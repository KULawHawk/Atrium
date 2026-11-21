// Package gate lets a request through only when Tailscale itself says it came from
// Jake's paired phone.
//
// The identity comes from the tailnet (tsnet LocalClient.WhoIs on the connection's
// remote address), never from a request header: there is no localhost listener, so
// no program on the PC can present a forged identity (plan section 5, review
// finding 1). Requests from the PC's own tailnet node, tagged devices, or any other
// device are refused and logged.
package gate

import (
	"context"
	"errors"
	"fmt"
	"html"
	"net/http"
	"sync"
	"time"
)

// Identity is what the tailnet reports about the device behind a connection.
type Identity struct {
	NodeID   string // Tailscale stable node ID
	NodeName string
	Login    string
	Tagged   bool
}

// WhoIser resolves a connection's remote address to an Identity.
type WhoIser interface {
	WhoIs(ctx context.Context, remoteAddr string) (Identity, error)
}

// Logger records refusals. The service passes its append-only log.
type Logger func(event string, fields map[string]any)

// Gate checks identities against the paired phone.
type Gate struct {
	who     WhoIser
	allowed map[string]bool
	login   string
	log     Logger

	mu         sync.Mutex
	lastLogged map[string]time.Time
	suppressed map[string]int
	now        func() time.Time
}

// RefusalLogGap is the least time between two logged refusals of one device, so a
// device retrying in a loop cannot grow the log without bound. Skipped refusals are
// counted and reported on the next logged line.
const RefusalLogGap = time.Minute

// ErrNotPaired means no phone has been paired at the desk yet.
var ErrNotPaired = errors.New("no phone is paired yet")

// New builds a Gate. An empty allowed list refuses everyone.
func New(who WhoIser, allowedNodeIDs []string, allowedLogin string, log Logger) *Gate {
	m := map[string]bool{}
	for _, id := range allowedNodeIDs {
		m[id] = true
	}
	return &Gate{who: who, allowed: m, login: allowedLogin, log: log,
		lastLogged: map[string]time.Time{}, suppressed: map[string]int{}, now: time.Now}
}

// SetClock replaces the time source (tests).
func (g *Gate) SetClock(now func() time.Time) { g.now = now }

// logRefusal writes a refusal line at most once per RefusalLogGap per device.
func (g *Gate) logRefusal(fields map[string]any, key string) {
	g.mu.Lock()
	defer g.mu.Unlock()
	now := g.now()
	if last, ok := g.lastLogged[key]; ok && now.Sub(last) < RefusalLogGap {
		g.suppressed[key]++
		return
	}
	if n := g.suppressed[key]; n > 0 {
		fields["skipped_since_last_line"] = n
	}
	g.lastLogged[key] = now
	g.suppressed[key] = 0
	g.log("gate.refused", fields)
}

// Check returns the identity if allowed, or an error saying why not.
func (g *Gate) Check(ctx context.Context, remoteAddr string) (Identity, error) {
	id, err := g.who.WhoIs(ctx, remoteAddr)
	if err != nil {
		return Identity{}, fmt.Errorf("tailnet identity unknown: %w", err)
	}
	switch {
	case id.Tagged:
		return id, errors.New("tagged devices are never allowed")
	case len(g.allowed) == 0:
		return id, ErrNotPaired
	case !g.allowed[id.NodeID]:
		return id, errors.New("this device is not the paired phone")
	case id.Login != g.login:
		return id, errors.New("this device is signed in as a different Tailscale user")
	}
	return id, nil
}

type ctxKey struct{}

// FromContext returns the identity a request was allowed with.
func FromContext(ctx context.Context) (Identity, bool) {
	id, ok := ctx.Value(ctxKey{}).(Identity)
	return id, ok
}

// Middleware refuses every request that fails Check. The refusal page shows the
// visitor its own device name and ID so Jake can pair it at the desk; it reveals
// nothing about the PC.
func (g *Gate) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id, err := g.Check(r.Context(), r.RemoteAddr)
		if err != nil {
			g.logRefusal(map[string]any{"node_id": id.NodeID, "node_name": id.NodeName, "login": id.Login, "reason": err.Error(), "path": r.URL.Path}, id.NodeID)
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.Header().Set("Cache-Control", "no-store")
			w.WriteHeader(http.StatusForbidden)
			fmt.Fprintf(w, refusedPage, html.EscapeString(err.Error()), html.EscapeString(id.NodeName), html.EscapeString(id.NodeID))
			return
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), ctxKey{}, id)))
	})
}

const refusedPage = `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PhoneRunner</title><body style="font-family:system-ui;margin:16px">
<h1>Not allowed</h1><p>%s</p>
<p>This device: <b>%s</b><br>Device ID: <code>%s</code></p>
<p>To pair this phone, run the pairing step at the PC desk with this device ID.</p></body>`
