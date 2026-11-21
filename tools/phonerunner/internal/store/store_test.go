package store

import (
	"bufio"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func open(t *testing.T) *Store {
	t.Helper()
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s.SetClock(func() time.Time { return time.Date(2026, 11, 21, 3, 0, 0, 0, time.UTC) })
	return s
}

func TestAppendRedactsAndSequences(t *testing.T) {
	s := open(t)
	if err := s.Append("a", map[string]any{"msg": "token=abc", "n": 3}); err != nil {
		t.Fatal(err)
	}
	s.Logger()("b", nil)
	f, _ := os.Open(s.LogPath())
	defer f.Close()
	sc := bufio.NewScanner(f)
	var lines []map[string]any
	for sc.Scan() {
		var m map[string]any
		if err := json.Unmarshal(sc.Bytes(), &m); err != nil {
			t.Fatal(err)
		}
		lines = append(lines, m)
	}
	if len(lines) != 2 || lines[0]["seq"].(float64) != 1 || lines[1]["seq"].(float64) != 2 {
		t.Fatalf("%v", lines)
	}
	if strings.Contains(lines[0]["msg"].(string), "abc") {
		t.Fatal("not redacted")
	}
	if s.Root() == "" {
		t.Fatal("no root")
	}
}

func TestAppendErrors(t *testing.T) {
	s := open(t)
	if err := s.Append("x", map[string]any{"bad": make(chan int)}); err == nil {
		t.Fatal("unmarshalable accepted")
	}
	os.RemoveAll(filepath.Join(s.root, "log"))
	os.WriteFile(filepath.Join(s.root, "log"), []byte("file"), 0o644) // log is now a file
	if err := s.Append("x", nil); err == nil {
		t.Fatal("open error not reported")
	}
}

func TestOpenError(t *testing.T) {
	f := filepath.Join(t.TempDir(), "file")
	os.WriteFile(f, nil, 0o644)
	if _, err := Open(f); err == nil {
		t.Fatal("open under a file accepted")
	}
}

func TestWriteJSON(t *testing.T) {
	s := open(t)
	if err := s.WriteJSON("status.json", map[string]int{"a": 1}); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(s.root, "status.json")); !strings.Contains(string(b), `"a": 1`) {
		t.Fatal(string(b))
	}
	if err := s.WriteJSON("status.json", make(chan int)); err == nil {
		t.Fatal("bad value accepted")
	}
	if err := s.WriteJSON("nope/x.json", 1); err == nil {
		t.Fatal("missing dir accepted")
	}
	os.MkdirAll(filepath.Join(s.root, "dir.json"), 0o755)
	os.WriteFile(filepath.Join(s.root, "dir.json", "f"), nil, 0o644)
	if err := s.WriteJSON("dir.json", 1); err == nil {
		t.Fatal("rename over non-empty dir accepted")
	}
}

func TestSaveShot(t *testing.T) {
	s := open(t)
	at := s.now()
	p, err := s.SaveShot([]byte("png"), ShotMeta{At: at, Window: "ghp_abcdefghijklmnopqrstuvwxyz0123", HoldReason: "picture filter not built"})
	if err != nil {
		t.Fatal(err)
	}
	side, _ := os.ReadFile(strings.TrimSuffix(p, ".png") + ".json")
	if strings.Contains(string(side), "ghp_") || !strings.Contains(string(side), `"may_copy": false`) {
		t.Fatal(string(side))
	}
	if _, err := s.SaveShot(nil, ShotMeta{At: at}); err == nil {
		t.Fatal("held shot without reason accepted")
	}
	// captures/<date> is a file -> mkdir fails
	os.RemoveAll(filepath.Join(s.root, "captures"))
	os.WriteFile(filepath.Join(s.root, "captures"), nil, 0o644)
	if _, err := s.SaveShot(nil, ShotMeta{At: at, MayCopy: true}); err == nil {
		t.Fatal("mkdir error not reported")
	}
}

func TestSaveShotWriteErrors(t *testing.T) {
	s := open(t)
	at := s.now()
	day := filepath.Join(s.root, "captures", "2026-11-21")
	base := filepath.Join(day, at.Format("150405.000000000"))
	os.MkdirAll(base+".png.tmp", 0o755) // png tmp is a dir
	if _, err := s.SaveShot(nil, ShotMeta{At: at, MayCopy: true}); err == nil {
		t.Fatal("png write error not reported")
	}
	os.RemoveAll(base + ".png.tmp")
	os.MkdirAll(base+".json.tmp", 0o755)
	if _, err := s.SaveShot(nil, ShotMeta{At: at, MayCopy: true}); err == nil {
		t.Fatal("sidecar write error not reported")
	}
}

func TestReadAck(t *testing.T) {
	s := open(t)
	if st := s.ReadAck(5 * time.Minute); st.Present || !strings.Contains(st.Problem, "no copy") {
		t.Fatalf("%+v", st)
	}
	ack := filepath.Join(s.root, "ack", "copy_ack.json")
	os.WriteFile(ack, []byte("{"), 0o644)
	if st := s.ReadAck(time.Minute); !strings.Contains(st.Problem, "unreadable") {
		t.Fatalf("%+v", st)
	}
	s.Append("e", nil)
	fi, _ := os.Stat(s.LogPath())
	write := func(age time.Duration, copied int64) {
		b, _ := json.Marshal(Ack{At: s.now().Add(-age), CopiedBytes: copied, Copier: "pc lane"})
		os.WriteFile(ack, b, 0o644)
	}
	write(time.Minute, fi.Size())
	if st := s.ReadAck(5 * time.Minute); !st.Fresh || st.Problem != "" || st.Copier != "pc lane" {
		t.Fatalf("%+v", st)
	}
	write(time.Minute, 0)
	if st := s.ReadAck(5 * time.Minute); !strings.Contains(st.Problem, "not yet copied") {
		t.Fatalf("%+v", st)
	}
	write(10*time.Minute, fi.Size())
	if st := s.ReadAck(5 * time.Minute); st.Fresh || !strings.Contains(st.Problem, "seconds ago") {
		t.Fatalf("%+v", st)
	}
}

type failWrite struct{}

func (failWrite) Write([]byte) (int, error) { return 0, errors.New("disk full") }
func (failWrite) Sync() error               { return nil }
func (failWrite) Close() error              { return nil }

func TestAppendWriteError(t *testing.T) {
	s := open(t)
	old := openAppend
	defer func() { openAppend = old }()
	openAppend = func(string) (appendFile, error) { return failWrite{}, nil }
	if err := s.Append("x", nil); err == nil || !strings.Contains(err.Error(), "disk full") {
		t.Fatalf("got %v", err)
	}
}
