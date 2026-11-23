//go:build windows

package winsvc

import (
	"bytes"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-webauthn/webauthn/protocol"
	"golang.org/x/sys/windows"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/approve"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/control"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

// fakeApprover stands in for the passkey: every tap is approved, but the
// manifest re-check the real approver does is kept.
type fakeApprover struct {
	mu   sync.Mutex
	last approve.Request
}

func (a *fakeApprover) Begin(req approve.Request) (*protocol.CredentialAssertion, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.last = req
	return &protocol.CredentialAssertion{}, nil
}

func (a *fakeApprover) Finish(_ string, _ *protocol.ParsedCredentialAssertionData, manifest func(string) (string, error)) (approve.Request, error) {
	a.mu.Lock()
	req := a.last
	a.mu.Unlock()
	m, err := manifest(req.ItemID)
	if err != nil {
		return approve.Request{}, err
	}
	if m != req.ManifestSHA {
		return approve.Request{}, errors.New("manifest changed")
	}
	return req, nil
}

// startJobbed starts an item like StartItem does (one kill-on-close job for the
// whole tree, stderr into stdout) but as the test's own account.
func startJobbed(s runner.Spec) (runner.Proc, error) {
	c := exec.Command(s.Exe, s.Args...)
	c.Dir, c.Env = s.Dir, s.Env
	r, w := io.Pipe()
	c.Stdout, c.Stderr = w, w
	if err := c.Start(); err != nil {
		return nil, err
	}
	job, err := newKillJob()
	if err != nil {
		return nil, err
	}
	h, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(c.Process.Pid))
	if err != nil {
		return nil, err
	}
	err = windows.AssignProcessToJobObject(job, h)
	windows.CloseHandle(h)
	if err != nil {
		return nil, err
	}
	done := make(chan int, 1)
	go func() { c.Wait(); w.Close(); done <- c.ProcessState.ExitCode() }()
	return &waitOnly{c: c, out: r, done: done, job: job}, nil
}

var itemIDRe = regexp.MustCompile(`'(t20-(?:500|env|link)-\d+)'`)

