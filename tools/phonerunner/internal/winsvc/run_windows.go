//go:build windows

package winsvc

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sys/windows"
	"tailscale.com/tsnet"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/alert"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/approve"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/capture"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/control"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/gate"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/tsnetwho"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/web"
)

// Run is the whole service until ctx ends. root is the store folder, sessionExe the
// session part next to the service exe.
func Run(ctx context.Context, root, sessionExe string) error {
	st, err := store.Open(root)
	if err != nil {
		return err
	}
	cfgPath := filepath.Join(root, "private", "config.json")
	cfg, err := config.Load(cfgPath)
	if err != nil {
		_ = st.Append("service.config_error", map[string]any{"error": err.Error()})
		return err
	}
	ts := &tsnet.Server{
		Hostname: cfg.Hostname,
		Dir:      filepath.Join(root, "tsnet"),
		Logf:     func(string, ...any) {}, // Tailscale's own chatter is not logged (may name peers)
		UserLogf: func(f string, a ...any) { _ = st.Append("tailscale", map[string]any{"msg": fmt.Sprintf(f, a...)}) },
	}
	defer ts.Close()
	if _, err := ts.Up(ctx); err != nil {
		_ = st.Append("tailscale.not_up", map[string]any{"error": err.Error(), "fix": "run 'phonerunner-service login' at the desk"})
		return err
	}
	lc, err := ts.LocalClient()
	if err != nil {
		return err
	}
	pageURL := ""
	if names := ts.CertDomains(); len(names) > 0 {
		pageURL = "https://" + names[0] + "/"
	}
	clickURL := ""
	if cfg.NtfyClickLink {
		clickURL = pageURL // off by default: sending it tells ntfy.sh the tailnet host name
	}
	n := alert.New(cfg.NtfyServer, cfg.NtfyTopic, clickURL)
	svc := service.New(cfg, st, n, time.Now)
	if err := svc.WriteSessionSettings(); err != nil {
		_ = st.Append("service.session_settings_error", map[string]any{"error": err.Error()})
		return err
	}
	g := gate.New(tsnetwho.Adapter{Fn: lc.WhoIs}, cfg.AllowedNodeIDs, cfg.AllowedLogin, st.Logger())

	ln, err := ts.ListenTLS("tcp", ":443")
	if err != nil {
		return err
	}
	ctl, ap, err := runButton(root, pageURL, cfg, svc, st)
	if err != nil {
		_ = st.Append("service.run_button_error", map[string]any{"error": err.Error()})
		return err
	}
	desk := &control.Desk{Dir: filepath.Join(root, "private", "desk"), Reg: ap, Log: st.Logger(), Now: time.Now,
		Phone: func() string {
			if len(cfg.AllowedNodeIDs) == 0 {
				return ""
			}
			return cfg.AllowedNodeIDs[0]
		}}
	go func() {
		t := time.NewTicker(time.Second)
		defer t.Stop()
		logged := false
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if err := desk.Poll(); err != nil && !logged {
					_ = st.Append("desk.error", map[string]any{"error": err.Error()})
					logged = true
				}
			}
		}
	}()
	srv := &http.Server{Handler: web.Handler(svc, cfg, ctl, ap, g.Middleware), ReadHeaderTimeout: 10 * time.Second}
	go func() { <-ctx.Done(); srv.Close() }()
	go supervise(ctx, svc, st, sessionExe, filepath.Join(root, "session.json"))
	go func() {
		t := time.NewTicker(time.Duration(cfg.HeartbeatSeconds) * time.Second)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				svc.Refresh(ctx)
			}
		}
	}()
	svc.Started(ctx)
	_ = st.Append("service.listening", map[string]any{"url": pageURL, "paired": cfg.Paired()})
	if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

// runButton builds the passkey check, the runner and the control that joins
// them. The page address is the passkeys' origin, so it must be the tailnet
// HTTPS name.
func runButton(root, pageURL string, cfg config.Config, svc *service.Service, st *store.Store) (*control.Control, *approve.Approver, error) {
	if pageURL == "" {
		return nil, nil, errors.New("no HTTPS name for this device (turn on HTTPS certificates in the Tailscale admin DNS page)")
	}
	host := strings.TrimSuffix(strings.TrimPrefix(pageURL, "https://"), "/")
	ap, err := approve.New(host, "https://"+host, filepath.Join(root, "private", "passkeys.json"))
	if err != nil {
		return nil, nil, err
	}
	sysRoot, err := windows.GetSystemWindowsDirectory()
	if err != nil {
		return nil, nil, err
	}
	var ctl *control.Control
	run := runner.New(StartItem, st.Logger(), func(item, line string) { ctl.Keep(item, line) }, time.Now)
	ctl, err = control.New(control.Paths{
		Inbox:      filepath.Join(root, "inbox"),
		Approved:   filepath.Join(root, "approved"),
		Work:       filepath.Join(root, "work"),
		Output:     filepath.Join(root, "private", "output"),
		Ledger:     filepath.Join(root, "private", "approved.json"),
		SystemRoot: sysRoot,
	}, ap, run, svc.RunReady, st.Logger(), time.Now)
	return ctl, ap, err
}

// supervise keeps one session part running in the signed-in user's desktop and feeds
// its frames to the service. It retries with backoff and logs every exit.
func supervise(ctx context.Context, svc *service.Service, st *store.Store, exe, settingsPath string) {
	wait := 5 * time.Second
	for ctx.Err() == nil {
		child, err := LaunchSession(exe, []string{"--settings", settingsPath})
		if err != nil {
			_ = st.Append("session.launch_failed", map[string]any{"error": err.Error()})
		} else {
			_ = st.Append("session.started", map[string]any{"pid": child.PID})
			done := make(chan error, 1)
			go func() { done <- capture.Read(child.Out, func(f capture.Frame) { svc.Ingest(ctx, f) }) }()
			select {
			case <-ctx.Done():
				child.Stop()
			case err := <-done:
				msg := "pipe closed"
				if err != nil {
					msg = err.Error()
				}
				_ = st.Append("session.ended", map[string]any{"pid": child.PID, "reason": msg})
				child.Stop()
				wait = 5 * time.Second
			}
			child.Close()
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
		if wait < time.Minute {
			wait *= 2
		}
	}
}
