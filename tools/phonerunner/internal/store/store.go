// Package store is PhoneRunner's on-disk record: an append-only event log, the
// current status, screen captures, and the copy-off acknowledgement.
//
// Layout under the store root (C:\ProgramData\PhoneRunner on the PC):
//
//	log\events.jsonl        append-only, one JSON object per line, fsync per line
//	status.json             latest status (atomic replace)
//	heartbeat.json          liveness for the PC-offline alert (atomic replace)
//	session.json            settings for the session part (intervals, window rules; no secret)
//	captures\<date>\*.png   screenshots + .json sidecar; SYSTEM+Administrators only (set at install)
//	ack\copy_ack.json       written by the PC lane after each copy (the only lane-writable folder)
//
// Nothing here ever deletes a file (Jake's rule: nothing deleted without his decision).
// Every string written to the log passes through redact first.
package store

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/redact"
)

// appendFile is the part of *os.File that Append uses (a seam for tests).
type appendFile interface {
	Write([]byte) (int, error)
	Sync() error
	Close() error
}

var openAppend = func(path string) (appendFile, error) {
	return os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
}

// Store is safe for concurrent use.
type Store struct {
	root string
	mu   sync.Mutex
	seq  int64
	now  func() time.Time
}

// Open creates the folder layout if missing.
func Open(root string) (*Store, error) {
	for _, d := range []string{"log", "captures", "ack"} {
		if err := os.MkdirAll(filepath.Join(root, d), 0o755); err != nil {
			return nil, fmt.Errorf("store: %w", err)
		}
	}
	return &Store{root: root, now: time.Now}, nil
}

// SetClock replaces the time source (tests and the service share one clock).
func (s *Store) SetClock(now func() time.Time) { s.now = now }

// Root returns the store folder.
func (s *Store) Root() string { return s.root }

// LogPath is the event log file.
func (s *Store) LogPath() string { return filepath.Join(s.root, "log", "events.jsonl") }

// Append writes one event line and syncs it to disk before returning, so a crash
// never loses a line that was reported as written (Hard Rule 8).
func (s *Store) Append(event string, fields map[string]any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq++
	rec := map[string]any{"seq": s.seq, "at": s.now().UTC().Format(time.RFC3339Nano), "event": event}
	for k, v := range fields {
		if str, ok := v.(string); ok {
			v = redact.Text(str).Text
		}
		rec[k] = v
	}
	line, err := json.Marshal(rec)
	if err != nil {
		return fmt.Errorf("store: %w", err)
	}
	f, err := openAppend(s.LogPath())
	if err != nil {
		return fmt.Errorf("store: %w", err)
	}
	defer f.Close()
	if _, err := f.Write(append(line, '\n')); err != nil {
		return fmt.Errorf("store: %w", err)
	}
	return f.Sync()
}

// Logger adapts Append to the gate's logger shape; write errors are swallowed
// here only because the caller (the service) also surfaces store health.
func (s *Store) Logger() func(string, map[string]any) {
	return func(e string, f map[string]any) { _ = s.Append(e, f) }
}

// WriteJSON atomically replaces name (relative to the root) with v as JSON.
func (s *Store) WriteJSON(name string, v any) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Errorf("store: %w", err)
	}
	return s.writeAtomic(filepath.Join(s.root, name), data)
}

func (s *Store) writeAtomic(path string, data []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return fmt.Errorf("store: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return fmt.Errorf("store: %w", err)
	}
	return nil
}

// ShotMeta is the sidecar written next to every screenshot.
type ShotMeta struct {
	At         time.Time `json:"at"`
	Window     string    `json:"window"`
	MayCopy    bool      `json:"may_copy"`
	HoldReason string    `json:"hold_reason,omitempty"`
}

// SaveShot writes a PNG and its sidecar; it returns the PNG path.
func (s *Store) SaveShot(png []byte, meta ShotMeta) (string, error) {
	if !meta.MayCopy && meta.HoldReason == "" {
		return "", errors.New("store: a held screenshot needs a reason")
	}
	meta.Window = redact.Text(meta.Window).Text
	day := filepath.Join(s.root, "captures", meta.At.UTC().Format("2006-01-02"))
	if err := os.MkdirAll(day, 0o755); err != nil {
		return "", fmt.Errorf("store: %w", err)
	}
	base := filepath.Join(day, meta.At.UTC().Format("150405.000000000"))
	if err := s.writeAtomic(base+".png", png); err != nil {
		return "", err
	}
	side, _ := json.MarshalIndent(meta, "", "  ")
	if err := s.writeAtomic(base+".json", side); err != nil {
		return "", err
	}
	return base + ".png", nil
}

// Ack is what the PC lane writes after copying new bytes off the PC.
type Ack struct {
	At          time.Time `json:"at"`
	CopiedBytes int64     `json:"copied_bytes"`
	Copier      string    `json:"copier"`
}

// AckState summarises copy-off health for the page and for the long-item gate.
type AckState struct {
	Present     bool    `json:"present"`
	Fresh       bool    `json:"fresh"`
	AgeSeconds  float64 `json:"age_seconds"`
	CopiedBytes int64   `json:"copied_bytes"`
	LogBytes    int64   `json:"log_bytes"`
	Copier      string  `json:"copier,omitempty"`
	Problem     string  `json:"problem,omitempty"`
}

// ReadAck reports whether results are being copied off the PC. The ack is a claim
// by the copier (it lives in the one lane-writable folder), and is labelled so.
func (s *Store) ReadAck(maxAge time.Duration) AckState {
	st := AckState{}
	if fi, err := os.Stat(s.LogPath()); err == nil {
		st.LogBytes = fi.Size()
	}
	data, err := os.ReadFile(filepath.Join(s.root, "ack", "copy_ack.json"))
	if err != nil {
		st.Problem = "no copy acknowledgement yet: results are not confirmed copied off the PC"
		return st
	}
	var a Ack
	if err := json.Unmarshal(data, &a); err != nil {
		st.Problem = "copy acknowledgement is unreadable"
		return st
	}
	st.Present = true
	st.AgeSeconds = s.now().Sub(a.At).Seconds()
	st.CopiedBytes = a.CopiedBytes
	st.Copier = redact.Text(a.Copier).Text
	st.Fresh = st.AgeSeconds >= 0 && st.AgeSeconds <= maxAge.Seconds()
	switch {
	case !st.Fresh:
		st.Problem = fmt.Sprintf("last copy off the PC was %.0f seconds ago", st.AgeSeconds)
	case a.CopiedBytes < st.LogBytes:
		st.Problem = fmt.Sprintf("%d log bytes not yet copied", st.LogBytes-a.CopiedBytes)
	}
	return st
}
