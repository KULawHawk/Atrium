package capture

import (
	"bytes"
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
)

type fake struct {
	mu      sync.Mutex
	w       Window
	wErr    error
	locked  bool
	lErr    error
	png     []byte
	sErr    error
}

func (f *fake) Foreground() (Window, error) { f.mu.Lock(); defer f.mu.Unlock(); return f.w, f.wErr }
func (f *fake) Locked() (bool, error)       { f.mu.Lock(); defer f.mu.Unlock(); return f.locked, f.lErr }
func (f *fake) Screenshot() ([]byte, error) { f.mu.Lock(); defer f.mu.Unlock(); return f.png, f.sErr }

type syncBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuf) Write(p []byte) (int, error) { s.mu.Lock(); defer s.mu.Unlock(); return s.b.Write(p) }
func (s *syncBuf) String() string              { s.mu.Lock(); defer s.mu.Unlock(); return s.b.String() }

func run(t *testing.T, f *fake, d time.Duration) []Frame {
	t.Helper()
	var buf syncBuf
	ctx, cancel := context.WithTimeout(context.Background(), d)
	defer cancel()
	if err := Loop(ctx, f, config.DefaultDenyRules(), 5*time.Millisecond, 7*time.Millisecond, &buf, time.Now); err != nil {
		t.Fatal(err)
	}
	var frames []Frame
	if err := Read(strings.NewReader(buf.String()), func(fr Frame) { frames = append(frames, fr) }); err != nil {
		t.Fatal(err)
	}
	return frames
}

func count(frames []Frame, pred func(Frame) bool) int {
	n := 0
	for _, f := range frames {
		if pred(f) {
			n++
		}
	}
	return n
}

func TestDenied(t *testing.T) {
	rules := config.DefaultDenyRules()
	if Denied(Window{Title: "Settings - API Keys - RunPod"}, rules) == "" {
		t.Error("key page not denied")
	}
	if Denied(Window{Exe: `C:\Windows\System32\consent.exe`}, rules) == "" {
		t.Error("UAC not denied")
	}
	if Denied(Window{Title: "Obsidian - Patient mode"}, rules) == "" {
		t.Error("patient window not denied")
	}
	if r := Denied(Window{Title: "RunPod - Sign in", Exe: "chrome.exe"}, rules); r != "" {
		t.Errorf("sign-in page wrongly denied: %s", r)
	}
	if Denied(Window{Title: "x"}, []config.DenyRule{{Reason: "r", TitleContains: []string{""}, ExeNames: []string{""}}}) != "" {
		t.Error("empty matchers must not match")
	}
}

func TestLoopShotsOnlyOnChange(t *testing.T) {
	f := &fake{w: Window{Title: "Notepad", Exe: "notepad.exe", PID: 7}, png: []byte("img1")}
	frames := run(t, f, 60*time.Millisecond)
	if count(frames, func(fr Frame) bool { return fr.Type == "window" && fr.Window.PID == 7 }) == 0 {
		t.Fatal("no window frames")
	}
	if n := count(frames, func(fr Frame) bool { return len(fr.PNG) > 0 }); n != 1 {
		t.Fatalf("expected exactly 1 shot for an unchanged screen, got %d", n)
	}
}

func TestLoopPausesAndErrors(t *testing.T) {
	f := &fake{w: Window{Title: "x"}, locked: true}
	if n := count(run(t, f, 40*time.Millisecond), func(fr Frame) bool { return fr.Paused == "the PC is locked" }); n == 0 {
		t.Fatal("no locked pause")
	}
	f = &fake{w: Window{Title: "Windows Security"}}
	if n := count(run(t, f, 40*time.Millisecond), func(fr Frame) bool { return strings.HasPrefix(fr.Paused, "paused: ") && fr.PNG == nil }); n == 0 {
		t.Fatal("no deny pause")
	}
	for _, f := range []*fake{
		{wErr: errors.New("fg")},
		{lErr: errors.New("lock")},
		{sErr: errors.New("shot")},
	} {
		if n := count(run(t, f, 40*time.Millisecond), func(fr Frame) bool { return fr.Type == "error" && fr.Error != "" }); n == 0 {
			t.Fatalf("no error frame for %+v", f)
		}
	}
}

type failW struct{ after int }

func (w *failW) Write(p []byte) (int, error) {
	if w.after <= 0 {
		return 0, io.ErrClosedPipe
	}
	w.after--
	return len(p), nil
}

func TestLoopPipeClosed(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	// window tick fails first
	if err := Loop(ctx, &fake{}, nil, time.Millisecond, time.Hour, &failW{}, time.Now); err == nil {
		t.Fatal("window write error not reported")
	}
	// shot tick fails first
	if err := Loop(ctx, &fake{png: []byte("p")}, nil, time.Hour, time.Millisecond, &failW{}, time.Now); err == nil {
		t.Fatal("shot write error not reported")
	}
}

func TestReadErrors(t *testing.T) {
	if err := Read(strings.NewReader("{bad\n"), func(Frame) {}); err == nil {
		t.Fatal("bad json accepted")
	}
	if err := Read(strings.NewReader(`{"type":"window","extra":1}`+"\n"), func(Frame) {}); err == nil {
		t.Fatal("unknown field accepted")
	}
	big := strings.Repeat("x", MaxFrame+10)
	if err := Read(strings.NewReader(big), func(Frame) {}); err == nil {
		t.Fatal("oversize frame accepted")
	}
}

func TestUnsupported(t *testing.T) {
	c := New()
	if _, err := c.Foreground(); !errors.Is(err, ErrUnsupported) {
		t.Fatal(err)
	}
	if _, err := c.Locked(); !errors.Is(err, ErrUnsupported) {
		t.Fatal(err)
	}
	if _, err := c.Screenshot(); !errors.Is(err, ErrUnsupported) {
		t.Fatal(err)
	}
}

func TestInitDPIOther(t *testing.T) {
	if err := InitDPI(); err != nil {
		t.Fatal(err)
	}
}
