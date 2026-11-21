// Package control joins the Run button's parts: the staged items (inbox), the
// passkey check (approve) and the runner. It is what the phone page's Run and
// Stop buttons call.
//
// The order for one Run tap:
//
//  1. BeginTap loads the item from the inbox, refuses it if it has a problem or
//     the PC is not ready (Run button off, PC locked, desktop watcher not
//     reporting, another item running), and asks the approver for a challenge
//     bound to the item, its manifest sha256, the action and the phone's
//     Tailscale device. It keeps its own copy of the item as loaded (the
//     snapshot), keyed by that manifest sha256.
//  2. Jake unlocks his phone and its passkey signs the challenge.
//  3. FinishTap has the approver check the signature, the device, the time
//     limit and the manifest. It then copies exactly the snapshot's files into a
//     new protected folder (inbox.CopyApproved re-hashes every byte written), and
//     starts the fixed command on that copy. The file list never comes from the
//     page.
//
// Stop is approved the same way, bound to the running item's manifest.
package control

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/go-webauthn/webauthn/protocol"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/approve"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/inbox"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/redact"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
)

// Approver is the passkey check (approve.Approver satisfies it).
type Approver interface {
	Begin(req approve.Request) (*protocol.CredentialAssertion, error)
	Finish(deviceID string, resp *protocol.ParsedCredentialAssertionData, manifest func(itemID string) (string, error)) (approve.Request, error)
}

// Runner runs one item at a time (runner.Runner satisfies it).
type Runner interface {
	Start(itemID, manifestSHA string, spec runner.Spec, o runner.Options) error
	Stop() error
	Current() runner.Run
}

// Paths are the folders the Run button uses. On the PC:
//
//	Inbox     staged items; Jake's account can write (that is how lanes stage)
//	Approved  one protected copy per approved run; Jake's account can only read
//	Work      one scratch folder (TEMP) per run; Jake's account can write
//	Output    PC-only output files; SYSTEM and Administrators only, never copied
//	Ledger    the last approved version of each item; SYSTEM and Administrators
type Paths struct {
	Inbox, Approved, Work, Output, Ledger string
	SystemRoot                            string
}

// Approved is the last approved version of one item.
type Approved struct {
	Dir         string       `json:"dir"`
	ManifestSHA string       `json:"manifest_sha256"`
	Files       []inbox.File `json:"files"`
	At          time.Time    `json:"at"`
}

// Errors.
var (
	ErrNotRunnable = errors.New("this item has problems; Run is refused until they are fixed")
	ErrAction      = errors.New("that action is not available")
	ErrNotThisItem = errors.New("that item is not the one running")
	ErrNoSnapshot  = errors.New("the approval does not match a Run tap from this page (it expired or the service restarted); tap Run again")
	ErrBadID       = errors.New("not a valid item id")
)

// Seams for tests that need a failing disk.
var (
	marshal  = json.MarshalIndent
	mkdirAll = os.MkdirAll
	copyIn   = inbox.CopyApproved
)

type snap struct {
	item inbox.Item
	at   time.Time
}

// Control is safe for concurrent use.
type Control struct {
	p     Paths
	ap    Approver
	run   Runner
	ready func() error // nil when the PC can take a run now
	log   func(string, map[string]any)
	now   func() time.Time

	mu        sync.Mutex
	snaps     map[string]snap
	last      map[string]Approved
	runBadges []string
	keepErr   bool
}

// New loads the ledger (a missing ledger means nothing approved yet; a damaged
// one refuses to start, so a lost history is never silent).
func New(p Paths, ap Approver, run Runner, ready func() error, log func(string, map[string]any), now func() time.Time) (*Control, error) {
	c := &Control{p: p, ap: ap, run: run, ready: ready, log: log, now: now, snaps: map[string]snap{}, last: map[string]Approved{}}
	b, err := os.ReadFile(p.Ledger)
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return nil, fmt.Errorf("control: %w", err)
	default:
		if err := json.Unmarshal(b, &c.last); err != nil {
			return nil, fmt.Errorf("control: %s is damaged: refusing to start (%v)", p.Ledger, err)
		}
	}
	return c, nil
}

// Card is one item as the phone shows it.
type Card struct {
	inbox.Item
	Time         string         `json:"estimate_time_shown"`
	Cost         string         `json:"estimate_cost_shown"`
	FirstTime    bool           `json:"first_time"`
	Changes      []inbox.Change `json:"changes"`
	LastApproved time.Time      `json:"last_approved,omitzero"`
}

