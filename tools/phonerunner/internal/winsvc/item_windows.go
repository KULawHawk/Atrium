//go:build windows

package winsvc

import (
	"io"

	"golang.org/x/sys/windows"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
)

// itemProc adapts a launched item to runner.Proc.
type itemProc struct{ c *Child }

func (p itemProc) Output() io.Reader { return p.c.Out }

func (p itemProc) Wait() (int, error) {
	defer p.c.Close() // closing the job ends anything the item left behind
	if _, err := windows.WaitForSingleObject(p.c.Process, windows.INFINITE); err != nil {
		return -1, err
	}
	var code uint32
	if err := windows.GetExitCodeProcess(p.c.Process, &code); err != nil {
		return -1, err
	}
	return int(code), nil
}

func (p itemProc) Kill() error { return p.c.Stop() }

// StartItem is the runner.Starter on the PC: Jake's session, the locked-down
// process and thread rights of the session part, stdout and stderr on one pipe,
// and a kill-on-close job so Stop ends the whole tree.
func StartItem(s runner.Spec) (runner.Proc, error) {
	c, err := Launch(s.Exe, s.Args, Opts{Dir: s.Dir, Env: s.Env, StderrToOut: true, Job: true})
	if err != nil {
		return nil, err
	}
	return itemProc{c}, nil
}
