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
	"image"
	"image/png"
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

// VisibleWindow is one shown top-level window. Rect is in physical pixels, in the
// same coordinates as ScreenImage's origin (the virtual screen across all monitors).
// Hidden marks a window that is shown but not drawn on screen (minimized, or hidden
// by Windows on another desktop): it has no area to black out, but the taskbar,
// Alt-Tab and Task View can still show a live preview of it.
type VisibleWindow struct {
	Window
	Handle uintptr         `json:"-"`
	Rect   image.Rectangle `json:"-"`
	Class  string          `json:"-"` // window class name
	Hidden bool            `json:"-"`
	// Sure is false when the window's bounds or the display scaling cannot be known
	// for certain; any such window that needs blacking out pauses the whole picture.
	Sure bool `json:"-"`
}

// Layout is the monitor arrangement: the virtual-screen rectangle and how many
// monitors make it up. A picture is kept only if it did not change during capture.
type Layout struct {
	Rect     image.Rectangle
	Monitors int
}

// ScreenLayout reports the current monitor arrangement.
type ScreenLayout interface {
	Layout() (Layout, error)
}

// previewClasses are the Windows shell windows that draw live previews of other
// windows: taskbar hover thumbnails, Alt-Tab, Task View, Snap Assist and Peek. No deny
// rule can match them by title, so while one is up and a patient window exists
// (minimized included), the whole picture pauses.
var previewClasses = []string{
	"TaskListThumbnailWnd",         // taskbar hover thumbnail
	"MultitaskingViewFrame",        // Alt-Tab and Task View (Windows 10)
	"XamlExplorerHostIslandWindow", // Alt-Tab, Task View, Snap Assist (Windows 11)
	"TaskSwitcherWnd",              // classic Alt-Tab
	"TaskSwitcherOverlayWnd",       // classic Alt-Tab
	"ForegroundStaging",            // switcher staging window
	"LivePreview",                  // Peek
	"Flip3D",                       // older switcher
}

func isPreview(class string) bool {
	for _, c := range previewClasses {
		if strings.EqualFold(class, c) {
			return true
		}
	}
	return false
}

// WindowLister lists the windows on screen, front first (Windows on the PC).
type WindowLister interface {
	VisibleWindows() ([]VisibleWindow, error)
}

// ImageShooter returns the whole screen as an image plus the virtual-screen
// coordinates of its top-left pixel (negative when a monitor sits left of or above
// the main one).
type ImageShooter interface {
	ScreenImage() (*image.RGBA, image.Point, error)
}

// MaskMargin widens each blacked-out window on every side, so a shadow, a resize
// border or a one-pixel rounding never shows its edge.
const MaskMargin = 16

// MaskPlan decides what to black out in a picture: every visible window that a deny
// rule matches, plus every other visible window of the same program (its dialogs and
// pop-ups). It returns the rectangles and how many windows they cover, or a reason
// to pause the whole picture instead (a window to black out whose position is not
// certain).
func MaskPlan(ws []VisibleWindow, rules []config.DenyRule) (rects []image.Rectangle, n int, pause string) {
	pids := map[uint32]string{}
	anyDenied := ""
	for _, w := range ws {
		if r := Denied(w.Window, rules); r != "" {
			anyDenied = r
			if w.PID != 0 {
				pids[w.PID] = r
			}
		}
	}
	if anyDenied != "" {
		for _, w := range ws {
			if !w.Hidden && isPreview(w.Class) {
				return nil, 0, "paused: " + anyDenied + " open, and a window preview (task switcher or taskbar preview) is on screen"
			}
		}
	}
	for _, w := range ws {
		if w.Hidden {
			continue
		}
		reason := Denied(w.Window, rules)
		if reason == "" && w.PID != 0 {
			reason = pids[w.PID]
		}
		if reason == "" {
			continue
		}
		if !w.Sure || w.Rect.Empty() {
			return nil, 0, "paused: " + reason + " on screen, and its position is not certain"
		}
		rects = append(rects, w.Rect.Inset(-MaskMargin))
		n++
	}
	return rects, n, ""
}

