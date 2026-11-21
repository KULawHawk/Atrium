package web

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-webauthn/webauthn/protocol"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/control"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/gate"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
)

type ctl struct {
	dev, item, action, file string
	err                     error
	finished                bool
}

func (c *ctl) Items() ([]control.Card, error) { return []control.Card{{Time: "5 min"}}, c.err }
func (c *ctl) File(id, rel string) (control.FileView, error) {
	c.item, c.file = id, rel
	return control.FileView{Path: rel}, c.err
}
func (c *ctl) Run() control.RunView { return control.RunView{Badges: []string{"b"}} }
func (c *ctl) BeginTap(dev, id, action string) (*protocol.CredentialAssertion, error) {
	c.dev, c.item, c.action = dev, id, action
	return &protocol.CredentialAssertion{}, c.err
}
func (c *ctl) FinishTap(dev string, _ *protocol.ParsedCredentialAssertionData) (control.Result, error) {
	c.dev, c.finished = dev, true
	return control.Result{Done: "started"}, c.err
}

type keys struct {
	dev string
	err error
}

func (k *keys) Count() int { return 1 }
func (k *keys) BeginRegistration(dev string) (*protocol.CredentialCreation, error) {
	k.dev = dev
	return &protocol.CredentialCreation{}, k.err
}
func (k *keys) FinishRegistration(dev string, _ *protocol.ParsedCredentialCreationData) (string, error) {
	k.dev = dev
	return "abcd1234", k.err
}

type who struct{}

func (who) WhoIs(context.Context, string) (gate.Identity, error) {
	return gate.Identity{NodeID: "phone-node", Login: "j@x"}, nil
}

func post(h http.Handler, path, body string, sameOrigin bool) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if sameOrigin {
		req.Header.Set("Sec-Fetch-Site", "same-origin")
	}
	h.ServeHTTP(rec, req)
	return rec
}

func errOf(r *httptest.ResponseRecorder) string {
	var m map[string]string
	json.Unmarshal(r.Body.Bytes(), &m)
	return m["error"]
}

// A minimal, well-formed assertion and attestation body, so the library's
// parser accepts them; the fakes stand in for the signature checks.
const assertionBody = `{"id":"AQ","rawId":"AQ","type":"public-key","response":{"clientDataJSON":"eyJ0eXBlIjoid2ViYXV0aG4uZ2V0IiwiY2hhbGxlbmdlIjoiQVEiLCJvcmlnaW4iOiJodHRwczovL3gifQ","authenticatorData":"SZYN5YgOjGh0NBcPZHZgW4_krrmihjLHmVzzuoMdl2MFAAAAAQ","signature":"AQ"}}`

