package pccheck

import (
	"errors"
	"strings"
	"testing"
)

type fakeProc struct {
	elevated bool
	elErr    error
	idErr    error
	il       string
	pids     []uint32
	findErr  error
	tids     []uint32
	thrErr   error
	allow    uint32 // process rights that open successfully
	tallow   uint32 // thread rights that open successfully
}

func (f fakeProc) Elevated() (bool, error) { return f.elevated, f.elErr }
func (f fakeProc) Identity() (string, string, error) {
	il := f.il
	if il == "" {
		il = "Medium"
	}
	return "S-1-5-21-1", il, f.idErr
}
func (f fakeProc) FindAll(string) ([]uint32, error) {
	if f.pids == nil && f.findErr == nil {
		return []uint32{42}, nil
	}
	return f.pids, f.findErr
}
func (f fakeProc) Threads(uint32) ([]uint32, error) {
	if f.tids == nil && f.thrErr == nil {
		return []uint32{7, 8}, nil
	}
	return f.tids, f.thrErr
}
func (f fakeProc) Open(_, access uint32) error {
	if access&f.allow == access {
		return nil
	}
	return errors.New("Access is denied.")
}
func (f fakeProc) OpenThread(_, access uint32) error {
	if f.tallow != 0 && access&f.tallow == access {
		return nil
	}
	return errors.New("Access is denied.")
}

func TestCheckLocked(t *testing.T) {
	q := uint32(QueryLimited | 0x1)
	cases := []struct {
		name string
		p    fakeProc
		pass bool
		want string
	}{
		{"locked", fakeProc{allow: q}, true, "all 11 process rights and 8 rights on each of 2 threads refused"},
		{"identity shown", fakeProc{allow: q}, true, "[ran as S-1-5-21-1, Medium integrity]"},
		{"process rights", fakeProc{allow: q | 0x20 | 0x40000}, false, "memory write, change permissions"},
		{"thread rights", fakeProc{allow: q, tallow: 0x10}, false, "thread set context (thread 7), thread set context (thread 8)"},
		{"no query", fakeProc{allow: 0}, false, "proves nothing"},
		{"not running", fakeProc{pids: []uint32{}, allow: q}, false, "not running"},
		{"two copies", fakeProc{pids: []uint32{42, 43}, allow: q}, false, "2 copies"},
		{"find error", fakeProc{findErr: errors.New("boom"), allow: q}, false, "listing processes failed"},
		{"threads error", fakeProc{thrErr: errors.New("snap"), allow: q}, false, "cannot list the threads"},
		{"no threads", fakeProc{tids: []uint32{}, allow: q}, false, "cannot list the threads"},
		{"high integrity", fakeProc{il: "High", allow: q}, false, "Medium integrity, the level agents run at"},
		{"identity error", fakeProc{idErr: errors.New("x")}, false, "which account"},
		{"elevated", fakeProc{elevated: true}, false, "not elevated"},
		{"elevated error", fakeProc{elErr: errors.New("x")}, false, "cannot tell"},
	}
	for _, c := range cases {
		r := CheckLocked(c.p, "phonerunner-session.exe")
		if r.Pass != c.pass || !strings.Contains(r.Detail, c.want) {
			t.Errorf("%s: %s", c.name, r.Line())
		}
	}
	var w WinProc
	if _, err := w.Elevated(); err == nil {
		t.Fatal("off-Windows")
	}
	if _, _, err := w.Identity(); err == nil {
		t.Fatal("off-Windows")
	}
	if _, err := w.FindAll("x"); err == nil {
		t.Fatal("off-Windows")
	}
	if _, err := w.Threads(1); err == nil {
		t.Fatal("off-Windows")
	}
	if err := w.Open(1, 1); err == nil {
		t.Fatal("off-Windows")
	}
	if err := w.OpenThread(1, 1); err == nil {
		t.Fatal("off-Windows")
	}
}