// BlackOut paints each rectangle (virtual-screen coordinates) black in img, whose
// top-left pixel is at origin, then checks every painted pixel really is black.
func BlackOut(img *image.RGBA, origin image.Point, rects []image.Rectangle) error {
	for _, r := range rects {
		rr := r.Sub(origin).Add(img.Rect.Min).Intersect(img.Rect)
		for y := rr.Min.Y; y < rr.Max.Y; y++ {
			i := img.PixOffset(rr.Min.X, y)
			for x := rr.Min.X; x < rr.Max.X; x++ {
				img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3] = 0, 0, 0, 0xff
				i += 4
			}
		}
	}
	for _, r := range rects {
		rr := r.Sub(origin).Add(img.Rect.Min).Intersect(img.Rect)
		for y := rr.Min.Y; y < rr.Max.Y; y++ {
			for x := rr.Min.X; x < rr.Max.X; x++ {
				if c := img.RGBAAt(x, y); c.R != 0 || c.G != 0 || c.B != 0 {
					return fmt.Errorf("capture: pixel %d,%d not blacked out", x, y)
				}
			}
		}
	}
	return nil
}

// sameWindows is true when two listings show the same windows in the same places.
func sameWindows(a, b []VisibleWindow) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i].Handle != b[i].Handle || a[i].Rect != b[i].Rect || a[i].Window != b[i].Window || a[i].Sure != b[i].Sure || a[i].Hidden != b[i].Hidden || a[i].Class != b[i].Class {
			return false
		}
	}
	return true
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
	Masked int       `json:"masked,omitempty"` // "shot" frames: windows blacked out in the picture
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
			case isMasking(c):
				pic, masked, why, err := maskedShot(c, rules, w, state)
				switch {
				case err != nil:
					f = Frame{Type: "error", Error: err.Error()}
				case why != "":
					f.Paused = why
				default:
					h := sha256.Sum256(pic)
					if h == lastHash {
						continue
					}
					lastHash = h
					f.PNG, f.Masked = pic, masked
				}
			default:
				// Fail closed: a capturer that cannot list windows, report the monitor
				// layout and return a raw image cannot black out patient windows.
				f.Paused = "paused: this build cannot black out patient windows; no picture"
			}
			if err := send(f); err != nil {
				return err
			}
		}
	}
}

func isMasking(c Capturer) bool {
	_, l := c.(WindowLister)
	_, i := c.(ImageShooter)
	_, m := c.(ScreenLayout)
	return l && i && m
}

// maskedShot takes a picture with every patient (denied) window blacked out. It lists
// the windows, takes the picture, lists them again, and gives up (why != "") if
// anything moved, the front window changed, a window to black out has an uncertain
// position, or the blackout check fails. Fails closed: no picture rather than a doubtful one.
func maskedShot(c Capturer, rules []config.DenyRule, front Window, state func() (Window, bool, string)) (pic []byte, masked int, why string, err error) {
	l, sh, ly := c.(WindowLister), c.(ImageShooter), c.(ScreenLayout)
	lay1, err := ly.Layout()
	if err != nil {
		return nil, 0, "paused: cannot read the monitor layout (" + err.Error() + ")", nil
	}
	ws1, err := l.VisibleWindows()
	if err != nil {
		return nil, 0, "paused: cannot list the windows on screen (" + err.Error() + ")", nil
	}
	rects, n, pause := MaskPlan(ws1, rules)
	if pause != "" {
		return nil, 0, pause, nil
	}
	img, origin, err := sh.ScreenImage()
	if err != nil {
		return nil, 0, "", err
	}
	w2, locked2, problem2 := state()
	ws2, err2 := l.VisibleWindows()
	lay2, err3 := ly.Layout()
	shot := image.Rectangle{Min: origin, Max: origin.Add(img.Rect.Size())}
	if problem2 != "" || locked2 || w2 != front || Denied(w2, rules) != "" || err2 != nil || !sameWindows(ws1, ws2) ||
		err3 != nil || lay2 != lay1 || shot != lay1.Rect {
		return nil, 0, "screen changed during capture; picture discarded", nil
	}
	if err := BlackOut(img, origin, rects); err != nil {
		return nil, 0, "paused: blackout check failed; picture discarded", nil
	}
	var out bytes.Buffer
	if err := (&png.Encoder{CompressionLevel: png.BestSpeed}).Encode(&out, img); err != nil {
		return nil, 0, "", err
	}
	return out.Bytes(), n, "", nil
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
