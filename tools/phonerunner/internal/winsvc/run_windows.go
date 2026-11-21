//go:build windows

package winsvc

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"path/filepath"
	"time"

	"tailscale.com/tsnet"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/alert"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/capture"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/gate"
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
	cfgPath := filepath.Join(root, "config.json")
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
	n := alert.New(cfg.NtfyServer, cfg.NtfyTopic, pageURL)
	svc := service.New(cfg, st, n, time.Now)
	g := gate.New(tsnetwho.Adapter{Fn: lc.WhoIs}, cfg.AllowedNodeIDs, cfg.AllowedLogin, st.Logger())

	ln, err := ts.ListenTLS("tcp", ":443")
	if err != nil {
		return err
	}
	srv := &http.Server{Handler: web.Handler(svc, cfg, g.Middleware), ReadHeaderTimeout: 10 * time.Second}
	go func() { <-ctx.Done(); srv.Close() }()
	go supervise(ctx, svc, st, sessionExe, cfgPath)
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

// supervise keeps one session part running in the signed-in user's desktop and feeds
// its frames to the service. It retries with backoff and logs every exit.
func supervise(ctx context.Context, svc *service.Service, st *store.Store, exe, cfgPath string) {
	wait := 5 * time.Second
	for ctx.Err() == nil {
		child, err := LaunchSession(exe, []string{"--config", cfgPath})
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
