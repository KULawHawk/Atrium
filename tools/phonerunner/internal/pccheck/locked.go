package pccheck

import (
	"errors"
	"fmt"
	"strings"
)

// T-16: an agent (any program running as Jake, not elevated) cannot open the
// running session part with rights that would let it inject code, change its
// memory or permissions, or steal its handles. It may only query and stop it.
//
// The other half of T-16, "a fake session part is rejected", holds by
// construction: the service reads frames only from the pipe it handed to the
// process it started, never from a name or port another program could claim.

// Dangerous lists the rights that must be refused, by name.
var Dangerous = []struct {
	Name string
	Mask uint32
}{
	{"create thread", 0x0002},
	{"memory operation", 0x0008},
	{"memory write", 0x0020},
	{"duplicate handles", 0x0040},
	{"set information", 0x0200},
	{"suspend/resume", 0x0800},
	{"change permissions", 0x40000},
	{"change owner", 0x80000},
}

// QueryLimited is the one right Jake should have (with terminate).
const QueryLimited = 0x1000

// ErrElevated means the check ran with admin rights, which bypass the lock-down,
// so its answer would prove nothing about agents.
var ErrElevated = errors.New("run this check from a normal (not elevated) window: admin rights bypass the lock-down")

// Proc is the platform part.
type Proc interface {
	Elevated() (bool, error)
	Find(exe string) (pid uint32, err error)
	Open(pid, access uint32) error // nil if the open succeeded
}

// CheckLocked is T-16.
func CheckLocked(p Proc, exe string) Result {
	const test = "T-16"
	el, err := p.Elevated()
	if err != nil {
		return fail(test, "cannot tell whether this window is elevated: %v", err)
	}
	if el {
		return fail(test, "%v", ErrElevated)
	}
	pid, err := p.Find(exe)
	if err != nil {
		return fail(test, "%s is not running (start the service first): %v", exe, err)
	}
	if err := p.Open(pid, QueryLimited); err != nil {
		return fail(test, "cannot even query %s (pid %d), so the test proves nothing: %v", exe, pid, err)
	}
	var allowed []string
	for _, d := range Dangerous {
		if p.Open(pid, d.Mask) == nil {
			allowed = append(allowed, d.Name)
		}
	}
	if len(allowed) > 0 {
		return fail(test, "%s (pid %d) can be opened for: %s", exe, pid, strings.Join(allowed, ", "))
	}
	return Result{Test: test, Pass: true, Detail: fmt.Sprintf("%s (pid %d): query allowed, all %d dangerous rights refused", exe, pid, len(Dangerous))}
}
