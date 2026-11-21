package copyoff

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

var t0 = time.Date(2026, 11, 21, 3, 0, 0, 0, time.UTC)

func setup(t *testing.T) (*Copier, *store.Store) {
	t.Helper()
	root := t.TempDir()
	st, err := store.Open(filepath.Join(root, "store"))
	if err != nil {
		t.Fatal(err)
	}
	st.SetClock(func() time.Time { return t0 })
	return &Copier{Store: st.Root(), Outbox: filepath.Join(root, "outbox"), Now: func() time.Time { return t0 }}, st
}

func readAck(t *testing.T, c *Copier) store.Ack {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(c.Store, "ack", "copy_ack.json"))
	if err != nil {
		t.Fatal(err)
	}
	var a store.Ack
	if err := json.Unmarshal(data, &a); err != nil {
		t.Fatal(err)
	}
	return a
}

func TestFullCycle(t *testing.T) {
	c, st := setup(t)
	_ = st.Append("service.started", map[string]any{"version": "x"})
	_ = st.Append("note", map[string]any{"n": 1})
	_ = st.WriteJSON("status.json", map[string]any{"mode": "watch-only"})
	_ = st.WriteJSON("heartbeat.json", map[string]any{"ok": true})
	if _, err := st.SaveShot([]byte("png-ok"), store.ShotMeta{At: t0, Window: "w", MayCopy: true}); err != nil {
		t.Fatal(err)
	}

	r, err := c.Stage()
	if err != nil {
		t.Fatal(err)
	}
	if r.Reused || r.Manifest.Batch != 1 || r.Manifest.LogFrom != 0 || r.Manifest.LogTo == 0 {
		t.Fatalf("bad manifest %+v", r.Manifest)
	}
	if len(r.Manifest.Files) != 3 {
		t.Fatalf("files %+v", r.Manifest)
	}
	for _, f := range r.Manifest.Files {
		if strings.HasSuffix(f.Name, ".png") {
			t.Fatal("a picture was copied")
		}
	}
	if filepath.Base(r.Dir) != "batch_000001" {
		t.Fatal(r.Dir)
	}

	// Staging again before the ack returns the same batch.
	r2, err := c.Stage()
	if err != nil || !r2.Reused || r2.ManifestSHA != r.ManifestSHA {
		t.Fatalf("reuse: %v %+v", err, r2)
	}

	// Wrong sha refused.
	if _, err := c.Ack("deadbeef"); err == nil {
		t.Fatal("wrong sha accepted")
	}
	a, err := c.Ack(r.ManifestSHA)
	if err != nil {
		t.Fatal(err)
	}
	if a.Manifest.Batch != 1 {
		t.Fatal(a)
	}
	ack := readAck(t, c)
	if ack.CopiedBytes != r.Manifest.LogTo || ack.Copier != CopierLabel || ack.Batch != 1 || ack.ManifestSHA != r.ManifestSHA {
		t.Fatalf("ack %+v", ack)
	}
	if s := st.ReadAck(5 * time.Minute); s.Problem != "" || !s.Fresh {
		t.Fatalf("store sees %+v", s)
	}

	// Refresh with nothing new.
	ref, err := c.Ack(r.ManifestSHA)
	if err != nil || !ref.Refreshed {
		t.Fatalf("refresh %v %+v", err, ref)
	}

	// New lines: refresh refused, next batch picks up only the new bytes, shot not re-copied.
	_ = st.Append("later", nil)
	if _, err := c.Ack(r.ManifestSHA); err == nil || !strings.Contains(err.Error(), "new log lines") {
		t.Fatalf("refresh with new lines: %v", err)
	}
	r3, err := c.Stage()
	if err != nil {
		t.Fatal(err)
	}
	if r3.Manifest.Batch != 2 || r3.Manifest.LogFrom != r.Manifest.LogTo {
		t.Fatalf("batch 2 %+v", r3.Manifest)
	}
	if _, err := c.Ack(r3.ManifestSHA); err != nil {
		t.Fatal(err)
	}
}

