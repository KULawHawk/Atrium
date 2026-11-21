package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDefaultsValid(t *testing.T) {
	c := Defaults()
	if err := c.Validate(); err != nil {
		t.Fatal(err)
	}
	if c.Paired() {
		t.Fatal("defaults must be unpaired")
	}
}

func TestParseAndPaired(t *testing.T) {
	c, err := Parse([]byte(`{"allowed_node_ids":["nABC"],"allowed_login":"jake@example.com",
	"watched_logs":[{"label":"pod","path":"C:\\x.log","lines":30}],
	"ntfy_topic":"abcdefghijklmnopqrstuvwxyz"}`))
	if err != nil {
		t.Fatal(err)
	}
	if !c.Paired() || c.CaptureShotSeconds != 10 || len(c.DenyRules) == 0 {
		t.Fatalf("unexpected %+v", c)
	}
	b, err := c.Marshal()
	if err != nil || !strings.Contains(string(b), "nABC") {
		t.Fatalf("marshal %v %s", err, b)
	}
}

func TestUnknownFieldRejected(t *testing.T) {
	if _, err := Parse([]byte(`{"surprise":1}`)); err == nil {
		t.Fatal("unknown field accepted")
	}
}

func TestValidateProblems(t *testing.T) {
	bad := `{"hostname":" ","allowed_node_ids":[""],"capture_text_seconds":0,"capture_shot_seconds":1,
	"heartbeat_seconds":1,"copy_ack_max_age_seconds":1,"ntfy_topic":"short","ntfy_server":"http://x",
	"watched_logs":[{"label":"","path":"","lines":0}],"deny_rules":[{"reason":""}]}`
	_, err := Parse([]byte(bad))
	if err == nil {
		t.Fatal("bad config accepted")
	}
	for _, want := range []string{"hostname", "empty entry", "allowed_login", "capture_text_seconds", "capture_shot_seconds",
		"heartbeat_seconds", "copy_ack", "24 random", "https", "label and path", "lines=0", "deny_rules[0]"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("missing %q in %v", want, err)
		}
	}
	if _, err := Parse([]byte(`{"deny_rules":[]}`)); err == nil || !strings.Contains(err.Error(), "deny_rules is empty") {
		t.Fatalf("empty deny rules: %v", err)
	}
}

func TestLoad(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "c.json")
	if err := os.WriteFile(p, []byte(`{}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(p); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(filepath.Join(dir, "missing.json")); err == nil {
		t.Fatal("missing file accepted")
	}
}
