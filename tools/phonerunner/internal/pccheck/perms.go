package pccheck

import (
	"errors"
	"fmt"
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

// Access bits that let a holder change a file, its permissions or its owner.
const (
	writeBits = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000
	readBits  = 0x1 | 0x80000000 | 0x10000000
)

// ACE is one permission entry.
type ACE struct {
	SID   string
	Allow bool
	Mask  uint32
	// InheritOnly entries apply only to things created later inside a folder,
	// not to the folder itself; they are checked on those children instead.
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
	Path string
	Rule Rule
}

// Targets lists what T-07 checks for an install. ack\ is left out on purpose: it
// is the one folder Jake's lane may write.
func Targets(programDir, root string) []Target {
	return []Target{
		{programDir, NoWrite},
		{filepath.Join(programDir, "phonerunner-service.exe"), NoWrite},
		{filepath.Join(programDir, "phonerunner-session.exe"), NoWrite},
		{root, NoWrite},
		{filepath.Join(root, "log"), NoWrite},
		{filepath.Join(root, "private"), NoRead},
		{filepath.Join(root, "private", "config.json"), NoRead},
		{filepath.Join(root, "tsnet"), NoRead},
		{filepath.Join(root, "captures"), NoRead},
	}
}

// Problems returns what is wrong with p under r (empty means it passes).
func Problems(p Perms, r Rule) []string {
	var out []string
	if !trusted[p.Owner] {
		out = append(out, fmt.Sprintf("owner %s is not SYSTEM/Administrators/TrustedInstaller (an owner can rewrite permissions)", p.Owner))
	}
	for _, a := range p.ACEs {
		if !a.Allow || a.InheritOnly || trusted[a.SID] {
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
