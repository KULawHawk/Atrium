package pccheck

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// T-07: no agent (anything running as Jake) can change the programs or the store,
// and none can read the private folders. Checked from the folders' own
// permissions, read without elevation.

// Well-known SIDs allowed to write. Everything else, Jake included, is untrusted.
const (
	SIDSystem         = "S-1-5-18"
	SIDAdministrators = "S-1-5-32-544"
	SIDTrustedInstall = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
)

var trusted = map[string]bool{SIDSystem: true, SIDAdministrators: true, SIDTrustedInstall: true}

// creatorSIDs stand for "whoever creates the child". They are safe to skip on
// inherit-only entries ONLY because the folder's own (non-inherit) entries are
// checked too: if no untrusted principal can create children, no untrusted
// principal can become a creator owner.
var creatorSIDs = map[string]bool{"S-1-3-0": true, "S-1-3-1": true}

// Access bits that let a holder change a file, its permissions or its owner.
const (
	writeBits = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000
	readBits  = 0x1 | 0x8 | 0x80000000 | 0x10000000
)

// ACE is one permission entry.
type ACE struct {
	SID   string
	Allow bool
	Mask  uint32
	// InheritOnly entries apply only to things created later inside a folder, not
	// to the folder itself. They are judged by the same rule, because they decide
	// what every new file there allows (for example each new picture).
	InheritOnly bool
}

// Perms is what the reader found for one path.
type Perms struct {
	Owner string
	ACEs  []ACE
}

// Rule says what may hold a path.
type Rule int

const (
	// NoWrite: only SYSTEM, Administrators and TrustedInstaller may change it.
	NoWrite Rule = iota
	// NoRead: as NoWrite, and nobody else may read it either.
	NoRead
)

// Target is one path to check.
type Target struct {
	Path    string
	Rule    Rule
	listErr error
}

// Lister lists the files directly inside a folder (for private\ and tsnet\).
type Lister func(dir string) ([]string, error)

// ListDir is the real Lister: every entry directly inside dir, full paths.
func ListDir(dir string) ([]string, error) {
	es, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(es))
	for _, e := range es {
		out = append(out, filepath.Join(dir, e.Name()))
	}
	return out, nil
}

// Targets lists what T-07 checks for an install. ack\ is left out on purpose: it
// is the one folder Jake's lane may write. The parent C:\Program Files is not
// checked; it is admin-only on a default Windows install.
func Targets(programDir, root string) []Target {
	return []Target{
		{Path: programDir, Rule: NoWrite},
		{Path: filepath.Join(programDir, "phonerunner-service.exe"), Rule: NoWrite},
		{Path: filepath.Join(programDir, "phonerunner-session.exe"), Rule: NoWrite},
		{Path: root, Rule: NoWrite},
		{Path: filepath.Join(root, "log"), Rule: NoWrite},
		{Path: filepath.Join(root, "log", "events.jsonl"), Rule: NoWrite},
		{Path: filepath.Join(root, "status.json"), Rule: NoWrite},
		{Path: filepath.Join(root, "heartbeat.json"), Rule: NoWrite},
		{Path: filepath.Join(root, "session.json"), Rule: NoWrite},
		{Path: filepath.Join(root, "private"), Rule: NoRead},
		{Path: filepath.Join(root, "private", "config.json"), Rule: NoRead},
		{Path: filepath.Join(root, "tsnet"), Rule: NoRead},
		{Path: filepath.Join(root, "captures"), Rule: NoRead},
	}
}

// WithFiles adds every file inside the NoRead folders (private\, tsnet\ and
// captures\, a file can carry its own entries). A folder it cannot list is
// returned as an error target that fails.
func WithFiles(ts []Target, list Lister) []Target {
	out := append([]Target{}, ts...)
	for _, t := range ts {
		if t.Rule != NoRead || filepath.Ext(t.Path) != "" {
			continue
		}
		files, err := list(t.Path)
		if err != nil {
			out = append(out, Target{Path: t.Path + string(filepath.Separator) + "*", Rule: NoRead, listErr: err})
			continue
		}
		for _, f := range files {
			out = append(out, Target{Path: f, Rule: NoRead})
		}
	}
	return out
}

// Problems returns what is wrong with p under r (empty means it passes).
func Problems(p Perms, r Rule) []string {
	var out []string
	if !trusted[p.Owner] {
		out = append(out, fmt.Sprintf("owner %s is not SYSTEM/Administrators/TrustedInstaller (an owner can rewrite permissions)", p.Owner))
	}
	for _, a := range p.ACEs {
		if !a.Allow || trusted[a.SID] || (a.InheritOnly && creatorSIDs[a.SID]) {
			continue
		}
		if a.Mask&writeBits != 0 {
			out = append(out, fmt.Sprintf("%s may change it (mask 0x%x)", a.SID, a.Mask))
		}
		if r == NoRead && a.Mask&readBits != 0 {
			out = append(out, fmt.Sprintf("%s may read it (mask 0x%x)", a.SID, a.Mask))
		}
	}
	return out
}

// Reader reads a path's owner and permission entries.
type Reader func(path string) (Perms, error)

// ErrUnsupportedPerms means this build cannot read Windows permissions.
var ErrUnsupportedPerms = errors.New("permission check runs only on Windows")

// CheckPerms is T-07.
func CheckPerms(read Reader, targets []Target) Result {
	const test = "T-07"
	var bad []string
	for _, t := range targets {
		if t.listErr != nil {
			bad = append(bad, fmt.Sprintf("%s: cannot list files: %v", t.Path, t.listErr))
			continue
		}
		p, err := read(t.Path)
		if err != nil {
			bad = append(bad, fmt.Sprintf("%s: cannot read permissions: %v", t.Path, err))
			continue
		}
		for _, pr := range Problems(p, t.Rule) {
			bad = append(bad, t.Path+": "+pr)
		}
	}
	if len(bad) > 0 {
		return fail(test, "%d problem(s): %s", len(bad), strings.Join(bad, "; "))
	}
	return Result{Test: test, Pass: true, Detail: fmt.Sprintf("%d paths: only SYSTEM/Administrators/TrustedInstaller can change them; private folders unreadable by others", len(targets))}
}
