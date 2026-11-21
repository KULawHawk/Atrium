package control

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-webauthn/webauthn/protocol"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/approve"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/inbox"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/runner"
)

// fakeAp approves whatever was begun last, after calling the manifest check
// the real approver makes.
type fakeAp struct {
	last     approve.Request
	beginErr error
	finErr   error
	checked  string
}

func (f *fakeAp) Begin(r approve.Request) (*protocol.CredentialAssertion, error) {
	if f.beginErr != nil {
		return nil, f.beginErr
	}
	f.last = r
	return &protocol.CredentialAssertion{}, nil
}

func (f *fakeAp) Finish(dev string, _ *protocol.ParsedCredentialAssertionData, m func(string) (string, error)) (approve.Request, error) {
	if f.finErr != nil {
		return approve.Request{}, f.finErr
	}
	sha, err := m(f.last.ItemID)
	if err != nil {
		return approve.Request{}, err
	}
	f.checked = sha
	if sha != f.last.ManifestSHA {
		return approve.Request{}, approve.ErrManifestChange
	}
	return f.last, nil
}

type fakeRun struct {
	cur      runner.Run
	spec     runner.Spec
	opts     runner.Options
	startErr error
	stopErr  error
	stopped  bool
}

func (f *fakeRun) Start(id, sha string, s runner.Spec, o runner.Options) error {
	if f.startErr != nil {
		return f.startErr
	}
	f.cur = runner.Run{ItemID: id, ManifestSHA: sha, Started: time.Now()}
	f.spec, f.opts = s, o
	return nil
}
func (f *fakeRun) Stop() error         { f.stopped = true; return f.stopErr }
func (f *fakeRun) Current() runner.Run { return f.cur }

type logs struct {
	mu sync.Mutex
	ev []string
}

func (l *logs) log(e string, _ map[string]any) { l.mu.Lock(); l.ev = append(l.ev, e); l.mu.Unlock() }
func (l *logs) has(e string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	for _, x := range l.ev {
		if x == e {
			return true
		}
	}
	return false
}

const header = `{"title":"Pod start","claimed_by":"PC lane","entry":"run.ps1","estimate_time":"5 min","estimate_cost":"$0","output_may_copy":true}`

type rig struct {
	c   *Control
	ap  *fakeAp
	run *fakeRun
	l   *logs
	p   Paths
	rdy error
}

func newRig(t *testing.T) *rig {
	t.Helper()
	root := t.TempDir()
	p := Paths{Inbox: filepath.Join(root, "inbox"), Approved: filepath.Join(root, "approved"), Work: filepath.Join(root, "work"),
		Output: filepath.Join(root, "output"), Ledger: filepath.Join(root, "ledger.json"), SystemRoot: `C:\Windows`}
	for _, d := range []string{p.Inbox, p.Approved, p.Work, p.Output} {
		os.MkdirAll(d, 0o700)
	}
	r := &rig{ap: &fakeAp{}, run: &fakeRun{}, l: &logs{}, p: p}
	t0 := time.Now()
	tick := func() time.Time { t0 = t0.Add(time.Second); return t0 } // each copy gets its own folder name
	c, err := New(p, r.ap, r.run, func() error { return r.rdy }, r.l.log, tick)
	if err != nil {
		t.Fatal(err)
	}
	r.c = c
	return r
}

