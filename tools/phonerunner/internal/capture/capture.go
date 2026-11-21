// Package capture watches Jake's desktop: which window is in front, whether the PC
// is locked, and (when allowed) a screenshot. It runs inside the session part,
// which must live in Jake's desktop session to see his windows, and reports to the
// SYSTEM service as JSON lines over a pipe the service hands it at launch.
//
// Everything the session part reports is labelled by the service as "reported by
// the session process": it runs as Jake, so the service treats it as information,
// never as approval (plan section 6.3).
package capture

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"regexp"
	"strings"
	"sync/atomic"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
)

// Window describes the front window.
type Window struct {
	Title string `json:"title"`
	Exe   string `json:"exe"`
	PID   uint32 `json:"pid"`
}

// Capturer is the platform part. ErrUnsupported is returned off Windows.
type Capturer interface {
	Foreground() (Window, error)
	Locked() (bool, error)
	Screenshot() ([]byte, error) // PNG
}

// TextReader reads the visible text of the front window (Windows UI Automation on
// the PC). It is optional: a nil reader, or ScreenTextEvery 0, means no screen text.
type TextReader interface {
	ScreenText() ([]string, error)
}

// ReadTimeout bounds one screen-text read, so a hung app cannot stall the loop.
var ReadTimeout = 5 * time.Second

// ErrReadTimeout and ErrReadBusy are the timed reader's refusals.
var (
	ErrReadTimeout = errors.New("the front window did not answer in time; skipped")
	ErrReadBusy    = errors.New("the previous read is still waiting on the front window; skipped")
)

type timedReader struct {
	r    TextReader
	d    time.Duration
	busy atomic.Bool
}

// WithTimeout wraps r so each read gives up after d. A read that hangs is left
// to finish on its own; until it does, later reads are skipped (never stacked).
func WithTimeout(r TextReader, d time.Duration) TextReader { return &timedReader{r: r, d: d} }

func (t *timedReader) ScreenText() ([]string, error) {
	if !t.busy.CompareAndSwap(false, true) {
		return nil, ErrReadBusy
	}
	type res struct {
		lines []string
		err   error
	}
	ch := make(chan res, 1)
	go func() {
		defer t.busy.Store(false)
		l, err := t.r.ScreenText()
		ch <- res{l, err}
	}()
	select {
	case r := <-ch:
		return r.lines, r.err
	case <-time.After(t.d):
		return nil, ErrReadTimeout
	}
}

// Screen text limits per frame.
const (
	MaxTextLines   = 200
	MaxTextLineLen = 300
)

// LoopConfig is what Loop needs from the session settings.
type LoopConfig struct {
	Rules           []config.DenyRule
	TextEvery       time.Duration // front window + lock state
	ShotEvery       time.Duration
	ScreenTextEvery time.Duration // 0 = off
	Reader          TextReader
}

// ErrUnsupported means this build cannot see a desktop.
var ErrUnsupported = errors.New("screen capture is only available on Windows")

// Frame is one message from the session part to the service.
type Frame struct {
	Type   string    `json:"type"` // "window", "shot", "text", "error"
	At     time.Time `json:"at"`
	Window Window    `json:"window"`
	Locked bool      `json:"locked"`
	Paused string    `json:"paused,omitempty"` // why no screenshot or text was taken
	Lines  []string  `json:"lines,omitempty"`  // "text" frames: the front window's visible text
	PNG    []byte    `json:"png,omitempty"`
	Error  string    `json:"error,omitempty"`
}

// MaxFrame bounds one frame on the pipe (a 4K PNG is well under this).
const MaxFrame = 32 << 20

