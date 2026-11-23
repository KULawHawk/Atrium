//go:build windows

package winsvc

import (
	"context"
	"errors"
	"io"
	"net/http"
	"os"
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
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/pccheck"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/tslog"
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
		UserLogf: tslog.Once(func(l string) { _ = st.Append("tailscale", map[string]any{"msg": l}) }),
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
	svc.SetRunCheck(func() error {
		if r := pccheck.AlwaysNotify(readUAC); !r.Pass {
			return errors.New(r.Line())
		}
		return nil
	})
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
			errTail := make(chan string, 1)
			go func() { errTail <- readTail(child.Err, SessionErrBytes) }()
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
				fields := map[string]any{"pid": child.PID, "reason": msg}
				if code, ok := exitCode(child.Process, 5*time.Second); ok {
					fields["exit_code"] = code
					fields["why"] = ExitWhy(code)
				}
				child.Stop()
				select {
				case t := <-errTail:
					// The raw error text stays on the PC (private\ is SYSTEM and
					// Administrators only, never copied off); the log, which is
					// copied off, gets only the exit code and a fixed reason.
					if t != "" && keepSessionErrors(st.Root(), t) == nil {
						fields["errors_in"] = `private\` + SessionErrFile
					}
				case <-time.After(5 * time.Second):
				}
				_ = st.Append("session.ended", fields)
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

// SessionErrFile holds the session part's last error output, PC-only.
const SessionErrFile = "session-errors.log"

// keepSessionErrors replaces private\session-errors.log with the latest text.
func keepSessionErrors(root, text string) error {
	dir := filepath.Join(root, "private")
	tmp := filepath.Join(dir, SessionErrFile+".tmp")
	if err := os.WriteFile(tmp, []byte(time.Now().UTC().Format(time.RFC3339)+"\r\n"+text+"\r\n"), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(dir, SessionErrFile))
}

// ExitWhy turns a session part exit code into a fixed phrase for the log (no
// program output ever reaches the copied-off log).
func ExitWhy(code uint32) string {
	switch code {
	case 0:
		return "exited normally"
	case 0xC0000142:
		return "could not start (Windows refused to load it: STATUS_DLL_INIT_FAILED)"
	case 0xC0000005:
		return "crashed (access violation)"
	case 2:
		return "stopped with an error (Go runtime exit 2)"
	case 1:
		return "stopped with an error (exit 1)"
	}
	return "stopped (other exit code)"
}

// SessionErrBytes is how much of the session part's error output is kept in the
// PC-only file: the first lines say why it stopped (a Go crash dump is cut).
const SessionErrBytes = 1500

// readTail returns up to max bytes from the start of r, then reads r to its end so
// the child never blocks on a full pipe.
func readTail(r *os.File, max int) string {
	if r == nil {
		return ""
	}
	b, _ := io.ReadAll(io.LimitReader(r, int64(max)))
	_, _ = io.Copy(io.Discard, r)
	return strings.TrimSpace(string(b))
}

// exitCode waits up to d for the process to end and returns its exit code.
func exitCode(p windows.Handle, d time.Duration) (uint32, bool) {
	if ev, err := windows.WaitForSingleObject(p, uint32(d/time.Millisecond)); err != nil || ev != windows.WAIT_OBJECT_0 {
		return 0, false
	}
	var code uint32
	if err := windows.GetExitCodeProcess(p, &code); err != nil {
		return 0, false
	}
	return code, true
}
