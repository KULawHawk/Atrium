// Package alert sends short push notifications to Jake's phone through ntfy.
//
// The text is chosen from a fixed list (Kind), so no window title, file name, key
// or patient detail can ever ride along: the notification only says that the page
// needs a look, and carries the page link. The topic name is a bearer secret kept
// in the SYSTEM-only config. A Kind is sent at most once per MinGap.
package alert

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

// Kind is one of the fixed alert texts.
type Kind string

// The only alerts PhoneRunner sends.
const (
	NeedsYou Kind = "PhoneRunner needs you"
	Done     Kind = "PhoneRunner: a run finished"
	Locked   Kind = "PhoneRunner: the PC is locked"
	Started  Kind = "PhoneRunner started on the PC"
	CopyLag  Kind = "PhoneRunner: results are not being copied off the PC"
)

// MinGap is the shortest time between two alerts of the same Kind.
const MinGap = time.Minute

// Notifier posts to ntfy. A zero Topic disables sending (Send reports that).
type Notifier struct {
	Server  string
	Topic   string
	PageURL string
	Client  *http.Client
	now     func() time.Time
	mu      sync.Mutex
	last    map[Kind]time.Time
}

// New builds a Notifier.
func New(server, topic, pageURL string) *Notifier {
	return &Notifier{Server: strings.TrimRight(server, "/"), Topic: topic, PageURL: pageURL,
		Client: &http.Client{Timeout: 10 * time.Second}, now: time.Now, last: map[Kind]time.Time{}}
}

// Result says what Send did, so the caller can log it (no silent failure).
type Result string

// Send results.
const (
	Sent     Result = "sent"
	Disabled Result = "disabled (no ntfy topic set)"
	Skipped  Result = "skipped (same alert sent under a minute ago)"
)

// Send posts one alert.
func (n *Notifier) Send(ctx context.Context, k Kind) (Result, error) {
	if n.Topic == "" {
		return Disabled, nil
	}
	n.mu.Lock()
	if t, ok := n.last[k]; ok && n.now().Sub(t) < MinGap {
		n.mu.Unlock()
		return Skipped, nil
	}
	n.last[k] = n.now()
	n.mu.Unlock()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, n.Server+"/"+n.Topic, strings.NewReader(string(k)))
	if err != nil {
		return "", fmt.Errorf("alert: %w", err)
	}
	req.Header.Set("Title", "PhoneRunner")
	if n.PageURL != "" {
		req.Header.Set("Click", n.PageURL)
	}
	resp, err := n.Client.Do(req)
	if err != nil {
		return "", fmt.Errorf("alert: %w", err)
	}
	resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return "", fmt.Errorf("alert: ntfy answered %d", resp.StatusCode)
	}
	return Sent, nil
}
