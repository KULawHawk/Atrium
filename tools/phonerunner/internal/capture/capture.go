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

// ErrUnsupported means this build cannot see a desktop.
var ErrUnsupported = errors.New("screen capture is only available on Windows")

// Frame is one message from the session part to the service.
type Frame struct {
	Type   string    `json:"type"` // "window", "shot", "error"
	At     time.Time `json:"at"`
	Window Window    `json:"window"`
	Locked bool      `json:"locked"`
	Paused string    `json:"paused,omitempty"` // why no screenshot was taken
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
func Loop(ctx context.Context, c Capturer, rules []config.DenyRule, textEvery, shotEvery time.Duration, out io.Writer, now func() time.Time) error {
	enc := json.NewEncoder(out)
	tText := time.NewTicker(textEvery)
	tShot := time.NewTicker(shotEvery)
	defer tText.Stop()
	defer tShot.Stop()
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
