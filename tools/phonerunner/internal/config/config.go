// Package config loads PhoneRunner's settings file and refuses anything unsafe.
//
// The file lives in the store's SYSTEM+Administrators-only folder
// (C:\ProgramData\PhoneRunner\private\config.json) because it holds the ntfy topic,
// a bearer secret; it is changed only at the desk with an elevated command. The
// session part (running as Jake) never reads it: it gets a Session file with only
// the capture intervals and deny rules. Loading fails closed:
// an unknown field, a missing phone, or an out-of-range interval stops the service
// instead of starting it with a guess.
package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"
)

// WatchedLog is a text file whose last lines the phone page shows (for example the
// GPU pod driver's log). Lines are redacted before display.
type WatchedLog struct {
	Label string `json:"label"`
	Path  string `json:"path"`
	Lines int    `json:"lines"`
	// MayCopy lets this log's lines go into status.json, the status copy that leaves
	// the PC. Off by default: a log can carry patient data the key filter cannot see,
	// so its lines show on the phone only unless Jake turns this on for that log.
	MayCopy bool `json:"may_copy"`
}

// DenyRule stops screen capture, and withholds the window's title and program
// name, while a matching window is in front. Matching is case-insensitive; a rule
// matches when any TitleContains entry is a substring of the window title, any
// TitleRegex matches the title, or the program file name equals any ExeNames entry.
// Rules cover the FRONT window only; other windows on screen are not checked.
type DenyRule struct {
	Reason        string   `json:"reason"`
	TitleContains []string `json:"title_contains"`
	TitleRegex    []string `json:"title_regex,omitempty"`
	ExeNames      []string `json:"exe_names"`
}

// Config is the whole settings file.
type Config struct {
	Hostname             string       `json:"hostname"`
	AllowedNodeIDs       []string     `json:"allowed_node_ids"`
	AllowedLogin         string       `json:"allowed_login"`
	CaptureTextSeconds   int          `json:"capture_text_seconds"`
	CaptureShotSeconds   int          `json:"capture_shot_seconds"`
	ScreenTextSeconds    int          `json:"screen_text_seconds"` // 0 = off (default until PC test T-10 passes)
	HeartbeatSeconds     int          `json:"heartbeat_seconds"`
	CopyAckMaxAgeSeconds int          `json:"copy_ack_max_age_seconds"`
	NtfyServer           string       `json:"ntfy_server"`
	NtfyTopic            string       `json:"ntfy_topic"`
	NtfyClickLink        bool         `json:"ntfy_click_link"` // off: the page address is not sent to ntfy.sh
	WatchedLogs          []WatchedLog `json:"watched_logs"`
	DenyRules            []DenyRule   `json:"deny_rules"`
	// RunButton turns on the phone's Run and Stop buttons. Off by default; the
	// desk command that turns it on first re-checks "Always notify" (T-01C).
	RunButton bool `json:"run_button"`
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
		{Reason: "patient-mode window", TitleContains: []string{"patient", "date of birth", "medical record"},
			TitleRegex: []string{
				`(?i)(^|[^a-z])(dob|mrn)([^a-z]|$)`, // whole word only ("Adobe" must not match)
				`(^|[^0-9])(19|20)[0-9]{2}[-_./](0[1-9]|1[0-2])[-_./](0[1-9]|[12][0-9]|3[01])([^0-9]|$)`, // 1980-02-03
				`(^|[^0-9])(0?[1-9]|1[0-2])[-/](0?[1-9]|[12][0-9]|3[01])[-/](19|20)[0-9]{2}([^0-9]|$)`,   // 2/3/1980
			}},
	}
}

// Session is the part of the settings the session process (running as Jake) gets.
// It holds no secret, so it may live in a Jake-readable file.
type Session struct {
	CaptureTextSeconds int        `json:"capture_text_seconds"`
	CaptureShotSeconds int        `json:"capture_shot_seconds"`
	ScreenTextSeconds  int        `json:"screen_text_seconds"`
	DenyRules          []DenyRule `json:"deny_rules"`
}

// SessionSettings returns what the session process needs and nothing else.
func (c Config) SessionSettings() Session {
	return Session{CaptureTextSeconds: c.CaptureTextSeconds, CaptureShotSeconds: c.CaptureShotSeconds, ScreenTextSeconds: c.ScreenTextSeconds, DenyRules: c.DenyRules}
}

// LoadSession reads and validates a session settings file. Unknown fields (for
// example a topic copied in by mistake) are an error.
func LoadSession(path string) (Session, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Session{}, fmt.Errorf("config: %w", err)
	}
	var s Session
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s); err != nil {
		return Session{}, fmt.Errorf("config: %w", err)
	}
	c := Defaults()
	c.CaptureTextSeconds, c.CaptureShotSeconds, c.ScreenTextSeconds, c.DenyRules = s.CaptureTextSeconds, s.CaptureShotSeconds, s.ScreenTextSeconds, s.DenyRules
	if err := c.Validate(); err != nil {
		return Session{}, err
	}
	return s, nil
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
	if c.ScreenTextSeconds != 0 {
		check("screen_text_seconds", c.ScreenTextSeconds, 2, 3600)
	}
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
		if r.Reason == "" || (len(r.TitleContains) == 0 && len(r.ExeNames) == 0 && len(r.TitleRegex) == 0) {
			problems = append(problems, fmt.Sprintf("deny_rules[%d] needs a reason and at least one match", i))
		}
		for _, re := range r.TitleRegex {
			if _, err := regexp.Compile(re); err != nil {
				problems = append(problems, fmt.Sprintf("deny_rules[%d] title_regex %q does not compile", i, re))
			}
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
