// Package config loads PhoneRunner's settings file and refuses anything unsafe.
//
// The file lives in the SYSTEM-only store (C:\ProgramData\PhoneRunner\config.json)
// and is changed only at the desk with an elevated command. Loading fails closed:
// an unknown field, a missing phone, or an out-of-range interval stops the service
// instead of starting it with a guess.
package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
)

// WatchedLog is a text file whose last lines the phone page shows (for example the
// GPU pod driver's log). Lines are redacted before display.
type WatchedLog struct {
	Label string `json:"label"`
	Path  string `json:"path"`
	Lines int    `json:"lines"`
}

// DenyRule stops screen capture while a matching window is in front. Matching is
// case-insensitive; a rule matches when any TitleContains entry is a substring of
// the window title, or the program file name equals any ExeNames entry.
type DenyRule struct {
	Reason        string   `json:"reason"`
	TitleContains []string `json:"title_contains"`
	ExeNames      []string `json:"exe_names"`
}

// Config is the whole settings file.
type Config struct {
	Hostname             string       `json:"hostname"`
	AllowedNodeIDs       []string     `json:"allowed_node_ids"`
	AllowedLogin         string       `json:"allowed_login"`
	CaptureTextSeconds   int          `json:"capture_text_seconds"`
	CaptureShotSeconds   int          `json:"capture_shot_seconds"`
	HeartbeatSeconds     int          `json:"heartbeat_seconds"`
	CopyAckMaxAgeSeconds int          `json:"copy_ack_max_age_seconds"`
	NtfyServer           string       `json:"ntfy_server"`
	NtfyTopic            string       `json:"ntfy_topic"`
	WatchedLogs          []WatchedLog `json:"watched_logs"`
	DenyRules            []DenyRule   `json:"deny_rules"`
}

// Defaults returns the strictest-first starting settings. AllowedNodeIDs is empty:
// until Jake pairs his phone at the desk the page refuses every visitor.
func Defaults() Config {
	return Config{
		Hostname:             "phonerunner",
		CaptureTextSeconds:   5,
		CaptureShotSeconds:   10,
		HeartbeatSeconds:     30,
		CopyAckMaxAgeSeconds: 300,
		NtfyServer:           "https://ntfy.sh",
		DenyRules:            DefaultDenyRules(),
	}
}

// DefaultDenyRules covers key pages, Windows security screens and patient-mode
// windows (plan section 17). Patient-mode titles are a starting list to confirm on
// the PC; the rule only ever widens what is withheld.
func DefaultDenyRules() []DenyRule {
	return []DenyRule{
		{Reason: "Windows security screen", ExeNames: []string{"consent.exe", "credentialuibroker.exe", "logonui.exe", "lockapp.exe"}, TitleContains: []string{"windows security", "user account control"}},
		{Reason: "key or token page", TitleContains: []string{"api key", "api keys", "access token", "personal access tokens", "credential manager", "secrets", "ssh keys"}},
		{Reason: "password manager", TitleContains: []string{"password manager", "passwords"}, ExeNames: []string{"keepass.exe", "1password.exe", "bitwarden.exe"}},
		{Reason: "patient-mode window", TitleContains: []string{"patient"}},
	}
}

// Load reads and validates a config file. Unknown fields are an error.
func Load(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("config: %w", err)
	}
	return Parse(data)
}

// Parse decodes on top of Defaults and validates.
func Parse(data []byte) (Config, error) {
	c := Defaults()
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&c); err != nil {
		return Config{}, fmt.Errorf("config: %w", err)
	}
	if err := c.Validate(); err != nil {
		return Config{}, err
	}
	return c, nil
}

// Validate checks every field. It does not require a paired phone, because the
// service must start unpaired to show a visitor its own device ID for pairing.
func (c Config) Validate() error {
	var problems []string
	if strings.TrimSpace(c.Hostname) == "" {
		problems = append(problems, "hostname is empty")
	}
	for _, id := range c.AllowedNodeIDs {
		if strings.TrimSpace(id) == "" {
			problems = append(problems, "allowed_node_ids has an empty entry")
		}
	}
	if len(c.AllowedNodeIDs) > 0 && strings.TrimSpace(c.AllowedLogin) == "" {
		problems = append(problems, "allowed_login must be set when a phone is paired")
	}
	check := func(name string, v, lo, hi int) {
		if v < lo || v > hi {
			problems = append(problems, fmt.Sprintf("%s=%d is outside %d..%d", name, v, lo, hi))
		}
	}
	check("capture_text_seconds", c.CaptureTextSeconds, 1, 3600)
	check("capture_shot_seconds", c.CaptureShotSeconds, 2, 3600)
	check("heartbeat_seconds", c.HeartbeatSeconds, 5, 600)
	check("copy_ack_max_age_seconds", c.CopyAckMaxAgeSeconds, 60, 3600)
	if c.NtfyTopic != "" && len(c.NtfyTopic) < 24 {
		problems = append(problems, "ntfy_topic must be at least 24 random characters (it is a bearer secret)")
	}
	if c.NtfyTopic != "" && !strings.HasPrefix(c.NtfyServer, "https://") {
		problems = append(problems, "ntfy_server must be https")
	}
	for i, w := range c.WatchedLogs {
		if w.Label == "" || w.Path == "" {
			problems = append(problems, fmt.Sprintf("watched_logs[%d] needs label and path", i))
		}
		if w.Lines < 1 || w.Lines > 200 {
			problems = append(problems, fmt.Sprintf("watched_logs[%d].lines=%d is outside 1..200", i, w.Lines))
		}
	}
	if len(c.DenyRules) == 0 {
		problems = append(problems, "deny_rules is empty (capture would never pause on key or patient windows)")
	}
	for i, r := range c.DenyRules {
		if r.Reason == "" || (len(r.TitleContains) == 0 && len(r.ExeNames) == 0) {
			problems = append(problems, fmt.Sprintf("deny_rules[%d] needs a reason and at least one match", i))
		}
	}
	if len(problems) > 0 {
		return errors.New("config: " + strings.Join(problems, "; "))
	}
	return nil
}

// Paired reports whether any phone is allowed.
func (c Config) Paired() bool { return len(c.AllowedNodeIDs) > 0 }

// Marshal renders the config for writing back (pairing at the desk).
func (c Config) Marshal() ([]byte, error) {
	return json.MarshalIndent(c, "", "  ")
}
