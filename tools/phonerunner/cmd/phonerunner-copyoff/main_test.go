package main

import (
	"bytes"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

func TestRun(t *testing.T) {
	now := func() time.Time { return time.Date(2026, 11, 21, 3, 0, 0, 0, time.UTC) }
	dir := t.TempDir()
	st, _ := store.Open(filepath.Join(dir, "store"))
	_ = st.Append("a", nil)
	outbox := filepath.Join(dir, "out")
	var b bytes.Buffer
	call := func(args ...string) (int, string) {
		b.Reset()
		rc := run(args, &b, now)
		return rc, b.String()
	}
	if rc, _ := call(); rc != 2 {
		t.Fatal("no args")
	}
	if rc, _ := call("stage", "--bogus"); rc != 2 {
		t.Fatal("bad flag")
	}
	if rc, _ := call("stage"); rc != 2 {
		t.Fatal("no outbox")
	}
	rc, out := call("stage", "--store", st.Root(), "--outbox", outbox)
	if rc != 0 || !strings.HasPrefix(out, "PASS staged batch 1") {
		t.Fatalf("%d %s", rc, out)
	}
	sha := regexp.MustCompile(`sha256 ([0-9a-f]{64})`).FindStringSubmatch(out)[1]
	if rc, out := call("stage", "--store", st.Root(), "--outbox", outbox); rc != 0 || !strings.Contains(out, "already staged") {
		t.Fatalf("%d %s", rc, out)
	}
	if rc, out := call("ack", "--store", st.Root(), "--outbox", outbox, "--manifest", "x"); rc != 1 || !strings.HasPrefix(out, "FAIL") {
		t.Fatalf("%d %s", rc, out)
	}
	if rc, out := call("ack", "--store", st.Root(), "--outbox", outbox, "--manifest", sha); rc != 0 || !strings.HasPrefix(out, "PASS ack written") {
		t.Fatalf("%d %s", rc, out)
	}
	if rc, out := call("ack", "--store", st.Root(), "--outbox", outbox, "--manifest", sha); rc != 0 || !strings.Contains(out, "refreshed") {
		t.Fatalf("%d %s", rc, out)
	}
	// Stage failure, and the split note for an oversized file.
	if rc, _ := call("stage", "--store", st.Root(), "--outbox", filepath.Join(dir, "out", "MISSING", "x", "\x00")); rc != 1 {
		t.Fatal("stage failure")
	}
	big := strings.Repeat(`{"x":"`+strings.Repeat("a", 1000)+`"}`+"\n", 11000)
	_ = st.WriteJSON("status.json", big)
	if rc, out := call("stage", "--store", st.Root(), "--outbox", outbox); rc != 0 || !strings.Contains(out, "NOTE status.json") {
		t.Fatalf("%d %s", rc, out)
	}
}
