package runner

import (
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeProc struct {
	out     io.Reader
	waitCh  chan struct{}
	code    int
	waitErr error
	killErr error
	once    sync.Once
	killed  bool
	closed  int
}

func (f *fakeProc) Close() { f.closed++ }

func (f *fakeProc) Output() io.Reader { return f.out }
func (f *fakeProc) Wait() (int, error) {
	<-f.waitCh
	return f.code, f.waitErr
}
func (f *fakeProc) Kill() error {
	if f.killErr != nil {
		return f.killErr
	}
	f.killed = true
	f.once.Do(func() { close(f.waitCh) })
	return nil
}

type logSink struct {
	mu     sync.Mutex
	events []string
	kept   []string
}

func (l *logSink) log(e string, f map[string]any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.events = append(l.events, e)
}

func (l *logSink) keep(item, line string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.kept = append(l.kept, line)
}

func (l *logSink) has(e string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	for _, x := range l.events {
		if x == e {
			return true
		}
	}
	return false
}

func clock() time.Time { return time.Date(2026, 11, 21, 4, 0, 0, 0, time.UTC) }

func TestCommandIsFixed(t *testing.T) {
	s := Command(`C:\Windows`, `C:\ProgramData\PhoneRunner\approved\pod-start-1`, `C:\ProgramData\PhoneRunner\work\pod-start-1`, "run.ps1")
	if s.Exe != `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` {
		t.Fatal(s.Exe)
	}
	if strings.Join(s.Args[:5], " ") != "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File" || !strings.HasSuffix(s.Args[5], "run.ps1") {
		t.Fatal(s.Args)
	}
	if s.Dir != `C:\ProgramData\PhoneRunner\approved\pod-start-1` {
		t.Fatal(s.Dir)
	}
	for _, e := range s.Env {
		if strings.Contains(e, "Users") || strings.Contains(e, "Documents") || strings.Contains(e, "USERPROFILE") {
			t.Fatal("environment must be clean: ", e)
		}
	}
	if !strings.Contains(strings.Join(s.Env, ";"), `TEMP=C:\ProgramData\PhoneRunner\work\pod-start-1`) || len(s.Env) != 8 {
		t.Fatal(s.Env)
	}
}

func TestRunToEnd(t *testing.T) {
	long := strings.Repeat("x", MaxLineBytes+10)
	out := "hello\nkey sk-ant-api03-" + strings.Repeat("Q", 90) + "\n" + long + "\nlast"
	p := &fakeProc{out: strings.NewReader(out), waitCh: make(chan struct{}), code: 3}
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	if err := r.Start("pod-start", "abc", Spec{}, Options{}); err != nil {
		t.Fatal(err)
	}
	r.Wait()
	c := r.Current()
	if c.Running() || c.ExitCode == nil || *c.ExitCode != 3 || c.Error != "" {
		t.Fatalf("%+v", c)
	}
	if len(c.Lines) != 4 || c.Lines[0] != "hello" || c.Lines[3] != "last" {
		t.Fatal(c.Lines)
	}
	if strings.Contains(c.Lines[1], "QQQQ") || c.Masked == 0 {
		t.Fatal("key not redacted: ", c.Lines[1])
	}
	if !strings.HasSuffix(c.Lines[2], "(line cut at 4096 characters)") || len(c.Lines[2]) > MaxLineBytes+40 {
		t.Fatal(len(c.Lines[2]))
	}
	for _, e := range []string{"run.started", "run.ended"} {
		if !l.has(e) {
			t.Fatal("missing log event ", e)
		}
	}
	// Output is held on the PC by default: kept, never in the copied log.
	if l.has("run.line") || len(l.kept) != 4 || c.Count != 4 {
		t.Fatal("output must stay off the copied log by default")
	}
}

func TestKeepsLastLinesAndWaitError(t *testing.T) {
	var b strings.Builder
	for i := 0; i < KeepLines+50; i++ {
		b.WriteString("line\n")
	}
	b.WriteString("final\n")
	p := &fakeProc{out: strings.NewReader(b.String()), waitCh: make(chan struct{}), waitErr: errors.New("lost")}
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	r.Wait()
	c := r.Current()
	if len(c.Lines) != KeepLines || c.Lines[KeepLines-1] != "final" || c.Error != "lost" {
		t.Fatal(len(c.Lines), c.Error)
	}
}

func TestBusyStopAndRefusals(t *testing.T) {
	pr, pw := io.Pipe()
	p := &fakeProc{out: pr, waitCh: make(chan struct{}), code: 1}
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	if err := r.Stop(); !errors.Is(err, ErrNotRunning) {
		t.Fatal(err)
	}
	r.Wait() // nothing started: returns at once
	if err := r.Start("a", "b", Spec{}, Options{}); err != nil {
		t.Fatal(err)
	}
	if err := r.Start("c", "d", Spec{}, Options{}); !errors.Is(err, ErrBusy) {
		t.Fatal(err)
	}
	p.killErr = errors.New("denied")
	if err := r.Stop(); err == nil || !strings.Contains(err.Error(), "stop failed") {
		t.Fatal(err)
	}
	if r.Current().Stopped {
		t.Fatal("a failed stop must not read as stopped")
	}
	p.killErr = nil
	if err := r.Stop(); err != nil {
		t.Fatal(err)
	}
	pw.Close()
	r.Wait()
	if c := r.Current(); !c.Stopped || c.Running() {
		t.Fatalf("%+v", c)
	}
	if !l.has("run.stop") {
		t.Fatal("stop not logged")
	}
	bad := New(func(Spec) (Proc, error) { return nil, errors.New("no session") }, l.log, l.keep, clock)
	if err := bad.Start("a", "b", Spec{}, Options{}); err == nil || !strings.Contains(err.Error(), "no session") {
		t.Fatal(err)
	}
	if !l.has("run.refused") {
		t.Fatal("refusal not logged")
	}
}

func TestPartialLineAtEnd(t *testing.T) {
	long := strings.Repeat("y", MaxLineBytes+5) // no newline, longer than the cap
	p := &fakeProc{out: strings.NewReader(long), waitCh: make(chan struct{})}
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	r.Wait()
	if c := r.Current(); len(c.Lines) != 1 || !strings.Contains(c.Lines[0], "line cut") {
		t.Fatal(c.Lines)
	}
}

type errReader struct{}

func (errReader) Read([]byte) (int, error) { return 0, io.ErrUnexpectedEOF }

func TestOutputBreaksMidLine(t *testing.T) {
	// A full buffer with no newline, then the pipe breaks: the part read is kept.
	out := io.MultiReader(strings.NewReader(strings.Repeat("z", MaxLineBytes)), errReader{})
	p := &fakeProc{out: out, waitCh: make(chan struct{})}
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	r.Wait()
	if c := r.Current(); len(c.Lines) != 1 || len(c.Lines[0]) != MaxLineBytes {
		t.Fatal(len(c.Lines))
	}
}

func TestOutputMayCopy(t *testing.T) {
	p := &fakeProc{out: strings.NewReader("a\nb\n"), waitCh: make(chan struct{})}
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{OutputMayCopy: true})
	r.Wait()
	if !l.has("run.line") || len(l.kept) != 2 {
		t.Fatal("may_copy output goes to both")
	}
}

