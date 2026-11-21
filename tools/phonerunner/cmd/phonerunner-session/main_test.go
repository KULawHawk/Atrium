package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/capture"
)

type fake struct{}

func (fake) Foreground() (capture.Window, error) { return capture.Window{Title: "t"}, nil }
func (fake) Locked() (bool, error)               { return false, nil }
func (fake) Screenshot() ([]byte, error)         { return []byte("p"), nil }

type failW struct{}

func (failW) Write([]byte) (int, error) { return 0, os.ErrClosed }

func TestRun(t *testing.T) {
	p := filepath.Join(t.TempDir(), "c.json")
	os.WriteFile(p, []byte(`{"capture_text_seconds":1,"capture_shot_seconds":2}`), 0o600)
	var out, errb bytes.Buffer
	if rc := run([]string{"--config", p, "--for", "1100ms"}, &out, &errb, fake{}); rc != 0 || !strings.Contains(out.String(), `"type":"window"`) {
		t.Fatalf("rc %d out %q err %q", rc, out.String(), errb.String())
	}
	if rc := run([]string{"--config", p, "--for", "3s"}, failW{}, &errb, fake{}); rc != 1 {
		t.Fatalf("pipe failure rc %d", rc)
	}
	if rc := run([]string{"--config", p + ".none"}, &out, &errb, fake{}); rc != 1 {
		t.Fatalf("missing config rc %d", rc)
	}
	if rc := run([]string{"--bogus"}, &out, &errb, fake{}); rc != 2 {
		t.Fatalf("bad flag rc %d", rc)
	}
}
