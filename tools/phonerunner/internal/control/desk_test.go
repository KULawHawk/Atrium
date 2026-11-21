package control

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/approve"
)

type fakeReg struct {
	opened  string
	waiting string
	conf    string
}

func (f *fakeReg) OpenRegistration(p string) { f.opened = p }
func (f *fakeReg) Waiting() (string, bool)   { return f.waiting, f.waiting != "" }
func (f *fakeReg) Confirm(code string) error {
	f.conf = code
	if code != f.waiting {
		return approve.ErrConfirmMismatch
	}
	f.waiting = ""
	return nil
}

func readState(t *testing.T, dir string) DeskState {
	t.Helper()
	var s DeskState
	b, err := os.ReadFile(filepath.Join(dir, "state.json"))
	if err != nil || json.Unmarshal(b, &s) != nil {
		t.Fatal(err)
	}
	return s
}

func newDesk(t *testing.T, reg *fakeReg, phone string) (*Desk, *logs) {
	l := &logs{}
	return &Desk{Dir: t.TempDir(), Reg: reg, Phone: func() string { return phone }, Log: l.log, Now: time.Now}, l
}

func TestDeskPollFlow(t *testing.T) {
	reg := &fakeReg{}
	d, l := newDesk(t, reg, "phone-node")
	if err := d.Poll(); err != nil || readState(t, d.Dir).Open {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(d.Dir, "open.json"), []byte("{}"), 0o600)
	d.Poll()
	if reg.opened != "phone-node" || !readState(t, d.Dir).Open || !l.has("passkey.window_opened") {
		t.Fatal(reg.opened)
	}
	if _, err := os.Stat(filepath.Join(d.Dir, "open.json")); err == nil {
		t.Fatal("request must be consumed")
	}
	reg.waiting = "abcd1234"
	d.Poll()
	if readState(t, d.Dir).Waiting != "abcd1234" {
		t.Fatal("waiting code not shown")
	}
	os.WriteFile(filepath.Join(d.Dir, "confirm.json"), []byte(`{"code":"wrong"}`), 0o600)
	d.Poll()
	if s := readState(t, d.Dir); !strings.HasPrefix(s.Result, "FAIL") || !l.has("passkey.refused") {
		t.Fatal(s)
	}
	os.WriteFile(filepath.Join(d.Dir, "confirm.json"), []byte(`{"code":" abcd1234 "}`), 0o600)
	d.Poll()
	if s := readState(t, d.Dir); s.Result != ResultStored || s.Open || !l.has("passkey.stored") {
		t.Fatal(s)
	}
}

func TestDeskPollRefusalsAndErrors(t *testing.T) {
	reg := &fakeReg{}
	d, _ := newDesk(t, reg, "")
	os.WriteFile(filepath.Join(d.Dir, "open.json"), []byte("{}"), 0o600)
	d.Poll()
	if s := readState(t, d.Dir); !strings.Contains(s.Result, "no phone is paired") || reg.opened != "" {
		t.Fatal(s)
	}
	removeFile = func(string) error { return errors.New("denied") }
	defer func() { removeFile = os.Remove }()
	os.WriteFile(filepath.Join(d.Dir, "open.json"), []byte("{}"), 0o600)
	if err := d.Poll(); err == nil {
		t.Fatal("must fail")
	}
	os.Remove(filepath.Join(d.Dir, "open.json"))
	os.WriteFile(filepath.Join(d.Dir, "confirm.json"), []byte("{}"), 0o600)
	if err := d.Poll(); err == nil {
		t.Fatal("must fail")
	}
	removeFile = os.Remove
	os.Remove(filepath.Join(d.Dir, "confirm.json"))
	os.MkdirAll(filepath.Join(d.Dir, "state.json.tmp"), 0o700)
	if err := d.Poll(); err == nil {
		t.Fatal("must fail on a blocked state file")
	}
}

// service plays the running service: each sleep the desk command takes is one
// Poll.
func service(d *Desk, onPoll func(int)) func(time.Duration) {
	n := 0
	return func(time.Duration) { n++; onPoll(n); d.Poll() }
}

func TestAddPasskeyPass(t *testing.T) {
	reg := &fakeReg{}
	d, _ := newDesk(t, reg, "phone")
	var out strings.Builder
	sleep := service(d, func(n int) {
		if n == 2 {
			reg.waiting = "abcd1234" // the phone's passkey arrives
		}
	})
	if err := AddPasskey(d.Dir, strings.NewReader("abcd1234\n"), &out, sleep, 10); err != nil {
		t.Fatal(err, out.String())
	}
	if !strings.Contains(out.String(), ResultStored) || reg.conf != "abcd1234" {
		t.Fatal(out.String())
	}
}

func TestAddPasskeyFails(t *testing.T) {
	reg := &fakeReg{}
	d, _ := newDesk(t, reg, "phone")
	var out strings.Builder
	sleep := service(d, func(n int) { reg.waiting = "abcd1234" })
	if err := AddPasskey(d.Dir, strings.NewReader("zzzz\n"), &out, sleep, 10); err == nil || !strings.Contains(err.Error(), "does not match") {
		t.Fatal(err)
	}
	// Not paired: the service says so at once.
	d2, _ := newDesk(t, &fakeReg{}, "")
	if err := AddPasskey(d2.Dir, strings.NewReader(""), &out, service(d2, func(int) {}), 10); err == nil || !strings.Contains(err.Error(), "no phone is paired") {
		t.Fatal(err)
	}
	// No service running: times out with a reason.
	dir := t.TempDir()
	if err := AddPasskey(dir, strings.NewReader(""), &out, func(time.Duration) {}, 3); !errors.Is(err, ErrDeskTimeout) {
		t.Fatal(err)
	}
	// The phone never sends its code after the window opened: times out too.
	reg3 := &fakeReg{}
	d3, _ := newDesk(t, reg3, "phone")
	n := 0
	sleep3 := func(time.Duration) {
		n++
		if n == 1 {
			reg3.waiting = "abcd1234"
		}
		if n == 1 {
			d3.Poll()
		}
	}
	if err := AddPasskey(d3.Dir, strings.NewReader("abcd1234\n"), &out, sleep3, 4); !errors.Is(err, ErrDeskTimeout) {
		t.Fatal(err)
	}
	// The desk folder is missing or blocked.
	if err := AddPasskey(filepath.Join(dir, "missing"), strings.NewReader(""), &out, func(time.Duration) {}, 1); err == nil {
		t.Fatal("must fail")
	}
	d4, _ := newDesk(t, &fakeReg{}, "phone")
	reg4 := d4.Reg.(*fakeReg)
	os.MkdirAll(filepath.Join(d4.Dir, "confirm.json"), 0o700)
	sleep4 := service(d4, func(int) { reg4.waiting = "abcd1234" })
	if err := AddPasskey(d4.Dir, strings.NewReader("abcd1234\n"), &out, sleep4, 10); err == nil {
		t.Fatal("blocked confirm file must fail")
	}
}
