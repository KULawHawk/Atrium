// Package copyoff moves PhoneRunner's results off the PC in batches the PC lane
// can send to the project share (Hard Rule 8: results copied as they come in).
//
// It runs as Jake (read access to the store, write access to the store's ack
// folder and to an outbox folder). One cycle is:
//
//	stage  -> copies new log lines (re-checked by the key filter) and the latest
//	          status and heartbeat into outbox\batch_NNNNNN\, with a MANIFEST.json
//	          listing every file's size and sha256
//	(lane) -> sends that batch folder to the share
//	ack    -> given the manifest's sha256, re-checks every file is unchanged and
//	          writes the store's ack\copy_ack.json so the phone page shows the
//	          copy is current
//
// Pictures are never copied here: they live in the SYSTEM-only captures folder,
// which Jake (and so this tool) cannot read. Under Decision 266 = A the service
// itself will export filtered pictures once the picture filter exists.
//
// Nothing here deletes or rewrites a result file. Only one batch is staged at a
// time; staging again before the ack returns the same batch.
package copyoff

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/redact"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

// MaxChunk caps one batch's log file, below the PC lane's ~10 MB transfer limit.
const MaxChunk = 8 << 20

// MaxFile is the transfer limit; bigger files are listed with NeedsSplit set.
const MaxFile = 10 << 20

// CopierLabel marks the ack as the lane's own claim, not proof.
const CopierLabel = "pc lane (claim: batch sent to share)"

// FileEntry is one file in a batch.
type FileEntry struct {
	Name       string `json:"name"`
	Bytes      int64  `json:"bytes"`
	SHA256     string `json:"sha256"`
	NeedsSplit bool   `json:"needs_split,omitempty"`
}

// Manifest describes one staged batch.
type Manifest struct {
	Batch    int         `json:"batch"`
	At       time.Time   `json:"at"`
	LogFrom  int64       `json:"log_from"`
	LogTo    int64       `json:"log_to"`
	Redacted int         `json:"redacted"`
	Missing  []string    `json:"missing,omitempty"`
	Files    []FileEntry `json:"files"`
}

// State is kept in the outbox; it is the copier's bookkeeping, not a result.
type State struct {
	LogOffset int64   `json:"log_offset"`
	Batches   int     `json:"batches"`
	Staged    *Staged `json:"staged,omitempty"`
	LastAcked string  `json:"last_acked_manifest_sha256,omitempty"`
}

// Staged points at the batch waiting for its ack.
type Staged struct {
	Dir         string `json:"dir"`
	ManifestSHA string `json:"manifest_sha256"`
	LogTo       int64  `json:"log_to"`
	Batch       int    `json:"batch"`
}

// Result is what a command prints.
type Result struct {
	Dir         string
	ManifestSHA string
	Manifest    Manifest
	Reused      bool
	Refreshed   bool
}

// Copier holds the two folders and a clock.
type Copier struct {
	Store  string
	Outbox string
	Now    func() time.Time
}

func (c *Copier) statePath() string { return filepath.Join(c.Outbox, "copyoff_state.json") }

func (c *Copier) loadState() (State, error) {
	st := State{}
	data, err := os.ReadFile(c.statePath())
	if errors.Is(err, os.ErrNotExist) {
		return st, nil
	}
	if err != nil {
		return st, fmt.Errorf("copyoff: read state: %w", err)
	}
	if err := json.Unmarshal(data, &st); err != nil {
		return st, fmt.Errorf("copyoff: state file is unreadable: %w", err)
	}
	return st, nil
}

func (c *Copier) saveState(st State) error {
	data, _ := json.MarshalIndent(st, "", "  ")
	return writeAtomic(c.statePath(), data)
}

var writeAtomic = func(path string, data []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return fmt.Errorf("copyoff: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return fmt.Errorf("copyoff: %w", err)
	}
	return nil
}

// openNew creates a file that must not already exist (a seam for tests).
var openNew = func(path string) (io.WriteCloser, error) {
	return os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
}

// logFile is the part of *os.File that readLog uses (a seam for tests).
type logFile interface {
	io.ReaderAt
	Stat() (os.FileInfo, error)
	Close() error
}

var openLog = func(path string) (logFile, error) { return os.Open(path) }

var mkdir, mkdirAll = os.Mkdir, os.MkdirAll

