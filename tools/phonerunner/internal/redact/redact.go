// Package redact removes key-like text before anything leaves the PC store.
//
// Jake's standing rule: no key text anywhere an agent can read it. Every string the
// tool shows on the phone, writes to the log, or lets the PC lane copy to the share
// passes through Text first. The filter is deliberately greedy: a false blackout
// costs a few characters of readability, a missed key costs a leaked secret.
package redact

import (
	"math"
	"regexp"
	"strings"
)

// Mask replaces every redacted span.
const Mask = "[REDACTED]"

// known lists key shapes with a recognisable prefix. Order does not matter.
var known = []*regexp.Regexp{
	regexp.MustCompile(`sk-ant-[A-Za-z0-9_\-]{8,}`),              // Anthropic
	regexp.MustCompile(`sk-[A-Za-z0-9_\-]{16,}`),                 // OpenAI-style
	regexp.MustCompile(`rpa_[A-Za-z0-9]{16,}`),                   // RunPod
	regexp.MustCompile(`gh[pousr]_[A-Za-z0-9]{20,}`),             // GitHub classic tokens
	regexp.MustCompile(`github_pat_[A-Za-z0-9_]{20,}`),           // GitHub fine-grained
	regexp.MustCompile(`hf_[A-Za-z0-9]{20,}`),                    // Hugging Face
	regexp.MustCompile(`AKIA[0-9A-Z]{16}`),                       // AWS access key id
	regexp.MustCompile(`xox[abprs]-[A-Za-z0-9\-]{10,}`),          // Slack
	regexp.MustCompile(`tskey-[A-Za-z0-9\-]{10,}`),               // Tailscale auth keys
	regexp.MustCompile(`-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)`),
	regexp.MustCompile(`(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*\S+`),
}

// tokenRe finds candidate opaque strings for the entropy check.
var tokenRe = regexp.MustCompile(`[A-Za-z0-9_\-+/=]{32,}`)

// hexOnly matches pure lowercase hex. Exactly 40 (git commit) and 64 (sha256)
// characters are kept so file hashes stay readable on the approval card; any other
// length of hex is treated like any other opaque token.
var hexOnly = regexp.MustCompile(`^[0-9a-f]+$`)

// Result reports what Text did.
type Result struct {
	Text  string
	Count int
}

// Text returns s with every key-like span replaced by Mask.
func Text(s string) Result {
	count := 0
	for _, re := range known {
		s = re.ReplaceAllStringFunc(s, func(string) string { count++; return Mask })
	}
	s = tokenRe.ReplaceAllStringFunc(s, func(tok string) string {
		if keepToken(tok) {
			return tok
		}
		count++
		return Mask
	})
	return Result{Text: s, Count: count}
}

// Lines redacts each line and returns the total count.
func Lines(in []string) ([]string, int) {
	out := make([]string, len(in))
	total := 0
	for i, l := range in {
		r := Text(l)
		out[i] = r.Text
		total += r.Count
	}
	return out, total
}

func keepToken(tok string) bool {
	if hexOnly.MatchString(tok) && (len(tok) == 40 || len(tok) == 64) {
		return true
	}
	if strings.Trim(tok, "-_=+/") == "" {
		return true // a rule line such as "--------------------------------"
	}
	return entropy(tok) < 3.0
}

// entropy is the Shannon entropy in bits per character.
func entropy(s string) float64 {
	freq := map[rune]float64{}
	for _, r := range s {
		freq[r]++
	}
	n := float64(len([]rune(s)))
	h := 0.0
	for _, c := range freq {
		p := c / n
		h -= p * math.Log2(p)
	}
	return h
}
