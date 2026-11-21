// Package inbox reads staged items for the Run button and builds what the phone
// shows before a tap: the header, the manifest (every file with its sha256),
// badges, and the difference from the last approved version. After a tap is
// approved it copies the exact approved bytes into the protected store.
//
// An item is a folder in the inbox:
//
//	<inbox>\<item-id>\item.json   the header (below)
//	<inbox>\<item-id>\run.ps1     the entry script named by the header
//	<inbox>\<item-id>\...         any other file it uses
//
// The inbox is writable by Jake's account (that is how lanes stage items), so
// nothing here trusts it: the manifest pins every byte, and the copy into the
// store is checked against the manifest the phone approved.
package inbox

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Limits on what an item may hold.
const (
	MaxFiles     = 200
	MaxFileBytes = 10 << 20
	MaxDiffLines = 2000
)

// Seams for tests that need a failing disk.
var (
	load      = Load
	writeFile = os.WriteFile
)

var idRE = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,63}$`)

// Header is item.json, written by the proposing lane.
type Header struct {
	Title        string `json:"title"`
	ClaimedBy    string `json:"claimed_by"`
	Entry        string `json:"entry"`
	EstimateTime string `json:"estimate_time"`
	EstimateCost string `json:"estimate_cost"`
	NeedsDesktop bool   `json:"needs_desktop"`
	// OutputMayCopy lets the item's output lines into the event log, which is
	// copied off the PC. Off unless the item says so: output stays on the PC.
	OutputMayCopy bool `json:"output_may_copy"`
}

// File is one manifest line.
type File struct {
	Rel    string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

// Item is what the phone card shows.
type Item struct {
	ID          string   `json:"id"`
	Header      Header   `json:"header"`
	Files       []File   `json:"files"`
	ManifestSHA string   `json:"manifest_sha256"`
	Badges      []string `json:"badges"`
	Problems    []string `json:"problems"` // any problem means Run is refused
}

// Runnable is true when nothing blocks a tap.
func (it Item) Runnable() bool { return len(it.Problems) == 0 }

// badge rules (plan 6.4). The scan is a pattern match and can be evaded; it
// helps the reader, it does not prove anything.
var badgeRules = []struct {
	name string
	re   *regexp.Regexp
}{
	{"installs software", regexp.MustCompile(`(?i)\b(msiexec|install-package|install-module|winget|choco|add-appxpackage|pip3?\s+install)\b|setup\.exe|\.msi\b`)},
	{"reads a key or secret", regexp.MustCompile(`(?i)\b(get-storedcredential|credentialmanager|cmdkey|convertto-securestring|get-secret)\b|\$env:\w*(key|token|secret|password)`)},
	{"starts a billed service", regexp.MustCompile(`(?i)\b(runpod|runpodctl|start-pod|run-instances)\b`)},
	{"deletes files", regexp.MustCompile(`(?i)\b(remove-item|clear-content|rmdir|rd|del|erase|rm)\b`)},
	{"changes Windows settings", regexp.MustCompile(`(?i)\b(set-itemproperty|new-itemproperty|reg\s+add|reg\s+delete|set-mppreference|netsh|bcdedit|set-executionpolicy|sc\s+config)\b`)},
	{"needs a Windows security box", regexp.MustCompile(`(?i)-verb\s+runas|\bwebauthn\b|windows hello`)},
	{"may start programs that Stop cannot end", regexp.MustCompile(`(?i)\b(invoke-wmimethod|invoke-cimmethod|win32_process|schtasks|register-scheduledtask|new-scheduledtask|new-service|explorer(\.exe)?|sc(\.exe)?\s+create)\b`)},
	{"REMOTE CODE: fetches or runs code not shown here", regexp.MustCompile(`(?i)\b(iex|invoke-expression|downloadstring|downloadfile|invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|start-bitstransfer|frombase64string)\b|\b(exec|eval)\s*\(|[a-z0-9+/]{200,}={0,2}`)},
}

var textExt = map[string]bool{".ps1": true, ".psm1": true, ".psd1": true, ".py": true, ".cmd": true, ".bat": true, ".json": true, ".txt": true, ".md": true, ".csv": true, ".yaml": true, ".yml": true}

// Load reads one item folder. It never fails for a bad item: problems are
// listed on the item so the phone can show why Run is refused. It fails only if
// the folder itself cannot be read.
func Load(dir string) (Item, error) {
	it := Item{ID: filepath.Base(dir), Badges: []string{}, Problems: []string{}}
	if !idRE.MatchString(it.ID) {
		it.Problems = append(it.Problems, "item folder name must be lowercase letters, digits, - or _ (64 at most)")
	}
	var rels []string
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if p == dir {
			return nil
		}
		rel, _ := filepath.Rel(dir, p)
		rel = filepath.ToSlash(rel)
		if d.Type()&fs.ModeSymlink != 0 || d.Type()&fs.ModeIrregular != 0 {
			it.Problems = append(it.Problems, rel+": links and special files are not allowed")
			return nil
		}
		if d.IsDir() {
			return nil
		}
		if SafeRel(rel) != nil {
			it.Problems = append(it.Problems, rel+": file name must not contain a backslash or colon")
			return nil
		}
		rels = append(rels, rel)
		return nil
	})
	if err != nil {
		return Item{}, fmt.Errorf("inbox: %w", err)
	}
	sort.Strings(rels)
	if len(rels) > MaxFiles {
		it.Problems = append(it.Problems, fmt.Sprintf("%d files; at most %d", len(rels), MaxFiles))
		rels = rels[:MaxFiles]
	}
	seen := map[string]bool{}
	var unread []string
	for _, rel := range rels {
		b, err := ReadInside(dir, rel)
		if err != nil {
			it.Problems = append(it.Problems, rel+": "+err.Error())
			continue
		}
		h := sha256.Sum256(b)
		it.Files = append(it.Files, File{Rel: rel, SHA256: hex.EncodeToString(h[:]), Size: int64(len(b))})
		if !textExt[strings.ToLower(filepath.Ext(rel))] {
			unread = append(unread, rel)
		} else {
			for _, r := range badgeRules {
				if !seen[r.name] && r.re.Match(b) {
					seen[r.name] = true
					it.Badges = append(it.Badges, r.name)
				}
			}
		}
		if rel == "item.json" {
			dec := json.NewDecoder(bytes.NewReader(b))
			dec.DisallowUnknownFields()
			if err := dec.Decode(&it.Header); err != nil {
				it.Problems = append(it.Problems, "item.json: "+err.Error())
			}
		}
	}
	if len(unread) > 0 {
		it.Badges = append(it.Badges, "contains files the scan cannot read: "+strings.Join(unread, ", "))
	}
	it.checkHeader()
	it.ManifestSHA = ManifestSHA(it.Files)
	return it, nil
}

func (it *Item) checkHeader() {
	h := it.Header
	if strings.TrimSpace(h.Title) == "" {
		it.Problems = append(it.Problems, "item.json: title is missing")
	}
	if strings.TrimSpace(h.ClaimedBy) == "" {
		it.Problems = append(it.Problems, "item.json: claimed_by is missing")
	}
	if strings.ToLower(filepath.Ext(h.Entry)) != ".ps1" || strings.ContainsAny(h.Entry, `/\:`) {
		it.Problems = append(it.Problems, "item.json: entry must be a .ps1 file in the item folder itself")
		return
	}
	for _, f := range it.Files {
		if f.Rel == h.Entry {
			return
		}
	}
	it.Problems = append(it.Problems, "item.json: entry "+h.Entry+" is not in the folder")
}

// NotStated is shown in red for a missing estimate.
const NotStated = "not stated"

// Estimates returns time and cost, NotStated when missing.
func (it Item) Estimates() (string, string) {
	t, c := strings.TrimSpace(it.Header.EstimateTime), strings.TrimSpace(it.Header.EstimateCost)
	if t == "" {
		t = NotStated
	}
	if c == "" {
		c = NotStated
	}
	return t, c
}

var errTooBig = fmt.Errorf("larger than %d bytes", MaxFileBytes)

// ManifestSHA is the sha256 of the manifest text, one "sha256  path" line per
// file in path order (the same form sha256sum prints).
func ManifestSHA(files []File) string {
	h := sha256.New()
	for _, f := range files {
		fmt.Fprintf(h, "%s  %s\n", f.SHA256, f.Rel)
	}
	return hex.EncodeToString(h.Sum(nil))
}

// List loads every item folder in the inbox, sorted by id.
func List(inbox string) ([]Item, error) {
	es, err := os.ReadDir(inbox)
	if err != nil {
		return nil, fmt.Errorf("inbox: %w", err)
	}
	var out []Item
	for _, e := range es {
		if !e.IsDir() {
			continue
		}
		it, err := load(filepath.Join(inbox, e.Name()))
		if err != nil {
			return nil, err
		}
		out = append(out, it)
	}
	return out, nil
}

// ErrBadPath means a manifest path could point outside the item folder.
var ErrBadPath = errors.New("a file path in the manifest is not a plain path inside the item")

// SafeRel accepts only a plain relative path inside the item: forward slashes,
// no absolute or volume prefix, no "..", ".", empty segment, backslash or colon.
func SafeRel(rel string) error {
	if rel == "" || strings.ContainsAny(rel, "\\:") || strings.HasPrefix(rel, "/") {
		return fmt.Errorf("%w: %q", ErrBadPath, rel)
	}
	for _, seg := range strings.Split(rel, "/") {
		if seg == "" || seg == "." || seg == ".." {
			return fmt.Errorf("%w: %q", ErrBadPath, rel)
		}
	}
	return nil
}

// ErrCopyMismatch means a file changed between the tap and the copy.
var ErrCopyMismatch = errors.New("a file changed after you approved it; nothing was copied or run")

// CopyApproved copies the item's files from src into dst (a new folder in the
// protected store) and checks that the bytes written hash to the approved
// manifest. On any mismatch dst is left incomplete and an error is returned;
// the caller must not run it. It hashes the bytes it writes, not the source
// afterwards, so what runs is exactly what was approved.
//
// approved must be the service's own Load snapshot taken when the tap began,
// never a list sent back by the page.
func CopyApproved(src, dst string, approved []File, approvedSHA string) error {
	if ManifestSHA(approved) != approvedSHA {
		return ErrCopyMismatch
	}
	for _, f := range approved {
		if err := SafeRel(f.Rel); err != nil {
			return err
		}
	}
	if _, err := os.Stat(dst); err == nil {
		return fmt.Errorf("inbox: %s already exists", dst)
	}
	for _, f := range approved {
		b, err := ReadInside(src, f.Rel)
		if err != nil {
			return fmt.Errorf("inbox: %s: %w", f.Rel, err)
		}
		h := sha256.Sum256(b)
		if hex.EncodeToString(h[:]) != f.SHA256 {
			return ErrCopyMismatch
		}
		out := filepath.Join(dst, filepath.FromSlash(f.Rel))
		if err := os.MkdirAll(filepath.Dir(out), 0o700); err != nil {
			return fmt.Errorf("inbox: %w", err)
		}
		if err := writeFile(out, b, 0o600); err != nil {
			return fmt.Errorf("inbox: %w", err)
		}
	}
	// The source must not have grown new files either.
	now, err := load(src)
	if err != nil {
		return fmt.Errorf("inbox: %w", err)
	}
	if now.ManifestSHA != approvedSHA {
		return ErrCopyMismatch
	}
	return nil
}

// Change is one file's difference from the last approved version.
type Change struct {
	Rel  string `json:"path"`
	What string `json:"what"` // added, removed, changed
}

// Changes compares a manifest with the last approved one.
func Changes(prev, cur []File) []Change {
	p := map[string]string{}
	for _, f := range prev {
		p[f.Rel] = f.SHA256
	}
	out := []Change{}
	for _, f := range cur {
		switch old, ok := p[f.Rel]; {
		case !ok:
			out = append(out, Change{f.Rel, "added"})
		case old != f.SHA256:
			out = append(out, Change{f.Rel, "changed"})
		}
		delete(p, f.Rel)
	}
	var gone []string
	for r := range p {
		gone = append(gone, r)
	}
	sort.Strings(gone)
	for _, r := range gone {
		out = append(out, Change{r, "removed"})
	}
	return out
}

// LineDiff returns a simple line diff ("  ", "- ", "+ " prefixes) of two texts.
// Past MaxDiffLines on either side it says so instead of diffing.
func LineDiff(a, b string) []string {
	x, y := splitLines(a), splitLines(b)
	if len(x) > MaxDiffLines || len(y) > MaxDiffLines {
		return []string{fmt.Sprintf("(too long to compare here: %d and %d lines; full text shown below)", len(x), len(y))}
	}
	// longest common subsequence table
	n, m := len(x), len(y)
	t := make([][]int, n+1)
	for i := range t {
		t[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if x[i] == y[j] {
				t[i][j] = t[i+1][j+1] + 1
			} else {
				t[i][j] = max(t[i+1][j], t[i][j+1])
			}
		}
	}
	var out []string
	i, j := 0, 0
	for i < n && j < m {
		switch {
		case x[i] == y[j]:
			out = append(out, "  "+x[i])
			i++
			j++
		case t[i+1][j] >= t[i][j+1]:
			out = append(out, "- "+x[i])
			i++
		default:
			out = append(out, "+ "+y[j])
			j++
		}
	}
	for ; i < n; i++ {
		out = append(out, "- "+x[i])
	}
	for ; j < m; j++ {
		out = append(out, "+ "+y[j])
	}
	return out
}

func splitLines(s string) []string {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	if s == "" {
		return nil
	}
	return strings.Split(strings.TrimSuffix(s, "\n"), "\n")
}
