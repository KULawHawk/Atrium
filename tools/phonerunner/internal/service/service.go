// Package service is the platform-independent heart of the SYSTEM service: it takes
// frames from the session part, keeps the current status, writes status and
// heartbeat files for the PC lane to copy, and decides when to alert.
//
// Watch-only (Decision 260 = A): nothing here can start, stop or change anything on
// the PC. The Run button comes in a later PR, behind the passkey check.
package service

import (
	"context"
	"sync"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/alert"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/capture"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/redact"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/tail"
)

// Version is stamped into every status and heartbeat.
var Version = "0.1.0-watch"

// PictureHold is why screenshots are not copied off the PC yet: the picture filter
// (key blackout by reading the words in a picture) is built last, after Jake answers
// Decision 4b. Until then pictures stay on the PC and the phone only.
const PictureHold = "not copied: picture filter not built yet (Decision 4b pending)"

// LogTail is one watched file on the page.
type LogTail struct {
	Label string   `json:"label"`
	Lines []string `json:"lines"`
	Error string   `json:"error,omitempty"`
}

// Session summarises what the session part last reported.
type Session struct {
	Connected  bool           `json:"connected"`
	LastFrame  time.Time      `json:"last_frame"`
	Window     capture.Window `json:"window"`
	Locked     bool           `json:"locked"`
	ShotPaused string         `json:"shot_paused,omitempty"`
	LastShotAt time.Time      `json:"last_shot_at"`
	LastError  string         `json:"last_error,omitempty"`
	Note       string         `json:"note"`
}

// Status is everything the phone page shows.
type Status struct {
	At       time.Time      `json:"at"`
	Version  string         `json:"version"`
	Mode     string         `json:"mode"`
	Paired   bool           `json:"paired"`
	Session  Session        `json:"session"`
	Logs     []LogTail      `json:"logs"`
	CopyOff  store.AckState `json:"copy_off"`
	Problems []string       `json:"problems"`
}

// Sender is the alert side (alert.Notifier satisfies it).
type Sender interface {
	Send(ctx context.Context, k alert.Kind) (alert.Result, error)
}

// Service holds live state.
type Service struct {
	cfg   config.Config
	st    *store.Store
	alert Sender
	now   func() time.Time

	mu        sync.Mutex
	sess      Session
	shot      []byte
	wasLocked bool
	copyLag   bool
}

// New builds a Service.
func New(cfg config.Config, st *store.Store, a Sender, now func() time.Time) *Service {
	return &Service{cfg: cfg, st: st, alert: a, now: now,
		sess: Session{Note: "reported by the session process (runs as Jake; information only, never approval)"}}
}

// Ingest applies one frame from the session part.
func (s *Service) Ingest(ctx context.Context, f capture.Frame) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sess.LastFrame = f.At
	if f.Type == "error" {
		s.sess.LastError = redact.Text(f.Error).Text
		s.log("session.error", map[string]any{"error": f.Error})
		return
	}
	s.sess.LastError = ""
	f.Window.Title = redact.Text(f.Window.Title).Text
	s.sess.Window = f.Window
	s.sess.Locked = f.Locked
	if f.Locked && !s.wasLocked {
		s.log("pc.locked", nil)
		s.send(ctx, alert.Locked)
	}
	if !f.Locked && s.wasLocked {
		s.log("pc.unlocked", nil)
	}
	s.wasLocked = f.Locked
	if f.Type != "shot" {
		return
	}
	s.sess.ShotPaused = f.Paused
	if len(f.PNG) == 0 {
		return
	}
	s.shot = f.PNG
	s.sess.LastShotAt = f.At
	if _, err := s.st.SaveShot(f.PNG, store.ShotMeta{At: f.At, Window: f.Window.Title, MayCopy: false, HoldReason: PictureHold}); err != nil {
		s.log("store.error", map[string]any{"error": err.Error()})
	}
}

// LatestShot returns the newest screenshot for the phone (nil if none).
func (s *Service) LatestShot() []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.shot
}

// Refresh rebuilds the status, writes status.json and heartbeat.json, and alerts on
// copy-off lag. It returns the status it wrote.
func (s *Service) Refresh(ctx context.Context) Status {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now().UTC()
	st := Status{At: now, Version: Version, Mode: "watch-only", Paired: s.cfg.Paired(), Problems: []string{}}
	stale := time.Duration(3*s.cfg.CaptureTextSeconds) * time.Second
	s.sess.Connected = !s.sess.LastFrame.IsZero() && now.Sub(s.sess.LastFrame) <= stale
	st.Session = s.sess
	if !st.Session.Connected {
		st.Problems = append(st.Problems, "the desktop watcher is not reporting (PC signed out, starting up, or stopped)")
	}
	if !st.Paired {
		st.Problems = append(st.Problems, "no phone is paired yet")
	}
	for _, w := range s.cfg.WatchedLogs {
		lt := LogTail{Label: w.Label}
		lines, err := tail.Lines(w.Path, w.Lines)
		if err != nil {
			lt.Error = redact.Text(err.Error()).Text
		} else {
			lt.Lines = lines
		}
		st.Logs = append(st.Logs, lt)
	}
	st.CopyOff = s.st.ReadAck(time.Duration(s.cfg.CopyAckMaxAgeSeconds) * time.Second)
	if st.CopyOff.Problem != "" {
		st.Problems = append(st.Problems, st.CopyOff.Problem)
	}
	lag := !st.CopyOff.Fresh
	if lag && !s.copyLag {
		s.log("copy.lag", map[string]any{"problem": st.CopyOff.Problem})
		s.send(ctx, alert.CopyLag)
	}
	s.copyLag = lag
	if err := s.st.WriteJSON("status.json", st); err != nil {
		st.Problems = append(st.Problems, "could not write status file: "+err.Error())
	}
	hb := map[string]any{"at": now, "version": Version, "session_connected": st.Session.Connected, "locked": st.Session.Locked}
	if err := s.st.WriteJSON("heartbeat.json", hb); err != nil {
		st.Problems = append(st.Problems, "could not write heartbeat: "+err.Error())
	}
	return st
}

// Started logs the start and sends the start alert.
func (s *Service) Started(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.log("service.started", map[string]any{"version": Version, "paired": s.cfg.Paired()})
	s.send(ctx, alert.Started)
}

func (s *Service) log(event string, fields map[string]any) {
	_ = s.st.Append(event, fields)
}

func (s *Service) send(ctx context.Context, k alert.Kind) {
	r, err := s.alert.Send(ctx, k)
	fields := map[string]any{"kind": string(k), "result": string(r)}
	if err != nil {
		fields["error"] = err.Error()
	}
	s.log("alert", fields)
}