func (r *rig) stage(t *testing.T, id string, files map[string]string) {
	t.Helper()
	for rel, body := range files {
		p := filepath.Join(r.p.Inbox, id, filepath.FromSlash(rel))
		os.MkdirAll(filepath.Dir(p), 0o700)
		if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestRunTapEndToEnd(t *testing.T) {
	r := newRig(t)
	r.stage(t, "pod-start", map[string]string{"item.json": header, "run.ps1": "Write-Output hi\nschtasks /create\n"})
	cards, err := r.c.Items()
	if err != nil || len(cards) != 1 || !cards[0].FirstTime || cards[0].Time != "5 min" || len(cards[0].Changes) != 2 {
		t.Fatalf("%v %+v", err, cards)
	}
	if _, err := r.c.BeginTap("phone", "pod-start", "run"); err != nil {
		t.Fatal(err)
	}
	if r.ap.last.Action != "run" || r.ap.last.DeviceID != "phone" || r.ap.last.ManifestSHA != cards[0].ManifestSHA {
		t.Fatalf("%+v", r.ap.last)
	}
	res, err := r.c.FinishTap("phone", nil)
	if err != nil || res.Done != "started" {
		t.Fatal(res, err)
	}
	// The fixed command runs the protected copy, not the inbox.
	if !strings.HasPrefix(r.run.spec.Dir, r.p.Approved) || !strings.HasSuffix(r.run.spec.Args[5], "run.ps1") || !r.run.opts.OutputMayCopy {
		t.Fatalf("%+v %+v", r.run.spec, r.run.opts)
	}
	if b, err := os.ReadFile(filepath.Join(r.run.spec.Dir, "run.ps1")); err != nil || !strings.HasPrefix(string(b), "Write-Output") {
		t.Fatal(err)
	}
	if !strings.Contains(strings.Join(r.run.spec.Env, ";"), "TEMP="+r.p.Work) {
		t.Fatal(r.run.spec.Env)
	}
	if v := r.c.Run(); !v.Running || len(v.Badges) == 0 || !strings.Contains(strings.Join(v.Badges, ","), "Stop cannot end") {
		t.Fatalf("%+v", v)
	}
	if !r.l.has("tap.approved") {
		t.Fatal("approval not logged")
	}
	// A second Run while one is going is refused before any challenge.
	if _, err := r.c.BeginTap("phone", "pod-start", "run"); !errors.Is(err, runner.ErrBusy) {
		t.Fatal(err)
	}
	// The ledger survives a restart and changes are shown against it.
	r.run.cur = runner.Run{}
	r.stage(t, "pod-start", map[string]string{"run.ps1": "Write-Output bye\n"})
	c2, err := New(r.p, r.ap, r.run, func() error { return nil }, r.l.log, time.Now)
	if err != nil {
		t.Fatal(err)
	}
	cards, _ = c2.Items()
	if cards[0].FirstTime || len(cards[0].Changes) != 1 || cards[0].Changes[0].What != "changed" || cards[0].LastApproved.IsZero() {
		t.Fatalf("%+v", cards[0])
	}
	v, err := c2.File("pod-start", "run.ps1")
	if err != nil || !v.Previous || strings.Join(v.Diff, "|") != "- Write-Output hi|- schtasks /create|+ Write-Output bye" {
		t.Fatal(v, err)
	}
}

func TestStopTap(t *testing.T) {
	r := newRig(t)
	if _, err := r.c.BeginTap("phone", "x", "stop"); !errors.Is(err, runner.ErrNotRunning) {
		t.Fatal(err)
	}
	r.run.cur = runner.Run{ItemID: "x", ManifestSHA: "runsha", Started: time.Now()}
	if _, err := r.c.BeginTap("phone", "y", "stop"); !errors.Is(err, ErrNotThisItem) {
		t.Fatal(err)
	}
	// Stop is bound to the running manifest even though the inbox has no item x.
	if _, err := r.c.BeginTap("phone", "x", "stop"); err != nil || r.ap.last.ManifestSHA != "runsha" {
		t.Fatal(err, r.ap.last)
	}
	res, err := r.c.FinishTap("phone", nil)
	if err != nil || res.Done != "stopped" || !r.run.stopped {
		t.Fatal(res, err)
	}
	r.run.stopErr = runner.ErrAlreadyEnded
	r.c.BeginTap("phone", "x", "stop")
	if _, err := r.c.FinishTap("phone", nil); !errors.Is(err, runner.ErrAlreadyEnded) {
		t.Fatal(err)
	}
}

func TestRefusals(t *testing.T) {
	r := newRig(t)
	r.stage(t, "bad", map[string]string{"item.json": `{"title":"x"}`})
	r.stage(t, "good", map[string]string{"item.json": header, "run.ps1": "ok"})
	for _, id := range []string{"", "..", "a/b", `a\b`} {
		if _, err := r.c.BeginTap("phone", id, "run"); !errors.Is(err, ErrBadID) {
			t.Errorf("%q: %v", id, err)
		}
		if _, err := r.c.File(id, "run.ps1"); !errors.Is(err, ErrBadID) {
			t.Errorf("%q: %v", id, err)
		}
	}
	if _, err := r.c.File("good", "../x"); !errors.Is(err, inbox.ErrBadPath) {
		t.Fatal(err)
	}
	if _, err := r.c.File("good", "nope.ps1"); err == nil {
		t.Fatal("missing file must fail")
	}
	if _, err := r.c.BeginTap("phone", "good", "resume"); !errors.Is(err, ErrAction) {
		t.Fatal(err)
	}
	if _, err := r.c.BeginTap("phone", "bad", "run"); !errors.Is(err, ErrNotRunnable) {
		t.Fatal(err)
	}
	if _, err := r.c.BeginTap("phone", "missing", "run"); err == nil {
		t.Fatal("missing item must fail")
	}
	r.rdy = errors.New("the PC is locked")
	if _, err := r.c.BeginTap("phone", "good", "run"); err == nil || err.Error() != "the PC is locked" {
		t.Fatal(err)
	}
	r.rdy = nil
	r.ap.beginErr = approve.ErrNoPasskey
	if _, err := r.c.BeginTap("phone", "good", "run"); !errors.Is(err, approve.ErrNoPasskey) {
		t.Fatal(err)
	}
	r.ap.beginErr = nil
	// Locked between tap and approval: refused after the signature too.
	r.c.BeginTap("phone", "good", "run")
	r.rdy = errors.New("locked now")
	if _, err := r.c.FinishTap("phone", nil); err == nil || err.Error() != "locked now" {
		t.Fatal(err)
	}
	r.rdy = nil
	// The approver refuses: logged, nothing runs.
	r.ap.finErr = approve.ErrWrongDevice
	if _, err := r.c.FinishTap("phone", nil); !errors.Is(err, approve.ErrWrongDevice) || !r.l.has("tap.refused") {
		t.Fatal(err)
	}
	r.ap.finErr = nil
	// No snapshot (service restarted between Begin and Finish).
	r.ap.last = approve.Request{ItemID: "good", ManifestSHA: r.ap.checked, Action: "run"}
	r.c.snaps = map[string]snap{}
	if _, err := r.c.FinishTap("phone", nil); !errors.Is(err, ErrNoSnapshot) {
		t.Fatal(err)
	}
	// The manifest check reads the inbox; an unreadable item fails it.
	r.ap.last.ItemID = "gone"
	if _, err := r.c.FinishTap("phone", nil); err == nil {
		t.Fatal("unreadable item must fail the manifest check")
	}
	if r.run.cur.Running() {
		t.Fatal("nothing may have started")
	}
}

func TestFileChangedAfterTap(t *testing.T) {
	r := newRig(t)
	r.stage(t, "good", map[string]string{"item.json": header, "run.ps1": "ok"})
	r.c.BeginTap("phone", "good", "run")
	// Changed after the tap: the approver's manifest re-check refuses.
	r.stage(t, "good", map[string]string{"run.ps1": "evil"})
	if _, err := r.c.FinishTap("phone", nil); !errors.Is(err, approve.ErrManifestChange) {
		t.Fatal(err)
	}
	// Changed between the approver's check and the copy: the copy refuses.
	r.stage(t, "good", map[string]string{"run.ps1": "ok"})
	r.c.BeginTap("phone", "good", "run")
	copyIn = func(src, dst string, f []inbox.File, sha string) error { return inbox.ErrCopyMismatch }
	defer func() { copyIn = inbox.CopyApproved }()
	if _, err := r.c.FinishTap("phone", nil); !errors.Is(err, inbox.ErrCopyMismatch) || !r.l.has("run.copy_refused") || r.run.cur.Running() {
		t.Fatal(err)
	}
}

func TestStartAndDiskFailures(t *testing.T) {
	r := newRig(t)
	r.stage(t, "good", map[string]string{"item.json": header, "run.ps1": "ok"})
	r.c.BeginTap("phone", "good", "run")
	mkdirAll = func(string, os.FileMode) error { return errors.New("disk full") }
	if _, err := r.c.FinishTap("phone", nil); err == nil || !strings.Contains(err.Error(), "disk full") {
		t.Fatal(err)
	}
	mkdirAll = os.MkdirAll
	r.c.BeginTap("phone", "good", "run")
	r.run.startErr = errors.New("no session")
	if _, err := r.c.FinishTap("phone", nil); err == nil || err.Error() != "no session" {
		t.Fatal(err)
	}
	r.run.startErr = nil
	// The run starts but the history cannot be saved: said, not silent.
	r.c.BeginTap("phone", "good", "run")
	marshal = func(any, string, string) ([]byte, error) { return nil, errors.New("no json") }
	res, err := r.c.FinishTap("phone", nil)
	marshal = json.MarshalIndent
	if err != nil || !strings.Contains(res.Done, "could not save") || !r.l.has("ledger.error") {
		t.Fatal(res, err)
	}
	// Ledger write failure (folder in the way of the temp file).
	r.run.cur = runner.Run{}
	os.MkdirAll(r.p.Ledger+".tmp", 0o700)
	r.c.BeginTap("phone", "good", "run")
	if res, _ := r.c.FinishTap("phone", nil); !strings.Contains(res.Done, "could not save") {
		t.Fatal(res)
	}
}

func TestLedgerAndInboxErrors(t *testing.T) {
	r := newRig(t)
	os.WriteFile(r.p.Ledger, []byte("{"), 0o600)
	if _, err := New(r.p, r.ap, r.run, nil, r.l.log, time.Now); err == nil || !strings.Contains(err.Error(), "damaged") {
		t.Fatal(err)
	}
	os.Remove(r.p.Ledger)
	os.MkdirAll(r.p.Ledger, 0o700) // unreadable as a file
	if _, err := New(r.p, r.ap, r.run, nil, r.l.log, time.Now); err == nil {
		t.Fatal("unreadable ledger must fail")
	}
	r.c.p.Inbox = filepath.Join(r.p.Inbox, "missing")
	if _, err := r.c.Items(); err == nil {
		t.Fatal("missing inbox must fail")
	}
}

func TestSnapshotsExpire(t *testing.T) {
	r := newRig(t)
	r.stage(t, "good", map[string]string{"item.json": header, "run.ps1": "ok"})
	now := time.Now()
	r.c.now = func() time.Time { return now }
	r.c.BeginTap("phone", "good", "run")
	now = now.Add(approve.TTL + time.Second)
	r.stage(t, "good", map[string]string{"run.ps1": "ok2"})
	r.c.BeginTap("phone", "good", "run")
	if len(r.c.snaps) != 1 {
		t.Fatal("old snapshot must be swept", len(r.c.snaps))
	}
}

func TestFileView(t *testing.T) {
	r := newRig(t)
	key := "sk-ant-api03-" + strings.Repeat("Q", 90)
	r.stage(t, "good", map[string]string{"item.json": header, "run.ps1": "$k='" + key + "'", "big.txt": strings.Repeat("a", MaxView+5)})
	v, err := r.c.File("good", "run.ps1")
	if err != nil || strings.Contains(v.Text, "QQQQ") || v.Masked == 0 || v.Previous || len(v.Diff) != 0 {
		t.Fatal(v, err)
	}
	v, _ = r.c.File("good", "big.txt")
	if !strings.HasSuffix(v.Text, "longer than shown here)") {
		t.Fatal(len(v.Text))
	}
	// A previous approval whose copy lacks this file: no diff, no error.
	r.c.last["good"] = Approved{Dir: filepath.Join(r.p.Approved, "none")}
	if v, err := r.c.File("good", "run.ps1"); err != nil || v.Previous {
		t.Fatal(v, err)
	}
}

func TestFileViewRefusesLinks(t *testing.T) {
	r := newRig(t)
	r.stage(t, "good", map[string]string{"item.json": header, "run.ps1": "ok"})
	secret := filepath.Join(filepath.Dir(r.p.Inbox), "private.txt")
	os.WriteFile(secret, []byte("topic-secret"), 0o600)
	os.Symlink(secret, filepath.Join(r.p.Inbox, "good", "leak.txt"))
	if _, err := r.c.File("good", "leak.txt"); !errors.Is(err, inbox.ErrOutside) {
		t.Fatal(err)
	}
}

func TestKeep(t *testing.T) {
	r := newRig(t)
	r.c.Keep("good", "line 1")
	r.c.Keep("good", "line 2")
	if b, _ := os.ReadFile(filepath.Join(r.p.Output, "good.log")); string(b) != "line 1\nline 2\n" {
		t.Fatal(string(b))
	}
	r.c.p.Output = filepath.Join(r.p.Output, "missing")
	r.c.Keep("good", "x")
	r.c.Keep("good", "y")
	n := 0
	for _, e := range r.l.ev {
		if e == "output.keep_error" {
			n++
		}
	}
	if n != 1 {
		t.Fatal("a keep failure is logged once, not per line: ", n)
	}
}
