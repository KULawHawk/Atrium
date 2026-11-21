package service

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/alert"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/capture"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

type rec struct {
	kinds []alert.Kind
	err   error
}

func (r *rec) Send(_ context.Context, k alert.Kind) (alert.Result, error) {
	r.kinds = append(r.kinds, k)
	return alert.Sent, r.err
}

func setup(t *testing.T) (*Service, *store.Store, *rec, *time.Time) {
	t.Helper()
	st, err := store.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	logPath := filepath.Join(t.TempDir(), "pod.log")
	os.WriteFile(logPath, []byte("PROGRESS 3/92\nkey sk-ant-abcdefghijklmnop\n"), 0o644)
	cfg := config.Defaults()
	cfg.WatchedLogs = []config.WatchedLog{{Label: "pod", Path: logPath, Lines: 5}, {Label: "missing", Path: logPath + ".none", Lines: 5}}
	clock := time.Date(2026, 11, 21, 3, 0, 0, 0, time.UTC)
	r := &rec{}
	st.SetClock(func() time.Time { return clock })
	return New(cfg, st, r, func() time.Time { return clock }), st, r, &clock
}

func logText(t *testing.T, st *store.Store) string {
	b, _ := os.ReadFile(st.LogPath())
	return string(b)
}

func TestIngestAndRefresh(t *testing.T) {
	s, st, r, clock := setup(t)
	ctx := context.Background()
	s.Started(ctx)

	s.Ingest(ctx, capture.Frame{Type: "window", At: *clock, Window: capture.Window{Title: "pod ghp_abcdefghijklmnopqrstuvwxyz0123", PID: 4}})
	s.Ingest(ctx, capture.Frame{Type: "shot", At: *clock, Window: capture.Window{Title: "Notepad"}, PNG: []byte("png")})
	s.Ingest(ctx, capture.Frame{Type: "shot", At: *clock, Paused: "paused: key or token page"})
	s.Ingest(ctx, capture.Frame{Type: "window", At: *clock, Locked: true})
	s.Ingest(ctx, capture.Frame{Type: "window", At: *clock, Locked: true})
	s.Ingest(ctx, capture.Frame{Type: "window", At: *clock, Locked: false})
	s.Ingest(ctx, capture.Frame{Type: "error", At: *clock, Error: "boom token=abc"})

	stat := s.Refresh(ctx)
	if !stat.Session.Connected || stat.Session.ShotPaused != "paused: key or token page" || !strings.Contains(stat.Session.LastError, "boom") {
		t.Fatalf("%+v", stat.Session)
	}
	if strings.Contains(stat.Session.LastError, "abc") {
		t.Fatal("error not redacted")
	}
	if string(s.LatestShot()) != "png" {
		t.Fatal("latest shot missing")
	}
	if len(stat.Logs) != 2 || stat.Logs[0].Lines[0] != "PROGRESS 3/92" || strings.Contains(stat.Logs[0].Lines[1], "sk-ant") || stat.Logs[1].Error == "" {
		t.Fatalf("%+v", stat.Logs)
	}
	if stat.Paired || len(stat.Problems) < 2 {
		t.Fatalf("problems %v", stat.Problems)
	}
	want := []alert.Kind{alert.Started, alert.Locked, alert.CopyLag}
	if len(r.kinds) != 3 || r.kinds[0] != want[0] || r.kinds[1] != want[1] || r.kinds[2] != want[2] {
		t.Fatalf("alerts %v", r.kinds)
	}
	// Copy lag alerts once per transition, not on every refresh.
	s.Refresh(ctx)
	if len(r.kinds) != 3 {
		t.Fatalf("repeat lag alert %v", r.kinds)
	}
	lt := logText(t, st)
	for _, e := range []string{"service.started", "pc.locked", "pc.unlocked", "session.error", "copy.lag", `"kind"`} {
		if !strings.Contains(lt, e) {
			t.Errorf("log missing %s", e)
		}
	}
	if strings.Contains(lt, "ghp_") {
		t.Fatal("key in log")
	}
	var side store.ShotMeta
	matches, _ := filepath.Glob(filepath.Join(st.Root(), "captures", "*", "*.json"))
	b, _ := os.ReadFile(matches[0])
	json.Unmarshal(b, &side)
	if side.MayCopy || side.HoldReason != PictureHold {
		t.Fatalf("shot sidecar %+v", side)
	}
	for _, f := range []string{"status.json", "heartbeat.json"} {
		if _, err := os.Stat(filepath.Join(st.Root(), f)); err != nil {
			t.Fatal(err)
		}
	}

	// Session goes quiet -> not connected.
	*clock = clock.Add(time.Minute)
	if s.Refresh(ctx).Session.Connected {
		t.Fatal("stale session shown connected")
	}
}

func TestCopyLagClears(t *testing.T) {
	s, st, r, clock := setup(t)
	ctx := context.Background()
	s.Refresh(ctx) // lag
	fi, _ := os.Stat(st.LogPath())
	b, _ := json.Marshal(store.Ack{At: *clock, CopiedBytes: fi.Size() + 1000})
	os.WriteFile(filepath.Join(st.Root(), "ack", "copy_ack.json"), b, 0o644)
	s.Refresh(ctx) // fresh
	os.Remove(filepath.Join(st.Root(), "ack", "copy_ack.json"))
	s.Refresh(ctx) // lag again -> second alert
	n := 0
	for _, k := range r.kinds {
		if k == alert.CopyLag {
			n++
		}
	}
	if n != 2 {
		t.Fatalf("expected 2 lag alerts, got %v", r.kinds)
	}
}

func TestWriteFailuresSurface(t *testing.T) {
	s, st, r, clock := setup(t)
	r.err = errors.New("ntfy down")
	ctx := context.Background()
	s.Started(ctx)
	if !strings.Contains(logText(t, st), "ntfy down") {
		t.Fatal("alert error not logged")
	}
	os.MkdirAll(filepath.Join(st.Root(), "status.json.tmp"), 0o755)
	os.MkdirAll(filepath.Join(st.Root(), "heartbeat.json.tmp"), 0o755)
	stat := s.Refresh(ctx)
	joined := strings.Join(stat.Problems, "|")
	if !strings.Contains(joined, "status file") || !strings.Contains(joined, "heartbeat") {
		t.Fatalf("%v", stat.Problems)
	}
	// SaveShot failure is logged, not hidden.
	os.RemoveAll(filepath.Join(st.Root(), "captures"))
	os.WriteFile(filepath.Join(st.Root(), "captures"), nil, 0o644)
	s.Ingest(ctx, capture.Frame{Type: "shot", At: *clock, PNG: []byte("p")})
	if !strings.Contains(logText(t, st), "store.error") {
		t.Fatal("shot save error not logged")
	}
}

