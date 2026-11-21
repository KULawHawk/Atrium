// Package runner runs one approved item at a time, from its protected copy, and
// keeps its output.
//
// What it runs is fixed here, not by the item: the pinned PowerShell under
// System32 with -NoProfile -NonInteractive -ExecutionPolicy Bypass -File and the
// entry script inside the approved copy, with the working folder set to that
// copy and a short, clean environment (no PATH entries from Jake's profile, no
// user module folder in PSModulePath). Each output line is key-redacted; it is
// kept on the PC, and logged (copied off) only when the item allows it.
// Stop ends the item's whole process tree (a Windows job object on the PC).
package runner

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"sync"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/redact"
)

// KeepLines is how many recent output lines the page shows.
const KeepLines = 200

// MaxLineBytes caps one output line.
const MaxLineBytes = 4096

// Spec is the exact process to start.
type Spec struct {
	Exe  string
	Args []string
	Dir  string
	Env  []string
}

// Proc is a started item.
type Proc interface {
	Output() io.Reader // stdout and stderr together
	Wait() (exitCode int, err error)
	Kill() error // the whole process tree
	// Close releases the output and handles. The runner calls it once, after
	// the output has been read to its end and Wait has returned; Wait itself
	// must not close the output, or the last lines could be lost.
	Close()
}

// Starter starts a Spec (on the PC: in Jake's session, locked down, in a job).
type Starter func(Spec) (Proc, error)

// Command builds the fixed command line for entry inside the approved copy.
// systemRoot is the Windows folder (C:\Windows). copyDir holds the approved
// bytes and is read-only to Jake's account; workDir is the run's own scratch
// folder (TEMP), kept apart so nothing written during the run lands among the
// approved files.
func Command(systemRoot, copyDir, workDir, entry string) Spec {
	ps := systemRoot + `\System32\WindowsPowerShell\v1.0\powershell.exe`
	return Spec{
		Exe:  ps,
		Args: []string{"-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(copyDir, entry)},
		Dir:  copyDir,
		Env:  CleanEnv(systemRoot, workDir),
	}
}

// CleanEnv is the whole environment an item gets.
func CleanEnv(systemRoot, temp string) []string {
	return []string{
		"SystemRoot=" + systemRoot,
		"windir=" + systemRoot,
		"PATH=" + systemRoot + `\System32;` + systemRoot + `;` + systemRoot + `\System32\WindowsPowerShell\v1.0`,
		"PATHEXT=.COM;.EXE;.BAT;.CMD",
		// Set explicitly: left unset, Windows PowerShell adds the user-writable
		// Documents\WindowsPowerShell\Modules and could autoload a planted module.
		"PSModulePath=" + systemRoot + `\System32\WindowsPowerShell\v1.0\Modules`,
		"TEMP=" + temp,
		"TMP=" + temp,
		"PHONERUNNER=1",
	}
}

// Options are per-item choices from item.json.
type Options struct {
	// OutputMayCopy lets output lines go into the event log, which is copied off
	// the PC. Off by default: output stays on the PC (the page and the keep file).
	OutputMayCopy bool
}

// Run is what the page shows about the current or last run.
type Run struct {
	ItemID      string    `json:"item_id"`
	ManifestSHA string    `json:"manifest_sha256"`
	Started     time.Time `json:"started"`
	Ended       time.Time `json:"ended,omitzero"`
	ExitCode    *int      `json:"exit_code,omitempty"`
	Error       string    `json:"error,omitempty"`
	Stopped     bool      `json:"stopped"`
	Lines       []string  `json:"lines"`
	Masked      int       `json:"masked"` // key-like spans blanked in the output
	Count       int       `json:"line_count"`
}

// Running reports whether the run has not ended.
func (r Run) Running() bool { return !r.Started.IsZero() && r.Ended.IsZero() }

// Errors.
var (
	ErrBusy       = errors.New("another item is still running; stop it or wait")
	ErrNotRunning = errors.New("nothing is running")
	// ErrAlreadyEnded means the item's main process ended on its own before the
	// Stop arrived; the run is recorded as ended, not stopped. Proc.Kill returns
	// it when the item's tree is already gone.
	ErrAlreadyEnded = errors.New("the item had already ended on its own; nothing was stopped")
)

// Runner runs at most one item at a time. Safe for concurrent use.
type Runner struct {
	start Starter
	log   func(string, map[string]any)
	keep  func(item, line string) // PC-only output file; never copied
	now   func() time.Time
	opts  Options

	mu     sync.Mutex
	cur    Run
	proc   Proc
	exited bool // the main process has ended (output may still be draining)
	done   chan struct{}
}

// New builds a Runner. keep receives every (redacted) output line for the
// PC-only output file.
func New(start Starter, log func(string, map[string]any), keep func(item, line string), now func() time.Time) *Runner {
	return &Runner{start: start, log: log, keep: keep, now: now}
}

// Start runs spec for the approved item. The caller has already passed the
// approval check and copied the exact approved bytes into spec.Dir.
func (r *Runner) Start(itemID, manifestSHA string, spec Spec, o Options) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.cur.Running() {
		return ErrBusy
	}
	p, err := r.start(spec)
	if err != nil {
		r.log("run.refused", map[string]any{"item": itemID, "error": err.Error()})
		return fmt.Errorf("runner: could not start: %w", err)
	}
	r.cur = Run{ItemID: itemID, ManifestSHA: manifestSHA, Started: r.now(), Lines: []string{}}
	r.proc = p
	r.exited = false
	r.opts = o
	r.done = make(chan struct{})
	r.log("run.started", map[string]any{"item": itemID, "manifest_sha256": manifestSHA})
	go r.follow(p, r.done)
	return nil
}