// Denied returns the reason a window must not be captured, or "". A pattern that
// does not compile counts as a match (fail closed).
func Denied(w Window, rules []config.DenyRule) string {
	title := strings.ToLower(w.Title)
	exe := strings.ToLower(filepath.Base(strings.ReplaceAll(w.Exe, `\`, "/")))
	for _, r := range rules {
		for _, s := range r.TitleContains {
			if s != "" && strings.Contains(title, strings.ToLower(s)) {
				return r.Reason
			}
		}
		for _, p := range r.TitleRegex {
			re, err := regexp.Compile(p)
			if err != nil || re.MatchString(w.Title) {
				return r.Reason
			}
		}
		for _, e := range r.ExeNames {
			if e != "" && exe == strings.ToLower(e) {
				return r.Reason
			}
		}
	}
	return ""
}

// WithheldPrefix starts the title shown in place of a denied window's title.
const WithheldPrefix = "withheld: "

// Withhold replaces a denied window's title and program name, so neither reaches
// the phone, a status file or the log.
func Withhold(w Window, reason string) Window {
	return Window{Title: WithheldPrefix + reason, Exe: "withheld", PID: w.PID}
}

// Loop runs until ctx ends, writing frames to out. Window state is sent every
// textEvery; a screenshot is attempted every shotEvery and sent only when the PC is
// unlocked, the front window is not denied, and the picture changed.
func Loop(ctx context.Context, c Capturer, lc LoopConfig, out io.Writer, now func() time.Time) error {
	rules := lc.Rules
	enc := json.NewEncoder(out)
	tText := time.NewTicker(lc.TextEvery)
	tShot := time.NewTicker(lc.ShotEvery)
	defer tText.Stop()
	defer tShot.Stop()
	var screenC <-chan time.Time
	reader := lc.Reader
	if lc.ScreenTextEvery > 0 && lc.Reader != nil {
		reader = WithTimeout(lc.Reader, ReadTimeout)
		tScreen := time.NewTicker(lc.ScreenTextEvery)
		defer tScreen.Stop()
		screenC = tScreen.C
	}
	var lastHash [32]byte
	send := func(f Frame) error {
		f.At = now().UTC()
		if err := enc.Encode(f); err != nil {
			return fmt.Errorf("capture: pipe write failed: %w", err)
		}
		return nil
	}
	state := func() (Window, bool, string) {
		w, err := c.Foreground()
		if err != nil {
			return Window{}, false, err.Error()
		}
		locked, err := c.Locked()
		if err != nil {
			return w, false, err.Error()
		}
		return w, locked, ""
	}
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-tText.C:
			w, locked, problem := state()
			if reason := Denied(w, rules); reason != "" {
				w = Withhold(w, reason)
			}
			f := Frame{Type: "window", Window: w, Locked: locked}
			if problem != "" {
				f = Frame{Type: "error", Error: problem}
			}
			if err := send(f); err != nil {
				return err
			}
		case <-screenC:
			if err := send(screenText(c, reader, rules, state)); err != nil {
				return err
			}
		case <-tShot.C:
			w, locked, problem := state()
			reason := Denied(w, rules)
			if reason != "" {
				w = Withhold(w, reason)
			}
			f := Frame{Type: "shot", Window: w, Locked: locked}
			switch {
			case problem != "":
				f = Frame{Type: "error", Error: problem}
			case locked:
				f.Paused = "the PC is locked"
			case reason != "":
				f.Paused = "paused: " + reason
			default:
				png, err := c.Screenshot()
				if err != nil {
					f = Frame{Type: "error", Error: err.Error()}
					break
				}
				// Re-read after the picture: a key page may have opened in between.
				w2, locked2, problem2 := state()
				if problem2 != "" || locked2 || w2 != w || Denied(w2, rules) != "" {
					f.Paused = "screen changed during capture; picture discarded"
					if r2 := Denied(w2, rules); r2 != "" {
						f.Window = Withhold(w2, r2)
					}
					break
				}
				h := sha256.Sum256(png)
				if h == lastHash {
					continue // unchanged screen: nothing new to copy
				}
				lastHash = h
				f.PNG = png
			}
			if err := send(f); err != nil {
				return err
			}
		}
	}
}

// screenText builds one "text" frame: nothing while locked or while a denied
// window is in front, and nothing if the front window changed during the read.
func screenText(c Capturer, r TextReader, rules []config.DenyRule, state func() (Window, bool, string)) Frame {
	w, locked, problem := state()
	if problem != "" {
		return Frame{Type: "error", Error: problem}
	}
	f := Frame{Type: "text", Window: w, Locked: locked}
	if reason := Denied(w, rules); reason != "" {
		f.Window = Withhold(w, reason)
		f.Paused = "paused: " + reason
		return f
	}
	if locked {
		f.Paused = "the PC is locked"
		return f
	}
	lines, err := r.ScreenText()
	if err != nil {
		return Frame{Type: "error", Error: "screen text: " + err.Error()}
	}
	w2, locked2, problem2 := state()
	if problem2 != "" || locked2 || w2 != w {
		f.Paused = "screen changed during reading; text discarded"
		if r2 := Denied(w2, rules); r2 != "" {
			f.Window = Withhold(w2, r2)
		}
		return f
	}
	f.Lines = ClampLines(lines)
	return f
}

// ClampLines drops empty lines and limits count and length.
func ClampLines(in []string) []string {
	out := []string{}
	for _, l := range in {
		l = strings.TrimSpace(l)
		if l == "" {
			continue
		}
		if r := []rune(l); len(r) > MaxTextLineLen {
			l = string(r[:MaxTextLineLen]) + "…"
		}
		out = append(out, l)
		if len(out) == MaxTextLines {
			break
		}
	}
	return out
}

// Read decodes frames from r and calls fn for each until r ends. A frame larger
// than MaxFrame or malformed JSON ends reading with an error.
func Read(r io.Reader, fn func(Frame)) error {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), MaxFrame)
	for sc.Scan() {
		var f Frame
		dec := json.NewDecoder(bytes.NewReader(sc.Bytes()))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&f); err != nil {
			return fmt.Errorf("capture: bad frame: %w", err)
		}
		fn(f)
	}
	return sc.Err()
}
