//go:build windows

package winsvc

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc/mgr"
	"tailscale.com/tsnet"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
)

// ServiceName is the Windows service name (also what the PC guard should protect).
const ServiceName = "PhoneRunner"

// DefaultRoot is the SYSTEM-only store.
func DefaultRoot() string { return filepath.Join(os.Getenv("ProgramData"), "PhoneRunner") }

// RequireElevated refuses desk commands from a non-elevated shell, so an agent
// running as Jake at normal rights cannot run them (the UAC box is Jake's).
func RequireElevated() error {
	if !windows.GetCurrentProcessToken().IsElevated() {
		return errors.New("run this from an elevated (Run as administrator) window; that Windows box is yours to approve")
	}
	return nil
}

func setACL(path, sddl string) error {
	sd, err := windows.SecurityDescriptorFromString(sddl)
	if err != nil {
		return err
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		return err
	}
	return windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, dacl, nil)
}

// Install creates the store with its permissions, writes default settings if none
// exist, and registers the service. viewer is the Windows user whose agents may
// read the store and write copy acknowledgements (Jake's own account name).
func Install(viewer string) error {
	if err := RequireElevated(); err != nil {
		return err
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	pf := strings.ToLower(os.Getenv("ProgramFiles")) + `\`
	if !strings.HasPrefix(strings.ToLower(exe), pf) {
		return fmt.Errorf("install refused: %s must sit under %s (an admin-only folder), so no agent can swap the service program", exe, pf)
	}
	sessionExe := filepath.Join(filepath.Dir(exe), "phonerunner-session.exe")
	if _, err := os.Stat(sessionExe); err != nil {
		return fmt.Errorf("install refused: %s is missing", sessionExe)
	}
	sid, _, _, err := windows.LookupSID("", viewer)
	if err != nil {
		return fmt.Errorf("install: user %q not found: %w", viewer, err)
	}
	user := sid.String()
	root := DefaultRoot()
	dirs := []struct{ path, sddl string }{
		{root, fmt.Sprintf("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;%s)", user)},
		{filepath.Join(root, "tsnet"), "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"},
		{filepath.Join(root, "ack"), fmt.Sprintf("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;%s)", user)},
	}
	for _, d := range dirs {
		if err := os.MkdirAll(d.path, 0o755); err != nil {
			return err
		}
		if err := setACL(d.path, d.sddl); err != nil {
			return fmt.Errorf("install: permissions on %s: %w", d.path, err)
		}
		fmt.Println("PASS permissions set:", d.path)
	}
	cfgPath := filepath.Join(root, "config.json")
	if _, err := os.Stat(cfgPath); errors.Is(err, os.ErrNotExist) {
		b, _ := config.Defaults().Marshal()
		if err := os.WriteFile(cfgPath, b, 0o644); err != nil {
			return err
		}
		fmt.Println("PASS default settings written (no phone paired yet):", cfgPath)
	}
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()
	s, err := m.CreateService(ServiceName, exe, mgr.Config{
		DisplayName: "PhoneRunner (watch-only)",
		Description: "Lets Jake's paired phone watch this PC over his private Tailscale network. Cannot run anything.",
		StartType:   mgr.StartAutomatic,
	}, "service")
	if err != nil {
		return fmt.Errorf("install: create service: %w", err)
	}
	defer s.Close()
	_ = s.SetRecoveryActions([]mgr.RecoveryAction{{Type: mgr.ServiceRestart, Delay: 10 * time.Second}, {Type: mgr.ServiceRestart, Delay: time.Minute}}, 86400)
	fmt.Println("PASS service registered:", ServiceName, "(not started; next: phonerunner-service login)")
	return nil
}

// Login joins the PhoneRunner device to Jake's tailnet. It prints the sign-in link
// Tailscale gives; Jake opens it and approves (his sign-in, never an agent's).
func Login() error {
	if err := RequireElevated(); err != nil {
		return err
	}
	cfg, err := config.Load(filepath.Join(DefaultRoot(), "config.json"))
	if err != nil {
		return err
	}
	ts := &tsnet.Server{
		Hostname: cfg.Hostname,
		Dir:      filepath.Join(DefaultRoot(), "tsnet"),
		Logf:     func(string, ...any) {},
		UserLogf: func(f string, a ...any) { fmt.Printf(f+"\n", a...) },
	}
	defer ts.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	if _, err := ts.Up(ctx); err != nil {
		return fmt.Errorf("FAIL login: %w", err)
	}
	if names := ts.CertDomains(); len(names) > 0 {
		fmt.Println("PASS joined your tailnet. Page address: https://" + names[0] + "/")
	} else {
		fmt.Println("FAIL joined, but HTTPS certificates are off for your tailnet; turn on HTTPS in the Tailscale admin DNS page, then rerun")
		return errors.New("https certificates off")
	}
	return nil
}

// Pair allows one phone. Jake reads the device ID and login off the phone's
// "Not allowed" page and confirms here by typing YES.
func Pair(nodeID, login string, in *bufio.Reader) error {
	if err := RequireElevated(); err != nil {
		return err
	}
	cfgPath := filepath.Join(DefaultRoot(), "config.json")
	cfg, err := config.Load(cfgPath)
	if err != nil {
		return err
	}
	fmt.Printf("Pair device ID %q signed in as %q?\nOnly do this if it is the ID your phone showed. Type YES: ", nodeID, login)
	line, _ := in.ReadString('\n')
	if strings.TrimSpace(line) != "YES" {
		return errors.New("FAIL not paired (you did not type YES)")
	}
	cfg.AllowedNodeIDs = []string{nodeID}
	cfg.AllowedLogin = login
	if err := cfg.Validate(); err != nil {
		return err
	}
	b, err := cfg.Marshal()
	if err != nil {
		return err
	}
	if err := os.WriteFile(cfgPath, b, 0o644); err != nil {
		return err
	}
	fmt.Println("PASS paired. Restart the service: sc stop PhoneRunner, then sc start PhoneRunner")
	return nil
}

// Uninstall removes the service registration. The store (logs, captures, settings)
// is kept: nothing is deleted without Jake's decision.
func Uninstall() error {
	if err := RequireElevated(); err != nil {
		return err
	}
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()
	s, err := m.OpenService(ServiceName)
	if err != nil {
		return err
	}
	defer s.Close()
	if err := s.Delete(); err != nil {
		return err
	}
	fmt.Println("PASS service removed. Data kept at", DefaultRoot(), "(delete it yourself only if you decide to)")
	return nil
}
