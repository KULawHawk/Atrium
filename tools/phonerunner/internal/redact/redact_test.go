package redact

import (
	"strings"
	"testing"
)

func TestKnownShapes(t *testing.T) {
	cases := []string{
		"sk-ant-api03-abcdefghijklmnop",
		"sk-abcdefghijklmnopqrstuv",
		"rpa_ABCDEFGHIJKLMNOPQRST",
		"ghp_abcdefghijklmnopqrstuvwxyz0123",
		"github_pat_11ABCDEFG0123456789_abcdefghijk",
		"hf_abcdefghijklmnopqrstuvwxyz",
		"AKIAABCDEFGHIJKLMNOP",
		"xoxb-1234567890-abcdef",
		"tskey-auth-kAbCdEf123",
		"-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
		"-----BEGIN PRIVATE KEY-----\nunterminated",
		"password: hunter2",
		"API_KEY=whatever",
		"Authorization: Bearer abc.def",
		"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl",
	}
	for _, c := range cases {
		r := Text("before " + c + " after")
		if strings.Contains(r.Text, c) || r.Count == 0 || !strings.Contains(r.Text, Mask) {
			t.Errorf("not redacted: %q -> %q", c, r.Text)
		}
	}
}

func TestOpaqueHighEntropyRedacted(t *testing.T) {
	tok := "Zx8Qp2Lm9Vb4Nc7Kd1Rf6Tg3Yh5Uj0IwEaSoDp"
	r := Text("value " + tok)
	if strings.Contains(r.Text, tok) || r.Count != 1 {
		t.Fatalf("got %q count %d", r.Text, r.Count)
	}
}

func TestKeptShapes(t *testing.T) {
	keep := []string{
		strings.Repeat("ab", 20),                                                         // low entropy 40 chars
		"0123456789abcdef0123456789abcdef01234567",                                       // git sha (40 hex)
		"sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",        // labelled sha256
		"file hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",    // labelled hash
		"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  results.json", // sha256sum line
		"--------------------------------------",
		"ordinary words only",
	}
	for _, k := range keep {
		r := Text(k)
		if r.Text != k || r.Count != 0 {
			t.Errorf("wrongly redacted %q -> %q", k, r.Text)
		}
	}
}

func TestOtherHexLengthRedacted(t *testing.T) {
	tok := "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08aa"
	if r := Text(tok); r.Count != 1 {
		t.Fatalf("66-char hex should be redacted, got %q", r.Text)
	}
}

func TestLines(t *testing.T) {
	out, n := Lines([]string{"ok", "token=abc", "ghp_abcdefghijklmnopqrstuvwxyz0123"})
	if n != 2 || out[0] != "ok" || strings.Contains(out[2], "ghp_") {
		t.Fatalf("got %v %d", out, n)
	}
}

func TestEntropy(t *testing.T) {
	if e := entropy("aaaa"); e != 0 {
		t.Fatalf("entropy aaaa = %v", e)
	}
	if e := entropy("ab"); e != 1 {
		t.Fatalf("entropy ab = %v", e)
	}
}

func TestUnlabelledSha256Redacted(t *testing.T) {
	h := "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	for _, s := range []string{h, "secret value " + h, h + " ", "x " + h + "  file"} {
		if r := Text(s); strings.Contains(r.Text, h) || r.Count != 1 {
			t.Errorf("unlabelled 64-hex kept: %q -> %q", s, r.Text)
		}
	}
}