func TestEmptyStoreAndMissing(t *testing.T) {
	c, _ := setup(t)
	r, err := c.Stage()
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Manifest.Files) != 0 || len(r.Manifest.Missing) != 2 || r.Manifest.LogTo != 0 {
		t.Fatalf("%+v", r.Manifest)
	}
	if _, err := c.Ack(r.ManifestSHA); err != nil {
		t.Fatal(err)
	}
	// Nothing staged, unknown sha.
	if _, err := c.Ack(""); err == nil {
		t.Fatal("empty sha accepted")
	}
}

func TestRedactionSecondCheck(t *testing.T) {
	c, _ := setup(t)
	log := filepath.Join(c.Store, "log", "events.jsonl")
	key := "sk-ant-" + strings.Repeat("A1b2", 12)
	if err := os.WriteFile(log, []byte(`{"seq":1,"x":"`+key+`"}`+"\n"+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	r, err := c.Stage()
	if err != nil {
		t.Fatal(err)
	}
	if r.Manifest.Redacted == 0 {
		t.Fatal("key not counted")
	}
	data, _ := os.ReadFile(filepath.Join(r.Dir, r.Manifest.Files[0].Name))
	if strings.Contains(string(data), key) {
		t.Fatal("key left the PC")
	}
}

func TestPartialLineWaits(t *testing.T) {
	c, _ := setup(t)
	log := filepath.Join(c.Store, "log", "events.jsonl")
	_ = os.WriteFile(log, []byte(`{"seq":1}`+"\n"+`{"seq":2`), 0o644)
	r, err := c.Stage()
	if err != nil {
		t.Fatal(err)
	}
	if r.Manifest.LogTo != int64(len(`{"seq":1}`+"\n")) {
		t.Fatal(r.Manifest.LogTo)
	}
	c2, _ := setup(t)
	_ = os.WriteFile(filepath.Join(c2.Store, "log", "events.jsonl"), []byte(`{"seq":1`), 0o644)
	r, err = c2.Stage()
	if err != nil || r.Manifest.LogTo != 0 || len(r.Manifest.Files) != 0 {
		t.Fatalf("%v %+v", err, r.Manifest)
	}
}

func TestChunkCap(t *testing.T) {
	c, _ := setup(t)
	log := filepath.Join(c.Store, "log", "events.jsonl")
	line := strings.Repeat("x", 1<<20) + "\n"
	_ = os.WriteFile(log, []byte(strings.Repeat(line, 9)), 0o644)
	r, err := c.Stage()
	if err != nil {
		t.Fatal(err)
	}
	if r.Manifest.LogTo != int64(len(line)*7) { // 8 lines of 1 MiB+1 do not fit in 8 MiB
		t.Fatalf("cap: %d", r.Manifest.LogTo)
	}
	// One line longer than a batch.
	c2, _ := setup(t)
	_ = os.WriteFile(filepath.Join(c2.Store, "log", "events.jsonl"), []byte(strings.Repeat("y", MaxChunk+5)), 0o644)
	if _, err := c2.Stage(); err == nil || !strings.Contains(err.Error(), "longer than a batch") {
		t.Fatal(err)
	}
}

func TestLogShrankStops(t *testing.T) {
	c, st := setup(t)
	_ = st.Append("a", nil)
	r, _ := c.Stage()
	_, _ = c.Ack(r.ManifestSHA)
	_ = os.WriteFile(st.LogPath(), nil, 0o644)
	if _, err := c.Stage(); err == nil || !strings.Contains(err.Error(), "replaced") {
		t.Fatal(err)
	}
}

func TestRetryFolderKept(t *testing.T) {
	c, _ := setup(t)
	_ = os.MkdirAll(filepath.Join(c.Outbox, "batch_000001"), 0o755)
	_ = os.MkdirAll(filepath.Join(c.Outbox, "batch_000001_retry1"), 0o755)
	r, err := c.Stage()
	if err != nil || filepath.Base(r.Dir) != "batch_000001_retry2" {
		t.Fatalf("%v %s", err, r.Dir)
	}
}

func TestTamperDetected(t *testing.T) {
	c, st := setup(t)
	_ = st.Append("a", nil)
	r, _ := c.Stage()
	// Batch file changed.
	f := filepath.Join(r.Dir, r.Manifest.Files[0].Name)
	_ = os.WriteFile(f, []byte("changed\n"), 0o644)
	if _, err := c.Ack(r.ManifestSHA); err == nil || !strings.Contains(err.Error(), "changed since staging") {
		t.Fatal(err)
	}
	// Batch file gone.
	_ = os.Remove(f)
	if _, err := c.Ack(r.ManifestSHA); err == nil || !strings.Contains(err.Error(), "batch file") {
		t.Fatal(err)
	}
	// Manifest changed.
	mpath := filepath.Join(r.Dir, "MANIFEST.json")
	_ = os.WriteFile(mpath, []byte(`{"batch":9}`), 0o644)
	if _, err := c.Ack(r.ManifestSHA); err == nil || !strings.Contains(err.Error(), "manifest changed") {
		t.Fatal(err)
	}
	if _, err := c.Stage(); err == nil || !strings.Contains(err.Error(), "staged manifest changed") {
		t.Fatal(err)
	}
	// Manifest unreadable / gone.
	_ = os.WriteFile(mpath, []byte(`{bad`), 0o644)
	if _, err := c.Ack(r.ManifestSHA); err == nil || !strings.Contains(err.Error(), "unreadable") {
		t.Fatal(err)
	}
	_ = os.Remove(mpath)
	if _, err := c.Stage(); err == nil || !strings.Contains(err.Error(), "read manifest") {
		t.Fatal(err)
	}
}

func TestStateErrors(t *testing.T) {
	c, _ := setup(t)
	_ = os.MkdirAll(c.statePath(), 0o755) // a folder where the file should be
	if _, err := c.Stage(); err == nil || !strings.Contains(err.Error(), "read state") {
		t.Fatal(err)
	}
	if _, err := c.Ack("x"); err == nil {
		t.Fatal("ack with bad state")
	}
	c2, _ := setup(t)
	_ = os.MkdirAll(c2.Outbox, 0o755)
	_ = os.WriteFile(c2.statePath(), []byte("{bad"), 0o644)
	if _, err := c2.Stage(); err == nil || !strings.Contains(err.Error(), "unreadable") {
		t.Fatal(err)
	}
	c3, _ := setup(t)
	_ = os.MkdirAll(c3.Outbox, 0o755)
	_ = os.WriteFile(c3.statePath(), []byte(`{"log_offset":0}`), 0o644)
	if _, err := c3.Stage(); err != nil {
		t.Fatal(err)
	}
}

func TestFolderErrors(t *testing.T) {
	c, _ := setup(t)
	parent := filepath.Dir(c.Outbox)
	_ = os.WriteFile(filepath.Join(parent, "file"), nil, 0o644)
	c.Outbox = filepath.Join(parent, "file", "outbox")
	if _, err := c.Stage(); err == nil {
		t.Fatal("outbox under a file")
	}
	cA, _ := setup(t)
	oldAll := mkdirAll
	mkdirAll = func(string, os.FileMode) error { return errors.New("no") }
	_, errA := cA.Stage()
	mkdirAll = oldAll
	if errA == nil {
		t.Fatal("outbox creation error swallowed")
	}
	c2, _ := setup(t)
	old := mkdir
	mkdir = func(string, os.FileMode) error { return errors.New("no") }
	_, err := c2.Stage()
	mkdir = old
	if err == nil || !strings.Contains(err.Error(), "batch folder") {
		t.Fatal(err)
	}
}

type fakeLog struct {
	statErr, readErr error
	size             int64
}

func (f fakeLog) ReadAt([]byte, int64) (int, error) { return 0, f.readErr }
func (f fakeLog) Stat() (os.FileInfo, error)        { return fakeInfo{f.size}, f.statErr }
func (f fakeLog) Close() error                      { return nil }

type fakeInfo struct{ n int64 }

func (fakeInfo) Name() string       { return "events.jsonl" }
func (i fakeInfo) Size() int64      { return i.n }
func (fakeInfo) Mode() os.FileMode  { return 0 }
func (fakeInfo) ModTime() time.Time { return t0 }
func (fakeInfo) IsDir() bool        { return false }
func (fakeInfo) Sys() any           { return nil }

func TestLogErrors(t *testing.T) {
	old := openLog
	defer func() { openLog = old }()
	c, _ := setup(t)
	openLog = func(string) (logFile, error) { return nil, errors.New("denied") }
	if _, err := c.Stage(); err == nil || !strings.Contains(err.Error(), "open log") {
		t.Fatal(err)
	}
	c, _ = setup(t)
	openLog = func(string) (logFile, error) { return fakeLog{statErr: errors.New("stat")}, nil }
	if _, err := c.Stage(); err == nil {
		t.Fatal("stat error")
	}
	c, _ = setup(t)
	openLog = func(string) (logFile, error) { return fakeLog{size: 10, readErr: errors.New("io")}, nil }
	if _, err := c.Stage(); err == nil || !strings.Contains(err.Error(), "read log") {
		t.Fatal(err)
	}
}

type badWriter struct{ werr, cerr error }

func (b badWriter) Write(p []byte) (int, error) { return len(p), b.werr }
func (b badWriter) Close() error                { return b.cerr }

func TestWriteErrors(t *testing.T) {
	oldNew, oldAtomic := openNew, writeAtomic
	defer func() { openNew, writeAtomic = oldNew, oldAtomic }()

	for _, bw := range []badWriter{{werr: errors.New("w")}, {cerr: errors.New("c")}} {
		bw := bw
		openNew = func(string) (io.WriteCloser, error) { return bw, nil }
		if err := writeNew("x", []byte("d")); err == nil {
			t.Fatal("write error swallowed")
		}
	}
	openNew = oldNew

	// Each addFile / manifest write failing in turn.
	for fail := 1; fail <= 4; fail++ {
		c, st := setup(t)
		_ = st.Append("a", nil)
		_ = st.WriteJSON("status.json", 1)
		_ = st.WriteJSON("heartbeat.json", 1)
		n := 0
		openNew = func(p string) (io.WriteCloser, error) {
			n++
			if n == fail {
				return nil, errors.New("disk full")
			}
			return oldNew(p)
		}
		if _, err := c.Stage(); err == nil {
			t.Fatalf("write %d failure swallowed", fail)
		}
		openNew = oldNew
	}

	// State save fails after staging.
	c, _ := setup(t)
	writeAtomic = func(string, []byte) error { return errors.New("full") }
	if _, err := c.Stage(); err == nil {
		t.Fatal("state save error swallowed")
	}
	writeAtomic = oldAtomic

	// Ack write fails; state save after ack fails; refresh write fails.
	c, st := setup(t)
	_ = st.Append("a", nil)
	r, _ := c.Stage()
	writeAtomic = func(string, []byte) error { return errors.New("full") }
	if _, err := c.Ack(r.ManifestSHA); err == nil {
		t.Fatal("ack write error swallowed")
	}
	calls := 0
	writeAtomic = func(p string, d []byte) error {
		calls++
		if calls == 2 {
			return errors.New("full")
		}
		return oldAtomic(p, d)
	}
	if _, err := c.Ack(r.ManifestSHA); err == nil {
		t.Fatal("state save after ack swallowed")
	}
	writeAtomic = oldAtomic
	c, st = setup(t)
	r, _ = c.Stage()
	_, _ = c.Ack(r.ManifestSHA)
	writeAtomic = func(string, []byte) error { return errors.New("full") }
	if _, err := c.Ack(r.ManifestSHA); err == nil {
		t.Fatal("refresh write error swallowed")
	}
	writeAtomic = oldAtomic
}

func TestWriteAtomicErrors(t *testing.T) {
	dir := t.TempDir()
	if err := writeAtomic(filepath.Join(dir, "no", "x"), nil); err == nil {
		t.Fatal("missing folder")
	}
	_ = os.MkdirAll(filepath.Join(dir, "d", "inner"), 0o755)
	_ = os.WriteFile(filepath.Join(dir, "d", "inner", "f"), nil, 0o644)
	if err := writeAtomic(filepath.Join(dir, "d"), nil); err == nil {
		t.Fatal("rename over non-empty folder")
	}
}

func TestNeedsSplit(t *testing.T) {
	dir := t.TempDir()
	var m Manifest
	if err := (&Copier{}).addFile(dir, "big", make([]byte, MaxFile+1), &m); err != nil {
		t.Fatal(err)
	}
	if !m.Files[0].NeedsSplit {
		t.Fatal("big file not flagged")
	}
}