// writeNew writes a file that must not already exist (results are never overwritten).
func writeNew(path string, data []byte) error {
	f, err := openNew(path)
	if err != nil {
		return fmt.Errorf("copyoff: %w", err)
	}
	_, werr := f.Write(data)
	cerr := f.Close()
	if werr != nil {
		return fmt.Errorf("copyoff: %w", werr)
	}
	if cerr != nil {
		return fmt.Errorf("copyoff: %w", cerr)
	}
	return nil
}

func sum(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

// readLog returns complete lines from offset, at most MaxChunk bytes.
func readLog(path string, offset int64) ([]byte, int64, error) {
	f, err := openLog(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, offset, nil
	}
	if err != nil {
		return nil, offset, fmt.Errorf("copyoff: open log: %w", err)
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		return nil, offset, fmt.Errorf("copyoff: %w", err)
	}
	if fi.Size() < offset {
		return nil, offset, fmt.Errorf("copyoff: log is shorter (%d bytes) than already copied (%d): log was replaced, stop and tell Jake", fi.Size(), offset)
	}
	n := fi.Size() - offset
	if n > MaxChunk {
		n = MaxChunk
	}
	buf := make([]byte, n)
	if _, err := f.ReadAt(buf, offset); err != nil && !errors.Is(err, io.EOF) {
		return nil, offset, fmt.Errorf("copyoff: read log: %w", err)
	}
	end := bytes.LastIndexByte(buf, '\n')
	if end < 0 {
		if n == MaxChunk {
			return nil, offset, errors.New("copyoff: one log line is longer than a batch")
		}
		return nil, offset, nil // only a partial line so far
	}
	return buf[:end+1], offset + int64(end+1), nil
}

// filterLines re-runs the key filter over each line (the log was filtered when
// written; this is a second check before anything leaves the PC).
func filterLines(chunk []byte) ([]byte, int) {
	lines := strings.SplitAfter(string(chunk), "\n")
	var out strings.Builder
	count := 0
	for _, ln := range lines {
		if ln == "" {
			continue
		}
		r := redact.Text(strings.TrimSuffix(ln, "\n"))
		count += r.Count
		out.WriteString(r.Text)
		out.WriteByte('\n')
	}
	return []byte(out.String()), count
}

// Stage builds the next batch, or returns the batch already waiting for its ack.
func (c *Copier) Stage() (Result, error) {
	st, err := c.loadState()
	if err != nil {
		return Result{}, err
	}
	if st.Staged != nil {
		m, msha, err := c.readManifest(st.Staged.Dir)
		if err != nil {
			return Result{}, err
		}
		if msha != st.Staged.ManifestSHA {
			return Result{}, fmt.Errorf("copyoff: staged manifest changed on disk (%s, expected %s): stop and tell Jake", msha, st.Staged.ManifestSHA)
		}
		return Result{Dir: st.Staged.Dir, ManifestSHA: msha, Manifest: m, Reused: true}, nil
	}
	if err := mkdirAll(c.Outbox, 0o755); err != nil {
		return Result{}, fmt.Errorf("copyoff: %w", err)
	}
	batch := st.Batches + 1
	dir, err := newBatchDir(c.Outbox, batch)
	if err != nil {
		return Result{}, err
	}
	m := Manifest{Batch: batch, At: c.Now().UTC(), LogFrom: st.LogOffset, Files: []FileEntry{}}

	chunk, to, err := readLog(filepath.Join(c.Store, "log", "events.jsonl"), st.LogOffset)
	if err != nil {
		return Result{}, err
	}
	m.LogTo = to
	if len(chunk) > 0 {
		filtered, n := filterLines(chunk)
		m.Redacted = n
		name := fmt.Sprintf("events_%012d-%012d.jsonl", st.LogOffset, to)
		if err := c.addFile(dir, name, filtered, &m); err != nil {
			return Result{}, err
		}
	}
	for _, f := range []string{"status.json", "heartbeat.json"} {
		data, rerr := os.ReadFile(filepath.Join(c.Store, f))
		if rerr != nil {
			m.Missing = append(m.Missing, f)
			continue
		}
		filtered := []byte(redact.Text(string(data)).Text)
		if err := c.addFile(dir, f, filtered, &m); err != nil {
			return Result{}, err
		}
	}
	data, _ := json.MarshalIndent(m, "", "  ")
	if err := writeNew(filepath.Join(dir, "MANIFEST.json"), data); err != nil {
		return Result{}, err
	}
	msha := sum(data)
	st.Staged = &Staged{Dir: dir, ManifestSHA: msha, LogTo: to, Batch: batch}
	st.Batches = batch
	if err := c.saveState(st); err != nil {
		return Result{}, err
	}
	return Result{Dir: dir, ManifestSHA: msha, Manifest: m}, nil
}

// newBatchDir makes a fresh folder for the batch. A folder left by an earlier
// failed attempt is kept (never deleted) and a retry name is used instead.
func newBatchDir(outbox string, batch int) (string, error) {
	for i := 0; ; i++ {
		name := fmt.Sprintf("batch_%06d", batch)
		if i > 0 {
			name = fmt.Sprintf("batch_%06d_retry%d", batch, i)
		}
		dir := filepath.Join(outbox, name)
		err := mkdir(dir, 0o755)
		if err == nil {
			return dir, nil
		}
		if !errors.Is(err, os.ErrExist) {
			return "", fmt.Errorf("copyoff: batch folder: %w", err)
		}
	}
}

func (c *Copier) addFile(dir, name string, data []byte, m *Manifest) error {
	if err := writeNew(filepath.Join(dir, name), data); err != nil {
		return err
	}
	m.Files = append(m.Files, FileEntry{Name: name, Bytes: int64(len(data)), SHA256: sum(data), NeedsSplit: len(data) > MaxFile})
	return nil
}

func (c *Copier) readManifest(dir string) (Manifest, string, error) {
	data, err := os.ReadFile(filepath.Join(dir, "MANIFEST.json"))
	if err != nil {
		return Manifest{}, "", fmt.Errorf("copyoff: read manifest: %w", err)
	}
	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return Manifest{}, "", fmt.Errorf("copyoff: manifest is unreadable: %w", err)
	}
	return m, sum(data), nil
}