// Items lists the inbox with each item's changes since its last approval.
func (c *Control) Items() ([]Card, error) {
	items, err := inbox.List(c.p.Inbox)
	if err != nil {
		return nil, err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	cards := []Card{}
	for _, it := range items {
		cd := Card{Item: it}
		cd.Time, cd.Cost = it.Estimates()
		prev, ok := c.last[it.ID]
		cd.FirstTime = !ok
		cd.Changes = inbox.Changes(prev.Files, it.Files)
		cd.LastApproved = prev.At
		cards = append(cards, cd)
	}
	return cards, nil
}

// FileView is one file's text and its difference from the last approved copy.
type FileView struct {
	Path     string   `json:"path"`
	Text     string   `json:"text"`
	Masked   int      `json:"masked"`
	Diff     []string `json:"diff"`
	Previous bool     `json:"has_previous"`
}

// MaxView caps the text sent to the phone for one file.
const MaxView = 256 << 10

// File returns one file of an item, key-redacted, with a line diff against the
// last approved copy of the same file when there is one.
func (c *Control) File(itemID, rel string) (FileView, error) {
	if err := checkID(itemID); err != nil {
		return FileView{}, err
	}
	if err := inbox.SafeRel(rel); err != nil {
		return FileView{}, err
	}
	cur, err := readView(filepath.Join(c.p.Inbox, itemID), rel)
	if err != nil {
		return FileView{}, fmt.Errorf("control: %w", err)
	}
	res := redact.Text(cur)
	v := FileView{Path: rel, Text: res.Text, Masked: res.Count, Diff: []string{}}
	c.mu.Lock()
	prev, ok := c.last[itemID]
	c.mu.Unlock()
	if ok {
		if old, err := readView(prev.Dir, rel); err == nil {
			v.Previous = true
			v.Diff = inbox.LineDiff(redact.Text(old).Text, res.Text)
		}
	}
	return v, nil
}

// readView reads through inbox.ReadInside, so a link or junction an agent
// swapped into the Jake-writable inbox cannot make this SYSTEM service show a
// file Jake's account cannot read.
func readView(root, rel string) (string, error) {
	b, err := inbox.ReadInside(root, rel)
	if err != nil {
		return "", err
	}
	if len(b) > MaxView {
		return string(b[:MaxView]) + "\n…(cut: file is longer than shown here)", nil
	}
	return string(b), nil
}

func checkID(id string) error {
	if err := inbox.SafeRel(id); err != nil || filepath.Base(id) != id {
		return ErrBadID
	}
	return nil
}

// BeginTap starts one tap's approval.
func (c *Control) BeginTap(deviceID, itemID, action string) (*protocol.CredentialAssertion, error) {
	if err := checkID(itemID); err != nil {
		return nil, err
	}
	cur := c.run.Current()
	switch action {
	case "run":
		if cur.Running() {
			return nil, runner.ErrBusy
		}
		if err := c.ready(); err != nil {
			return nil, err
		}
		it, err := inbox.Load(filepath.Join(c.p.Inbox, itemID))
		if err != nil {
			return nil, err
		}
		if !it.Runnable() {
			return nil, ErrNotRunnable
		}
		opts, err := c.ap.Begin(approve.Request{ItemID: itemID, ManifestSHA: it.ManifestSHA, Action: action, DeviceID: deviceID})
		if err != nil {
			return nil, err
		}
		c.mu.Lock()
		c.sweep()
		c.snaps[it.ManifestSHA] = snap{item: it, at: c.now()}
		c.mu.Unlock()
		return opts, nil
	case "stop":
		if !cur.Running() {
			return nil, runner.ErrNotRunning
		}
		if cur.ItemID != itemID {
			return nil, ErrNotThisItem
		}
		return c.ap.Begin(approve.Request{ItemID: itemID, ManifestSHA: cur.ManifestSHA, Action: action, DeviceID: deviceID})
	}
	return nil, ErrAction
}

func (c *Control) sweep() {
	for k, s := range c.snaps {
		if c.now().Sub(s.at) > approve.TTL {
			delete(c.snaps, k)
		}
	}
}

// manifest is what the approver re-checks: the running item's manifest for the
// item that is running (a Stop), otherwise the inbox's current one (a Run).
func (c *Control) manifest(itemID string) (string, error) {
	if cur := c.run.Current(); cur.Running() && cur.ItemID == itemID {
		return cur.ManifestSHA, nil
	}
	it, err := inbox.Load(filepath.Join(c.p.Inbox, itemID))
	if err != nil {
		return "", err
	}
	return it.ManifestSHA, nil
}

// Result is what the phone shows after a tap.
type Result struct {
	Action string `json:"action"`
	ItemID string `json:"item_id"`
	Done   string `json:"done"`
}

// FinishTap checks the signed answer and does the approved action.
func (c *Control) FinishTap(deviceID string, resp *protocol.ParsedCredentialAssertionData) (Result, error) {
	req, err := c.ap.Finish(deviceID, resp, c.manifest)
	if err != nil {
		c.log("tap.refused", map[string]any{"error": err.Error()})
		return Result{}, err
	}
	c.log("tap.approved", map[string]any{"item": req.ItemID, "action": req.Action, "manifest_sha256": req.ManifestSHA})
	res := Result{Action: req.Action, ItemID: req.ItemID}
	if req.Action == "stop" {
		if err := c.run.Stop(); err != nil {
			return res, err
		}
		res.Done = "stopped"
		return res, nil
	}
	c.mu.Lock()
	s, ok := c.snaps[req.ManifestSHA]
	delete(c.snaps, req.ManifestSHA)
	c.mu.Unlock()
	if !ok || s.item.ID != req.ItemID {
		return res, ErrNoSnapshot
	}
	if err := c.ready(); err != nil {
		return res, err
	}
	name := fmt.Sprintf("%s-%s-%s", req.ItemID, c.now().UTC().Format("20060102T150405"), req.ManifestSHA[:8])
	dst := filepath.Join(c.p.Approved, name)
	work := filepath.Join(c.p.Work, name)
	if err := copyIn(filepath.Join(c.p.Inbox, req.ItemID), dst, s.item.Files, req.ManifestSHA); err != nil {
		c.log("run.copy_refused", map[string]any{"item": req.ItemID, "error": err.Error()})
		return res, err
	}
	if err := mkdirAll(work, 0o700); err != nil {
		return res, fmt.Errorf("control: %w", err)
	}
	spec := runner.Command(c.p.SystemRoot, dst, work, s.item.Header.Entry)
	if err := c.run.Start(req.ItemID, req.ManifestSHA, spec, runner.Options{OutputMayCopy: s.item.Header.OutputMayCopy}); err != nil {
		return res, err
	}
	c.mu.Lock()
	c.runBadges = append([]string{}, s.item.Badges...)
	c.last[req.ItemID] = Approved{Dir: dst, ManifestSHA: req.ManifestSHA, Files: s.item.Files, At: c.now().UTC()}
	err = c.saveLedger()
	c.mu.Unlock()
	if err != nil {
		// The run has started; the history file failed. Say so, never silently.
		c.log("ledger.error", map[string]any{"error": err.Error()})
		res.Done = "started (warning: could not save the approval history: " + err.Error() + ")"
		return res, nil
	}
	res.Done = "started"
	return res, nil
}

func (c *Control) saveLedger() error {
	b, err := marshal(c.last, "", "  ")
	if err != nil {
		return err
	}
	tmp := c.p.Ledger + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, c.p.Ledger)
}

// RunView is the run panel on the phone.
type RunView struct {
	runner.Run
	Running bool     `json:"running"`
	Badges  []string `json:"badges"` // shown next to Stop as well as on the card
}

// Run returns the current or last run with the badges of the item it ran.
func (c *Control) Run() RunView {
	r := c.run.Current()
	c.mu.Lock()
	defer c.mu.Unlock()
	return RunView{Run: r, Running: r.Running(), Badges: append([]string{}, c.runBadges...)}
}

// Keep appends one (already redacted) output line to the item's PC-only output
// file. A failure is logged once, not repeated for every line.
func (c *Control) Keep(item, line string) {
	f, err := os.OpenFile(filepath.Join(c.p.Output, item+".log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err == nil {
		_, err = f.WriteString(line + "\n")
		f.Close()
	}
	c.mu.Lock()
	first := err != nil && !c.keepErr
	c.keepErr = err != nil
	c.mu.Unlock()
	if first {
		c.log("output.keep_error", map[string]any{"item": item, "error": err.Error()})
	}
}
