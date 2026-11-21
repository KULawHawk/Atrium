package pccheck

import (
	"errors"
	"strings"
	"testing"
)

type fakeProc struct {
	elevated bool
	elErr    error
	findErr  error
	allow    uint32 // rights that open successfully
}

func (f fakeProc) Elevated() (bool, error)     { return f.elevated, f.elErr }
func (f fakeProc) Find(string) (uint32, error) { return 42, f.findErr }
func (f fakeProc) Open(_, access uint32) error {
	if access&f.allow == access {
		return nil
	}
	return errors.New("Access is denied.")
}

func TestCheckLocked(t *testing.T) {
	cases := []struct {
		p    fakeProc
		pass bool
		want string
	}{
		{fakeProc{allow: QueryLimited | 0x1}, true, "all 8 dangerous rights refused"},
		{fakeProc{allow: QueryLimited | 0x20 | 0x40000}, false, "memory write, change permissions"},
		{fakeProc{allow: 0}, false, "proves nothing"},
		{fakeProc{findErr: errors.New("none"), allow: QueryLimited}, false, "not running"},
		{fakeProc{elevated: true}, false, "not elevated"},
		{fakeProc{elErr: errors.New("x")}, false, "cannot tell"},
	}
	for _, c := range cases {
		r := CheckLocked(c.p, "phonerunner-session.exe")
		if r.Pass != c.pass || !strings.Contains(r.Detail, c.want) {
			t.Errorf("%+v: %s", c.p, r.Line())
		}
	}
	var w WinProc
	if _, err := w.Elevated(); err == nil {
		t.Fatal("off-Windows")
	}
	if _, err := w.Find("x"); err == nil {
		t.Fatal("off-Windows")
	}
	if err := w.Open(1, 1); err == nil {
		t.Fatal("off-Windows")
	}
}
