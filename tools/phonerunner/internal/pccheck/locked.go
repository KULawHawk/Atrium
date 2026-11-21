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
	{"memory read", 0x0010},
	{"create child process", 0x0080},
	{"set quota", 0x0100},
	{"set information", 0x0200},
	{"suspend/resume", 0x0800},
	{"change permissions", 0x40000},
	{"change owner", 0x80000},
}

// DangerousThread lists the thread rights that must be refused on EVERY thread of
// the session part (threads created after launch get the token's default rights,
// so they are checked one by one).
var DangerousThread = []struct {
	Name string
	Mask uint32
}{
	{"thread suspend/resume", 0x0002},
	{"thread get context", 0x0008},
	{"thread set context", 0x0010},
	{"thread set information", 0x0020},
	{"thread impersonate", 0x0100},
	{"thread direct impersonation", 0x0200},
	{"thread change permissions", 0x40000},
	{"thread change owner", 0x80000},
}

// QueryLimited is the one right Jake should have (with terminate).
const QueryLimited = 0x1000

// ErrElevated means the check ran with admin rights, which bypass the lock-down,
// so its answer would prove nothing about agents.
var ErrElevated = errors.New("run this check from a normal (not elevated) window: admin rights bypass the lock-down")

// Self says who the running check is.
type Self interface {
	Elevated() (bool, error)
	Identity() (sid, integrity string, err error) // who this check runs as
}

// Proc is the platform part.
type Proc interface {
	Self
	FindAll(exe string) ([]uint32, error)
	Threads(pid uint32) ([]uint32, error)
	Open(pid, access uint32) error       // nil if the open succeeded
	OpenThread(tid, access uint32) error // nil if the open succeeded
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
	sid, il, err := p.Identity()
	if err != nil {
		return fail(test, "cannot tell which account this check runs as: %v", err)
	}
	who := fmt.Sprintf("[ran as %s, %s integrity]", sid, il)
	if il != "Medium" {
		return fail(test, "%s: run from a normal window at Medium integrity, the level agents run at", who)
	}
	pids, err := p.FindAll(exe)
	if err != nil {
		return fail(test, "%s: listing processes failed: %v", who, err)
	}
	switch len(pids) {
	case 0:
		return fail(test, "%s: %s is not running (start the service first)", who, exe)
	case 1:
	default:
		return fail(test, "%s: %d copies of %s are running (pids %v): a second one may be fake; tell Jake", who, len(pids), exe, pids)
	}
	pid := pids[0]
	if err := p.Open(pid, QueryLimited); err != nil {
		return fail(test, "%s: cannot even query %s (pid %d), so the test proves nothing: %v", who, exe, pid, err)
	}
	var allowed []string
	for _, d := range Dangerous {
		if p.Open(pid, d.Mask) == nil {
			allowed = append(allowed, d.Name)
		}
	}
	tids, err := p.Threads(pid)
	if err != nil || len(tids) == 0 {
		return fail(test, "%s: cannot list the threads of pid %d, so the test proves nothing: %v", who, pid, err)
	}
	for _, tid := range tids {
		for _, d := range DangerousThread {
			if p.OpenThread(tid, d.Mask) == nil {
				allowed = append(allowed, fmt.Sprintf("%s (thread %d)", d.Name, tid))
			}
		}
	}
	if len(allowed) > 0 {
		return fail(test, "%s: %s (pid %d) can be opened for: %s", who, exe, pid, strings.Join(allowed, ", "))
	}
	return Result{Test: test, Pass: true, Detail: fmt.Sprintf("%s: %s (pid %d): query allowed; all %d process rights and %d rights on each of %d threads refused", who, exe, pid, len(Dangerous), len(DangerousThread), len(tids))}
}