// Ack records that the staged batch with this manifest sha256 was sent to the
// share. With nothing staged, acking the last batch again only refreshes the
// time, and only if no new log bytes have appeared since.
func (c *Copier) Ack(manifestSHA string) (Result, error) {
	st, err := c.loadState()
	if err != nil {
		return Result{}, err
	}
	logSize := int64(0)
	if fi, err := os.Stat(filepath.Join(c.Store, "log", "events.jsonl")); err == nil {
		logSize = fi.Size()
	}
	if st.Staged == nil {
		if manifestSHA == "" || manifestSHA != st.LastAcked {
			return Result{}, errors.New("copyoff: nothing is staged and that is not the last acknowledged batch: run stage first")
		}
		if logSize != st.LogOffset {
			return Result{}, errors.New("copyoff: new log lines since the last batch: run stage, send, then ack the new batch")
		}
		if err := c.writeAck(st.LogOffset); err != nil {
			return Result{}, err
		}
		return Result{ManifestSHA: manifestSHA, Refreshed: true}, nil
	}
	if manifestSHA != st.Staged.ManifestSHA {
		return Result{}, fmt.Errorf("copyoff: that sha256 does not match the staged batch %d (%s)", st.Staged.Batch, st.Staged.ManifestSHA)
	}
	m, msha, err := c.readManifest(st.Staged.Dir)
	if err != nil {
		return Result{}, err
	}
	if msha != manifestSHA {
		return Result{}, fmt.Errorf("copyoff: manifest changed on disk since staging (%s): stop and tell Jake", msha)
	}
	for _, f := range m.Files {
		data, err := os.ReadFile(filepath.Join(st.Staged.Dir, f.Name))
		if err != nil {
			return Result{}, fmt.Errorf("copyoff: batch file %s: %w", f.Name, err)
		}
		if got := sum(data); got != f.SHA256 {
			return Result{}, fmt.Errorf("copyoff: batch file %s changed since staging (%s, expected %s): stop and tell Jake", f.Name, got, f.SHA256)
		}
	}
	if err := c.writeAck(st.Staged.LogTo); err != nil {
		return Result{}, err
	}
	res := Result{Dir: st.Staged.Dir, ManifestSHA: manifestSHA, Manifest: m}
	st.LogOffset = st.Staged.LogTo
	st.LastAcked = manifestSHA
	st.Staged = nil
	if err := c.saveState(st); err != nil {
		return Result{}, err
	}
	return res, nil
}

func (c *Copier) writeAck(copied int64) error {
	a := store.Ack{At: c.Now().UTC(), CopiedBytes: copied, Copier: CopierLabel}
	data, _ := json.MarshalIndent(a, "", "  ")
	return writeAtomic(filepath.Join(c.Store, "ack", "copy_ack.json"), data)
}