func (r *Runner) follow(p Proc, done chan struct{}) {
	defer close(done)
	// Wait on the main process while reading, so an exit is seen even if a
	// leftover child still holds the output pipe (on the PC, Wait then closes
	// the job, which ends that child and the pipe).
	type result struct {
		code int
		err  error
	}
	waited := make(chan result, 1)
	go func() {
		c, err := p.Wait()
		r.mu.Lock()
		r.exited = true
		r.mu.Unlock()
		waited <- result{c, err}
	}()
	br := bufio.NewReaderSize(p.Output(), MaxLineBytes)
	var buf []byte
	cut := false
	emit := func() {
		line := string(buf)
		if cut {
			line += " …(line cut at 4096 characters)"
		}
		r.add(line)
		buf, cut = buf[:0], false
	}
	for {
		chunk, more, err := br.ReadLine()
		if room := MaxLineBytes - len(buf); len(chunk) > room {
			chunk, cut = chunk[:room], true
		}
		buf = append(buf, chunk...)
		if err != nil {
			if len(buf) > 0 || cut {
				emit()
			}
			break
		}
		if !more {
			emit()
		}
	}
	w := <-waited
	p.Close()
	code, err := w.code, w.err
	r.mu.Lock()
	defer r.mu.Unlock()
	r.cur.Ended = r.now()
	r.cur.ExitCode = &code
	fields := map[string]any{"item": r.cur.ItemID, "exit_code": code, "stopped": r.cur.Stopped, "lines": r.cur.Count, "output_copied": r.opts.OutputMayCopy}
	if err != nil {
		r.cur.Error = err.Error()
		fields["error"] = err.Error()
	}
	r.proc = nil
	r.log("run.ended", fields)
}

func (r *Runner) add(line string) {
	res := redact.Text(line)
	r.mu.Lock()
	r.cur.Masked += res.Count
	r.cur.Count++
	r.cur.Lines = append(r.cur.Lines, res.Text)
	if len(r.cur.Lines) > KeepLines {
		r.cur.Lines = r.cur.Lines[len(r.cur.Lines)-KeepLines:]
	}
	item, mayCopy := r.cur.ItemID, r.opts.OutputMayCopy
	r.mu.Unlock()
	r.keep(item, res.Text)
	if mayCopy {
		r.log("run.line", map[string]any{"item": item, "line": res.Text})
	}
}

// Stop ends the running item's process tree. Stop is approved by a tap like Run.
// A Stop that arrives after the main process ended on its own (while its last
// output is still being read) returns ErrAlreadyEnded and the run is not marked
// stopped.
func (r *Runner) Stop() error {
	r.mu.Lock()
	if !r.cur.Running() || r.proc == nil {
		r.mu.Unlock()
		return ErrNotRunning
	}
	if r.exited {
		item := r.cur.ItemID
		r.mu.Unlock()
		r.log("run.stop_after_end", map[string]any{"item": item})
		return ErrAlreadyEnded
	}
	p, item := r.proc, r.cur.ItemID
	r.cur.Stopped = true // set first so the end record says stopped; undone if Kill fails
	r.mu.Unlock()
	if err := p.Kill(); err != nil {
		r.mu.Lock()
		r.cur.Stopped = false
		r.mu.Unlock()
		if errors.Is(err, ErrAlreadyEnded) {
			r.log("run.stop_after_end", map[string]any{"item": item})
			return ErrAlreadyEnded
		}
		return fmt.Errorf("runner: stop failed: %w", err)
	}
	r.log("run.stop", map[string]any{"item": item})
	return nil
}

// Current returns a copy of the current or last run.
func (r *Runner) Current() Run {
	r.mu.Lock()
	defer r.mu.Unlock()
	c := r.cur
	c.Lines = append([]string{}, r.cur.Lines...)
	return c
}

// Wait blocks until the current run has ended (tests and shutdown).
func (r *Runner) Wait() {
	r.mu.Lock()
	d := r.done
	r.mu.Unlock()
	if d != nil {
		<-d
	}
}