// TestT20DeskSelfTest runs the desk script's step 9 (500 lines, clean
// environment, Stop, hard link) against the real control, runner and event
// store, with this test playing the phone. What it cannot cover: the passkey
// (approved by fakeApprover), the page itself, the service account and the
// folder lock on the approved copy (so the write-into-approved-copy check
// may FAIL here; the test then expects exactly that one recorded failure, and
// every later step still to run).
func TestT20DeskSelfTest(t *testing.T) {
	desk, err := filepath.Abs(filepath.Join("..", "..", "desk", "PHONERUNNER_DESK_T20.ps1"))
	if err != nil {
		t.Fatal(err)
	}
	base, err := os.MkdirTemp(os.Getenv("SystemDrive")+`\`, "pr-desk-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(base) })
	root := filepath.Join(base, "PhoneRunner")
	for _, d := range []string{"inbox", "approved", "work", `private\output`, "selftest"} {
		if err := os.MkdirAll(filepath.Join(root, d), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	// The service log as the desk script reads it: one start that failed to join
	// Tailscale, then a restart (seq counts from 1 again) that is listening.
	old, err := store.Open(root)
	if err != nil {
		t.Fatal(err)
	}
	old.Append("tailscale", map[string]any{"msg": "tsnet starting"})
	old.Append("tailscale.not_up", map[string]any{"error": "tsnet.Up: context canceled"})
	st, err := store.Open(root)
	if err != nil {
		t.Fatal(err)
	}
	st.Append("tailscale", map[string]any{"msg": "tsnet starting"})
	st.Append("service.listening", map[string]any{"url": "https://phonerunner.example.ts.net/", "paired": true})
	// A stand-in for a network filter: a certificate Windows does not trust.
	filter := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	defer filter.Close()
	_, port, _ := net.SplitHostPort(filter.Listener.Addr().String())
	sysRoot, _ := windows.GetSystemWindowsDirectory()
	var ctl *control.Control
	rn := runner.New(startJobbed, st.Logger(), func(item, line string) { ctl.Keep(item, line) }, time.Now)
	ctl, err = control.New(control.Paths{
		Inbox:      filepath.Join(root, "inbox"),
		Approved:   filepath.Join(root, "approved"),
		Work:       filepath.Join(root, "work"),
		Output:     filepath.Join(root, "private", "output"),
		Ledger:     filepath.Join(root, "private", "approved.json"),
		SystemRoot: sysRoot,
	}, &fakeApprover{}, rn, func() error { return nil }, st.Logger(), time.Now)
	if err != nil {
		t.Fatal(err)
	}

	ps := exec.Command(filepath.Join(sysRoot, `System32\WindowsPowerShell\v1.0\powershell.exe`),
		"-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", desk, "-SelfTestRoot", root, "-SelfTestTlsPort", port)
	var psOut bytes.Buffer
	ps.Stdout, ps.Stderr = &psOut, &psOut
	if err := ps.Start(); err != nil {
		t.Fatal(err)
	}
	psDone := make(chan error, 1)
	go func() { psDone <- ps.Wait() }()

	answers := filepath.Join(root, "selftest", "answers.txt")
	answer := func(s string) {
		f, err := os.OpenFile(answers, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			t.Error(err)
			return
		}
		f.WriteString(s + "\n")
		f.Close()
	}
	tap := func(id, action string) {
		if _, err := ctl.BeginTap("phone", id, action); err != nil {
			t.Errorf("%s tap on %s refused: %v", action, id, err)
			return
		}
		res, err := ctl.FinishTap("phone", &protocol.ParsedCredentialAssertionData{})
		t.Logf("PHONE %s %s -> %q %v", action, id, res.Done, err)
		if err != nil {
			t.Errorf("%s on %s failed: %v", action, id, err)
		}
	}
	var linkRefusal error
	seen := 0
	timeout := time.After(10 * time.Minute)
loop:
	for {
		select {
		case <-psDone:
			break loop
		case <-timeout:
			ps.Process.Kill()
			t.Fatalf("desk script did not finish in 10 minutes; output:\n%s", psOut.String())
		case <-time.After(300 * time.Millisecond):
		}
		b, _ := os.ReadFile(filepath.Join(root, "selftest", "ask.txt"))
		asks := strings.Split(string(b), "\n")
		for ; seen < len(asks)-1; seen++ {
			a := asks[seen]
			t.Logf("ASK %s", a)
			m := itemIDRe.FindStringSubmatch(a)
			switch {
			case strings.Contains(a, "Try tapping Run once"):
				_, linkRefusal = ctl.BeginTap("phone", m[1], "run")
				t.Logf("PHONE run %s -> %v", m[1], linkRefusal)
				answer("")
			case strings.Contains(a, "What did the phone show"):
				answer("") // a stray Enter must re-ask, not fail
				answer("Y")
			case strings.HasPrefix(a, "TAP STOP NOW"):
				tap(rn.Current().ItemID, "stop")
			case m != nil && strings.Contains(a, "tap Run"):
				tap(m[1], "run")
			}
		}
	}
	t.Logf("desk script output:\n%s", psOut.String())
	res, err := os.ReadFile(filepath.Join(root, "selftest", "result.txt"))
	if err != nil {
		t.Fatalf("no result file: %v", err)
	}
	text := string(res)
	lines := strings.Split(strings.TrimRight(text, "\r\n"), "\n")
	last := strings.TrimSpace(lines[len(lines)-1])
	t.Logf("RESULT LAST LINE: %s", last)

	if !errors.Is(linkRefusal, control.ErrNotRunnable) {
		t.Errorf("the hard-link item was not refused as not runnable: %v", linkRefusal)
	}
	for _, want := range []string{
		"PASS service-up check from the log: up at https://phonerunner.example.ts.net/",
		"PASS network check: the real controlplane.tailscale.com answered with a genuine certificate",
		"PASS network check: a stand-in filter certificate is reported as: this network blocks Tailscale:",
		"PASS t20-500-", "PASS approved copy made: t20-500-",
		"CHECK no-user-folders-in-environment PASS", "CHECK module-path-system-only PASS",
		"CHECK runs-from-approved-copy PASS", "CHECK temp-is-run-work-folder PASS", "CHECK can-write-temp PASS",
		"PASS Stop ended t20-env-", "and its child process",
		"was not copied or started (hard link refused)",
		"Please type Y or N", "PASS phone showed the hard-link problem",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("result is missing %q", want)
		}
	}
	switch {
	case strings.Contains(text, "CHECK cannot-write-into-approved-copy PASS"):
		if last != "SELFTEST T20: PASS (Run, 500-line output, clean environment, Stop of the whole tree, hard-link refusal)" {
			t.Errorf("all checks passed but the last line is %q", last)
		}
	case strings.Contains(text, "CHECK cannot-write-into-approved-copy FAIL"):
		// No folder lock here: exactly this one failure, recorded, and the run went on.
		if !strings.HasPrefix(last, "SELFTEST T20: FAIL (1 test step(s) failed: ") || !strings.Contains(last, "1 environment check(s) failed") {
			t.Errorf("expected exactly the one environment-check failure, got %q", last)
		}
	default:
		t.Errorf("no cannot-write-into-approved-copy line in the result")
	}
}
