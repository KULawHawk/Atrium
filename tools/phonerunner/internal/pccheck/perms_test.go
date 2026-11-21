package pccheck

import (
	"errors"
	"strings"
	"testing"
)

const jake = "S-1-5-21-1-2-3-1001"

func TestProblems(t *testing.T) {
	good := Perms{Owner: SIDAdministrators, ACEs: []ACE{
		{SID: SIDSystem, Allow: true, Mask: 0x1f01ff},
		{SID: SIDAdministrators, Allow: true, Mask: 0x1f01ff},
		{SID: jake, Allow: true, Mask: 0x1200a9},                           // read + execute
		{SID: "S-1-3-0", Allow: true, Mask: 0x10000000, InheritOnly: true}, // CREATOR OWNER, children only
		{SID: jake, Allow: false, Mask: 0x1f01ff},                          // a deny never hurts
	}}
	if p := Problems(good, NoWrite); len(p) != 0 {
		t.Fatal(p)
	}
	if p := Problems(good, NoRead); len(p) != 1 || !strings.Contains(p[0], "may read") {
		t.Fatal(p)
	}
	bad := Perms{Owner: jake, ACEs: []ACE{{SID: jake, Allow: true, Mask: 0x40000}}}
	if p := Problems(bad, NoWrite); len(p) != 2 {
		t.Fatal(p)
	}
}

func TestCheckPerms(t *testing.T) {
	targets := Targets(`C:\Program Files\PhoneRunner`, `C:\ProgramData\PhoneRunner`)
	if len(targets) != 9 {
		t.Fatal(len(targets))
	}
	ok := func(string) (Perms, error) {
		return Perms{Owner: SIDSystem, ACEs: []ACE{{SID: SIDSystem, Allow: true, Mask: 0x1f01ff}}}, nil
	}
	if r := CheckPerms(ok, targets); !r.Pass || !strings.HasPrefix(r.Line(), "PASS T-07 9 paths") {
		t.Fatal(r.Line())
	}
	mixed := func(p string) (Perms, error) {
		if strings.HasSuffix(p, "captures") {
			return Perms{}, errors.New("denied")
		}
		if strings.HasSuffix(p, ".exe") {
			return Perms{Owner: SIDSystem, ACEs: []ACE{{SID: jake, Allow: true, Mask: 0x2}}}, nil
		}
		return ok(p)
	}
	r := CheckPerms(mixed, targets)
	if r.Pass || !strings.Contains(r.Detail, "3 problem(s)") || !strings.Contains(r.Detail, "cannot read permissions") {
		t.Fatal(r.Line())
	}
	if _, err := ReadPerms("x"); err == nil {
		t.Fatal("off-Windows reader should refuse")
	}
}
