package pccheck

import (
	"errors"
	"os"
	"path/filepath"
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
	if len(targets) != 13 {
		t.Fatal(len(targets))
	}
	ok := func(string) (Perms, error) {
		return Perms{Owner: SIDSystem, ACEs: []ACE{{SID: SIDSystem, Allow: true, Mask: 0x1f01ff}}}, nil
	}
	if r := CheckPerms(ok, targets); !r.Pass || !strings.HasPrefix(r.Line(), "PASS T-07 13 paths") {
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

func TestProblemsInheritOnly(t *testing.T) {
	// An inherit-only entry for an ordinary account decides what every new file
	// allows, so it fails like any other entry.
	p := Perms{Owner: SIDSystem, ACEs: []ACE{{SID: jake, Allow: true, Mask: 0x1, InheritOnly: true}}}
	if got := Problems(p, NoRead); len(got) != 1 || !strings.Contains(got[0], "may read") {
		t.Fatal(got)
	}
	// CREATOR GROUP on a non-inherit entry is NOT skipped.
	p = Perms{Owner: SIDSystem, ACEs: []ACE{{SID: "S-1-3-1", Allow: true, Mask: 0x2}}}
	if got := Problems(p, NoWrite); len(got) != 1 {
		t.Fatal(got)
	}
	// Read extended attributes (0x8) counts as read.
	p = Perms{Owner: SIDSystem, ACEs: []ACE{{SID: jake, Allow: true, Mask: 0x8}}}
	if got := Problems(p, NoRead); len(got) != 1 {
		t.Fatal(got)
	}
}

func TestWithFiles(t *testing.T) {
	ts := Targets(`C:\P`, `C:\D`)
	list := func(dir string) ([]string, error) {
		switch {
		case strings.HasSuffix(dir, "private"):
			return []string{dir + `\config.json`, dir + `\other.json`}, nil
		case strings.HasSuffix(dir, "tsnet"):
			return nil, errors.New("Access is denied.")
		}
		return []string{dir + `\shot1.png`}, nil
	}
	all := WithFiles(ts, list)
	if len(all) != len(ts)+4 {
		t.Fatal(len(all), all)
	}
	ok := func(string) (Perms, error) {
		return Perms{Owner: SIDSystem, ACEs: []ACE{{SID: SIDSystem, Allow: true, Mask: 0x1f01ff}}}, nil
	}
	r := CheckPerms(ok, all)
	if r.Pass || !strings.Contains(r.Detail, "tsnet"+string(filepath.Separator)+"*: cannot list files: Access is denied.") {
		t.Fatal(r.Line())
	}
}

func TestListDir(t *testing.T) {
	d := t.TempDir()
	if err := os.WriteFile(filepath.Join(d, "a.json"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := ListDir(d)
	if err != nil || len(got) != 1 || got[0] != filepath.Join(d, "a.json") {
		t.Fatal(got, err)
	}
	if _, err := ListDir(filepath.Join(d, "missing")); err == nil {
		t.Fatal("missing folder should fail")
	}
}