// closingProc closes its own output when Wait returns, as the PC's job close does.
type closingProc struct {
	fakeProc
	w *io.PipeWriter
}

func (c *closingProc) Wait() (int, error) {
	<-c.waitCh
	c.w.Close()
	return 0, nil
}

func TestExitSeenWhilePipeHeld(t *testing.T) {
	pr, pw := io.Pipe()
	p := &closingProc{fakeProc: fakeProc{out: pr, waitCh: make(chan struct{})}, w: pw}
	close(p.waitCh) // the main process has exited; nothing closed the pipe yet
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	done := make(chan struct{})
	go func() { r.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("the run must end when the main process ends")
	}
}

func TestPSModulePathIsSystemOnly(t *testing.T) {
	env := strings.Join(CleanEnv(`C:\Windows`, `C:\w`), "|")
	if !strings.Contains(env, `PSModulePath=C:\Windows\System32\WindowsPowerShell\v1.0\Modules|`) {
		t.Fatal(env)
	}
}

// eofCheck reports, when its reader reaches the end, whether Close had
// already been called.
type eofCheck struct {
	r       io.Reader
	p       *fakeProc
	early   bool
	reached bool
}

func (e *eofCheck) Read(b []byte) (int, error) {
	n, err := e.r.Read(b)
	if err == io.EOF && !e.reached {
		e.reached = true
		e.early = e.p.closed > 0
	}
	return n, err
}

func TestLastLinesKeptWhenExitIsImmediate(t *testing.T) {
	// The script prints 500 lines and exits at once: every line arrives, and
	// the output is closed only after it has been read to its end, once.
	var b strings.Builder
	for i := 1; i <= 500; i++ {
		b.WriteString("line ")
		b.WriteString(strings.Repeat("n", i%7))
		b.WriteString("\n")
	}
	b.WriteString("PASS T-05\n")
	p := &fakeProc{waitCh: make(chan struct{})}
	ec := &eofCheck{r: strings.NewReader(b.String()), p: p}
	p.out = ec
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	r.Wait()
	c := r.Current()
	if c.Count != 501 || c.Lines[len(c.Lines)-1] != "PASS T-05" || len(l.kept) != 501 {
		t.Fatal(c.Count, len(l.kept))
	}
	if ec.early || !ec.reached || p.closed != 1 {
		t.Fatal("output closed before it was read to the end, or not exactly once: ", ec.early, p.closed)
	}
}

func TestStopAfterOwnEndIsNotStopped(t *testing.T) {
	// The main process ended on its own; its output is still being read.
	pr, pw := io.Pipe()
	p := &fakeProc{out: pr, waitCh: make(chan struct{})}
	close(p.waitCh)
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	for {
		r.mu.Lock()
		e := r.exited
		r.mu.Unlock()
		if e {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if err := r.Stop(); !errors.Is(err, ErrAlreadyEnded) {
		t.Fatal(err)
	}
	pw.Close()
	r.Wait()
	if c := r.Current(); c.Stopped || p.killed || !l.has("run.stop_after_end") {
		t.Fatalf("%+v killed=%v", c, p.killed)
	}
}

func TestKillReportsAlreadyEnded(t *testing.T) {
	// The PC side reports the tree already gone (job closed) in the window
	// before the runner saw the exit.
	pr, pw := io.Pipe()
	p := &fakeProc{out: pr, waitCh: make(chan struct{}), killErr: ErrAlreadyEnded}
	var l logSink
	r := New(func(Spec) (Proc, error) { return p, nil }, l.log, l.keep, clock)
	_ = r.Start("a", "b", Spec{}, Options{})
	if err := r.Stop(); !errors.Is(err, ErrAlreadyEnded) {
		t.Fatal(err)
	}
	if r.Current().Stopped || !l.has("run.stop_after_end") {
		t.Fatal("must not read as stopped")
	}
	close(p.waitCh)
	pw.Close()
	r.Wait()
}