func TestRunButtonRoutes(t *testing.T) {
	g := gate.New(who{}, []string{"phone-node"}, "j@x", func(string, map[string]any) {})
	c, k := &ctl{}, &keys{}
	h := Handler(src{}, config.Defaults(), c, k, g.Middleware)
	if r := get(t, h, "GET", "/api/items"); r.Code != 200 || !strings.Contains(r.Body.String(), "5 min") {
		t.Fatal(r.Body.String())
	}
	if r := get(t, h, "GET", "/api/items/pod-start/file?path=run.ps1"); r.Code != 200 || c.item != "pod-start" || c.file != "run.ps1" {
		t.Fatal(r.Code, c.item, c.file)
	}
	if r := get(t, h, "GET", "/api/run"); !strings.Contains(r.Body.String(), `"badges":["b"]`) {
		t.Fatal(r.Body.String())
	}
	if r := get(t, h, "GET", "/api/passkey"); !strings.Contains(r.Body.String(), "Always notify") {
		t.Fatal(r.Body.String())
	}
	// The device is the tailnet's, whatever the page sends.
	if r := post(h, "/api/tap/begin", `{"item":"pod-start","action":"run","device":"forged"}`, true); r.Code != 200 || c.dev != "phone-node" || c.action != "run" {
		t.Fatal(r.Code, r.Body.String(), c.dev)
	}
	if r := post(h, "/api/tap/begin", `{`, true); r.Code != 400 {
		t.Fatal(r.Code)
	}
	if r := post(h, "/api/tap/finish", assertionBody, true); r.Code != 200 || !c.finished {
		t.Fatal(r.Code, r.Body.String())
	}
	if r := post(h, "/api/tap/finish", `{}`, true); r.Code != 400 {
		t.Fatal(r.Code)
	}
	if r := post(h, "/api/passkey/begin", `{}`, true); r.Code != 200 || k.dev != "phone-node" {
		t.Fatal(r.Code)
	}
	if r := post(h, "/api/passkey/finish", `{}`, true); r.Code != 400 || !strings.Contains(errOf(r), "reopen") {
		t.Fatal(r.Code, errOf(r))
	}
	att := attestationBody(t)
	if r := post(h, "/api/passkey/finish", att, true); r.Code != 200 || !strings.Contains(r.Body.String(), "abcd1234") {
		t.Fatal(r.Code, r.Body.String())
	}
	k.err = errors.New("two passkeys arrived")
	if r := post(h, "/api/passkey/finish", att, true); r.Code != 400 || !strings.Contains(errOf(r), "reopen") {
		t.Fatal(r.Code, errOf(r))
	}
	// Cross-site or non-JSON posts are refused before anything runs.
	c.action = ""
	if r := post(h, "/api/tap/begin", `{"item":"x","action":"run"}`, false); r.Code != 400 || c.action != "" || !strings.Contains(errOf(r), "not a request from this page") {
		t.Fatal(r.Code, errOf(r))
	}
	// Refusals come back as errors.
	c.err = errors.New("the PC is locked")
	if r := get(t, h, "GET", "/api/items"); r.Code != 400 || errOf(r) != "the PC is locked" {
		t.Fatal(r.Code)
	}
	// No device identity (not through the gate): refused.
	bare := Handler(src{}, config.Defaults(), c, k, func(h http.Handler) http.Handler { return h })
	if r := post(bare, "/api/tap/begin", `{}`, true); r.Code != 400 || !strings.Contains(errOf(r), "did not name") {
		t.Fatal(r.Code)
	}
}

type src struct{ shot []byte }

func (s src) Refresh(context.Context) service.Status { return service.Status{Mode: "watch-only"} }
func (s src) LatestShot() []byte                     { return s.shot }

func get(t *testing.T, h http.Handler, method, path string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, path, nil))
	return rec
}

func TestRoutes(t *testing.T) {
	wrapped := 0
	wrap := func(h http.Handler) http.Handler { wrapped++; return h }
	h := Handler(src{shot: []byte("png")}, config.Defaults(), &ctl{}, &keys{}, wrap)
	if wrapped != 1 {
		t.Fatal("gate not applied")
	}
	if r := get(t, h, "GET", "/"); r.Code != 200 || !strings.Contains(r.Body.String(), "PhoneRunner") || r.Header().Get("Content-Security-Policy") == "" {
		t.Fatalf("page %d", r.Code)
	}
	if r := get(t, h, "GET", "/app.js"); r.Code != 200 || strings.Contains(r.Body.String(), "innerHTML =") {
		t.Fatalf("js %d", r.Code)
	}
	r := get(t, h, "GET", "/api/status")
	var st service.Status
	if json.Unmarshal(r.Body.Bytes(), &st) != nil || st.Mode != "watch-only" {
		t.Fatal(r.Body.String())
	}
	r = get(t, h, "GET", "/api/settings")
	var rows []Setting
	if json.Unmarshal(r.Body.Bytes(), &rows) != nil || len(rows) < 5 || rows[0].Info == "" {
		t.Fatal(r.Body.String())
	}
	if r := get(t, h, "GET", "/api/shot"); r.Code != 200 || r.Header().Get("Content-Type") != "image/png" {
		t.Fatalf("shot %d", r.Code)
	}
	if r := get(t, Handler(src{}, config.Defaults(), &ctl{}, &keys{}, wrap), "GET", "/api/shot"); r.Code != 404 {
		t.Fatalf("no shot %d", r.Code)
	}
	// Only the tap and passkey routes accept a POST.
	for _, p := range []string{"/", "/api/status", "/api/run", "/api/items"} {
		if r := get(t, h, "POST", p); r.Code != http.StatusMethodNotAllowed && r.Code != 404 {
			t.Errorf("POST %s got %d", p, r.Code)
		}
	}
	if r := get(t, h, "GET", "/other"); r.Code != 404 {
		t.Fatalf("unknown path %d", r.Code)
	}
}
