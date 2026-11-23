//go:build windows

package winsvc

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
	"golang.org/x/sys/windows/svc/mgr"
	"tailscale.com/tsnet"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/control"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/pccheck"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/tslog"
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

// ConfigPath is the settings file, in the SYSTEM+Administrators-only folder.
func ConfigPath() string { return filepath.Join(DefaultRoot(), "private", "config.json") }

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
		{filepath.Join(root, "private"), "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"},  // settings incl. ntfy topic
		{filepath.Join(root, "captures"), "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"}, // pictures (Decision 266 = A)
		{filepath.Join(root, "ack"), fmt.Sprintf("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;%s)", user)},
		// Run button: lanes stage items in inbox (Jake's account can write);
		// approved copies are read-only to Jake; each run's TEMP is in work.
		{filepath.Join(root, "inbox"), fmt.Sprintf("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;%s)", user)},
		{filepath.Join(root, "approved"), fmt.Sprintf("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;%s)", user)},
		{filepath.Join(root, "work"), fmt.Sprintf("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;%s)", user)},
		// PC-only run output, the passkeys and the desk's files inherit private's
		// SYSTEM+Administrators-only entries.
		{filepath.Join(root, "private", "output"), "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"},
		{filepath.Join(root, "private", "desk"), "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"},
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
	cfgPath := ConfigPath()
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
		DisplayName: "PhoneRunner",
		Description: "Lets Jake's paired phone watch this PC over his private Tailscale network, and run staged items only on his tap and phone unlock (Run button off until turned on at the desk).",
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
	cfg, err := config.Load(ConfigPath())
	if err != nil {
		return err
	}
	ts := &tsnet.Server{
		Hostname: cfg.Hostname,
		Dir:      filepath.Join(DefaultRoot(), "tsnet"),
		Logf:     func(string, ...any) {},
		UserLogf: tslog.Once(func(l string) { fmt.Println(l) }),
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
	cfgPath := ConfigPath()
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

// SetRunButton turns the phone's Run button on or off. On is refused unless the
// read-only T-01C check passes ("Always notify"), so the risk note's premise
// holds. Off needs no check.
func SetRunButton(on bool) error {
	if err := RequireElevated(); err != nil {
		return err
	}
	if on {
		r := pccheck.AlwaysNotify(readUAC)
		fmt.Println(r.Line())
		if !r.Pass {
			return errors.New("the Run button stays off until Always notify is on")
		}
	}
	cfgPath := ConfigPath()
	cfg, err := config.Load(cfgPath)
	if err != nil {
		return err
	}
	cfg.RunButton = on
	b, err := cfg.Marshal()
	if err != nil {
		return err
	}
	if err := os.WriteFile(cfgPath, b, 0o644); err != nil {
		return err
	}
	fmt.Printf("PASS Run button %s. Restart the service: sc stop PhoneRunner, then sc start PhoneRunner\n", map[bool]string{true: "on", false: "off"}[on])
	return nil
}

func readUAC(name string) (uint32, error) {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, `SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`, registry.QUERY_VALUE)
	if err != nil {
		return 0, err
	}
	defer k.Close()
	v, _, err := k.GetIntegerValue(name)
	return uint32(v), err
}

// AddPasskey opens the service's 5-minute registration window and confirms the
// phone's new passkey with the code Jake types here.
func AddPasskey(in io.Reader) error {
	if err := RequireElevated(); err != nil {
		return err
	}
	return control.AddPasskey(filepath.Join(DefaultRoot(), "private", "desk"), in, os.Stdout, time.Sleep, 300)
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
