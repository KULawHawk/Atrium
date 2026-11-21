//go:build windows

package winsvc

import (
	"io"
	"sync"

	"golang.org/x/sys/windows"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
)

// itemProc adapts a launched item to runner.Proc.
//
// Order at the end of a run: the main process exits, Wait closes only the job
// (ending anything the item left behind, which releases the pipe's write ends),
// the runner keeps reading the pipe to its end, and only then Close releases
// the read end and the process handle. Closing the pipe early would drop the
// last lines a script prints just before it exits.
type itemProc struct {
	c *Child

	mu      sync.Mutex
	jobDone bool
}

func (p *itemProc) Output() io.Reader { return p.c.Out }

func (p *itemProc) Wait() (int, error) {
	defer p.closeJob()
	if _, err := windows.WaitForSingleObject(p.c.Process, windows.INFINITE); err != nil {
		return -1, err
	}
	var code uint32
	if err := windows.GetExitCodeProcess(p.c.Process, &code); err != nil {
		return -1, err
	}
	return int(code), nil
}

// closeJob ends the item's tree once. After it, Kill has nothing left to end.
func (p *itemProc) closeJob() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.jobDone {
		p.jobDone = true
		windows.CloseHandle(p.c.Job)
		p.c.Job = 0
	}
}

func (p *itemProc) Kill() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.jobDone {
		return nil // the main process has exited and its tree is already ended
	}
	return p.c.Stop()
}

// Close releases the pipe's read end and the process handle, after the output
// has been read to its end.
func (p *itemProc) Close() {
	p.closeJob()
	p.c.Close()
}

// StartItem is the runner.Starter on the PC: Jake's session, the locked-down
// process and thread rights of the session part, stdout and stderr on one pipe,
// and a kill-on-close job so Stop ends the whole tree.
func StartItem(s runner.Spec) (runner.Proc, error) {
	c, err := Launch(s.Exe, s.Args, Opts{Dir: s.Dir, Env: s.Env, StderrToOut: true, Job: true})
	if err != nil {
		return nil, err
	}
	return &itemProc{c: c}, nil
}
