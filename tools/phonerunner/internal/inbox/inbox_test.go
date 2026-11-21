package inbox

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const goodHeader = `{"title":"Pod start","claimed_by":"PC lane","entry":"run.ps1","estimate_time":"5 min","estimate_cost":"$0"}`

func write(t *testing.T, dir string, files map[string]string) {
	t.Helper()
	for rel, body := range files {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func item(t *testing.T, files map[string]string) string {
	t.Helper()
	d := filepath.Join(t.TempDir(), "pod-start")
	write(t, d, files)
	return d
}

func has(list []string, sub string) bool {
	for _, s := range list {
		if strings.Contains(s, sub) {
			return true
		}
	}
	return false
}

func TestLoadGood(t *testing.T) {
	d := item(t, map[string]string{"item.json": goodHeader, "run.ps1": "Write-Output hi\n", "lib/helper.ps1": "# helper\n"})
	it, err := Load(d)
	if err != nil || !it.Runnable() {
		t.Fatal(err, it.Problems)
	}
	if len(it.Files) != 3 || it.Files[0].Rel != "item.json" || it.Files[1].Rel != "lib/helper.ps1" {
		t.Fatal(it.Files)
	}
	if len(it.Badges) != 0 || it.ManifestSHA != ManifestSHA(it.Files) || len(it.ManifestSHA) != 64 {
		t.Fatal(it)
	}
	if tm, c := it.Estimates(); tm != "5 min" || c != "$0" {
		t.Fatal(tm, c)
	}
	// One byte changed anywhere changes the manifest.
	write(t, d, map[string]string{"lib/helper.ps1": "# helper!\n"})
	it2, _ := Load(d)
	if it2.ManifestSHA == it.ManifestSHA {
		t.Fatal("manifest must change")
	}
}

func TestBadges(t *testing.T) {
	cases := map[string]string{
		"installs software":            "winget install foo",
		"reads a key or secret":        "$k = $env:RUNPOD_API_KEY",
		"starts a billed service":      "runpodctl create pod",
		"deletes files":                "Remove-Item x",
		"changes Windows settings":     "Set-ItemProperty -Path HKLM:\\x",
		"needs a Windows security box": "Start-Process x -Verb RunAs",
		"REMOTE CODE":                  "iex (iwr https://x)",
	}
	for want, script := range cases {
		it, _ := Load(item(t, map[string]string{"item.json": goodHeader, "run.ps1": script}))
		if !has(it.Badges, want) {
			t.Errorf("%q: badges %v", script, it.Badges)
		}
	}
	long := strings.Repeat("A", 220)
	it, _ := Load(item(t, map[string]string{"item.json": goodHeader, "run.ps1": "$b='" + long + "'"}))
	if !has(it.Badges, "REMOTE CODE") {
		t.Fatal("a long base64-looking blob must be flagged")
	}
	// Binary files are not scanned.
	it, _ = Load(item(t, map[string]string{"item.json": goodHeader, "run.ps1": "ok", "x.bin": "iex"}))
	if len(it.Badges) != 0 {
		t.Fatal(it.Badges)
	}
}

func TestProblems(t *testing.T) {
	cases := []struct {
		files map[string]string
		want  string
	}{
		{map[string]string{"run.ps1": "x"}, "title is missing"},
		{map[string]string{"item.json": `{"title":"t","claimed_by":"c","entry":"run.ps1","extra":1}`, "run.ps1": "x"}, "unknown field"},
		{map[string]string{"item.json": `{"title":"t","entry":"run.ps1"}`, "run.ps1": "x"}, "claimed_by is missing"},
		{map[string]string{"item.json": `{"title":"t","claimed_by":"c","entry":"run.py"}`, "run.py": "x"}, "must be a .ps1"},
		{map[string]string{"item.json": `{"title":"t","claimed_by":"c","entry":"../run.ps1"}`}, "must be a .ps1"},
		{map[string]string{"item.json": `{"title":"t","claimed_by":"c","entry":"go.ps1"}`, "run.ps1": "x"}, "not in the folder"},
	}
	for _, c := range cases {
		it, err := Load(item(t, c.files))
		if err != nil || it.Runnable() || !has(it.Problems, c.want) {
			t.Errorf("%v: %v %v", c.files, err, it.Problems)
		}
	}
	// Bad folder name.
	d := filepath.Join(t.TempDir(), "Bad Name")
	write(t, d, map[string]string{"item.json": goodHeader, "run.ps1": "x"})
	if it, _ := Load(d); !has(it.Problems, "folder name") {
		t.Fatal(it.Problems)
	}
	// Estimates missing show "not stated".
	it, _ := Load(item(t, map[string]string{"item.json": `{"title":"t","claimed_by":"c","entry":"run.ps1"}`, "run.ps1": "x"}))
	if tm, c := it.Estimates(); tm != NotStated || c != NotStated {
		t.Fatal(tm, c)
	}
}

func TestLimitsAndLinks(t *testing.T) {
	d := item(t, map[string]string{"item.json": goodHeader, "run.ps1": "x"})
	big := make([]byte, MaxFileBytes+1)
	if err := os.WriteFile(filepath.Join(d, "big.dat"), big, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(d, "run.ps1"), filepath.Join(d, "link.ps1")); err != nil {
		t.Fatal(err)
	}
	it, _ := Load(d)
	if !has(it.Problems, "big.dat: larger than") || !has(it.Problems, "link.ps1: links") {
		t.Fatal(it.Problems)
	}
	many := map[string]string{"item.json": goodHeader, "run.ps1": "x"}
	for i := 0; i < MaxFiles; i++ {
		many[filepath.ToSlash(filepath.Join("f", strings.Repeat("a", 1+i%5)+string(rune('a'+i%26))+string(rune('a'+i/26))))] = "y"
	}
	it, _ = Load(item(t, many))
	if !has(it.Problems, "at most 200") || len(it.Files) != MaxFiles {
		t.Fatal(len(it.Files), it.Problems)
	}
	// Unreadable file (a folder named like a file cannot be opened as one on read).
	if _, err := Load(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("missing folder must fail")
	}
	if _, err := readCapped(filepath.Join(d, "nope")); err == nil {
		t.Fatal("missing file must fail")
	}
}

func TestList(t *testing.T) {
	root := t.TempDir()
	write(t, filepath.Join(root, "b-item"), map[string]string{"item.json": goodHeader, "run.ps1": "x"})
	write(t, filepath.Join(root, "a-item"), map[string]string{"item.json": goodHeader, "run.ps1": "x"})
	write(t, root, map[string]string{"stray.txt": "ignored"})
	items, err := List(root)
	if err != nil || len(items) != 2 || items[0].ID != "a-item" {
		t.Fatal(items, err)
	}
	if _, err := List(filepath.Join(root, "missing")); err == nil {
		t.Fatal("missing inbox must fail")
	}
	// An item folder that cannot be walked fails the list.
	bad := filepath.Join(root, "c-item")
	write(t, bad, map[string]string{"run.ps1": "x"})
	walkErr := filepath.Join(bad, "locked")
	if err := os.Mkdir(walkErr, 0o000); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(walkErr, 0o700)
	if os.Getuid() != 0 { // root ignores permissions
		if _, err := List(root); err == nil {
			t.Fatal("unreadable item must fail the list")
		}
	}
}

func TestCopyApproved(t *testing.T) {
	src := item(t, map[string]string{"item.json": goodHeader, "run.ps1": "Write-Output hi\n", "lib/h.ps1": "#\n"})
	it, _ := Load(src)
	store := t.TempDir()
	dst := filepath.Join(store, "approved")
	if err := CopyApproved(src, dst, it.Files, it.ManifestSHA); err != nil {
		t.Fatal(err)
	}
	back, _ := Load(dst)
	if back.ManifestSHA != it.ManifestSHA {
		t.Fatal("copy differs")
	}
	if err := CopyApproved(src, dst, it.Files, it.ManifestSHA); err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatal(err)
	}
	// Manifest that does not match its own files.
	if err := CopyApproved(src, filepath.Join(store, "x1"), it.Files, "00"); !errors.Is(err, ErrCopyMismatch) {
		t.Fatal(err)
	}
	// A file changed after approval.
	write(t, src, map[string]string{"run.ps1": "Write-Output evil\n"})
	if err := CopyApproved(src, filepath.Join(store, "x2"), it.Files, it.ManifestSHA); !errors.Is(err, ErrCopyMismatch) {
		t.Fatal(err)
	}
	write(t, src, map[string]string{"run.ps1": "Write-Output hi\n"})
	// A new file appeared after approval.
	write(t, src, map[string]string{"extra.ps1": "#"})
	if err := CopyApproved(src, filepath.Join(store, "x3"), it.Files, it.ManifestSHA); !errors.Is(err, ErrCopyMismatch) {
		t.Fatal(err)
	}
	os.Remove(filepath.Join(src, "extra.ps1"))
	// A file vanished.
	os.Remove(filepath.Join(src, "lib", "h.ps1"))
	if err := CopyApproved(src, filepath.Join(store, "x4"), it.Files, it.ManifestSHA); err == nil {
		t.Fatal("vanished file must fail")
	}
	write(t, src, map[string]string{"lib/h.ps1": "#\n"})
	// Destination cannot be created (a file sits where a folder must go).
	blocker := filepath.Join(store, "blk")
	write(t, store, map[string]string{"blk": "file"})
	if err := CopyApproved(src, filepath.Join(blocker, "sub"), it.Files, it.ManifestSHA); err == nil {
		t.Fatal("uncreatable destination must fail")
	}
	// Writing fails: a folder exists where a file must be written.
	dst5 := filepath.Join(store, "x5")
	if err := os.MkdirAll(filepath.Join(dst5, "item.json"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := CopyApproved(src, filepath.Join(dst5), it.Files, it.ManifestSHA); err == nil {
		t.Fatal("existing destination must fail")
	}
	writeFile = func(string, []byte, os.FileMode) error { return errors.New("disk full") }
	if err := CopyApproved(src, filepath.Join(store, "x6"), it.Files, it.ManifestSHA); err == nil || !strings.Contains(err.Error(), "disk full") {
		t.Fatal(err)
	}
	writeFile = os.WriteFile
	load = func(string) (Item, error) { return Item{}, errors.New("gone") }
	defer func() { load = Load }()
	if err := CopyApproved(src, filepath.Join(store, "x7"), it.Files, it.ManifestSHA); err == nil || !strings.Contains(err.Error(), "gone") {
		t.Fatal(err)
	}
	if _, err := List(filepath.Dir(src)); err == nil {
		t.Fatal("a failing item must fail the list")
	}
	if _, err := readCapped(store); err == nil {
		t.Fatal("a folder is not a file")
	}
}

func TestChangesAndDiff(t *testing.T) {
	prev := []File{{Rel: "a", SHA256: "1"}, {Rel: "b", SHA256: "2"}, {Rel: "c", SHA256: "3"}}
	cur := []File{{Rel: "a", SHA256: "1"}, {Rel: "b", SHA256: "9"}, {Rel: "d", SHA256: "4"}}
	got := Changes(prev, cur)
	want := []Change{{"b", "changed"}, {"d", "added"}, {"c", "removed"}}
	if len(got) != 3 || got[0] != want[0] || got[1] != want[1] || got[2] != want[2] {
		t.Fatal(got)
	}
	d := LineDiff("a\r\nb\nc\n", "a\nx\nc\nd\n")
	if strings.Join(d, "|") != "  a|- b|+ x|  c|+ d" {
		t.Fatal(d)
	}
	if d := LineDiff("", "x"); strings.Join(d, "|") != "+ x" {
		t.Fatal(d)
	}
	if d := LineDiff("x\ny", ""); strings.Join(d, "|") != "- x|- y" {
		t.Fatal(d)
	}
	long := strings.Repeat("l\n", MaxDiffLines+1)
	if d := LineDiff(long, "x"); len(d) != 1 || !strings.Contains(d[0], "too long") {
		t.Fatal(d)
	}
}
