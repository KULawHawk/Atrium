package gate

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type fakeWho struct {
	id  Identity
	err error
}

func (f fakeWho) WhoIs(context.Context, string) (Identity, error) { return f.id, f.err }

func TestCheck(t *testing.T) {
	phone := Identity{NodeID: "nPHONE", NodeName: "pixel", Login: "jake@x"}
	cases := []struct {
		name    string
		who     fakeWho
		allowed []string
		wantErr string
	}{
		{"ok", fakeWho{id: phone}, []string{"nPHONE"}, ""},
		{"whois error", fakeWho{err: errors.New("boom")}, []string{"nPHONE"}, "identity unknown"},
		{"tagged", fakeWho{id: Identity{NodeID: "nPHONE", Login: "jake@x", Tagged: true}}, []string{"nPHONE"}, "tagged"},
		{"unpaired", fakeWho{id: phone}, nil, "no phone is paired"},
		{"other device (the PC itself)", fakeWho{id: Identity{NodeID: "nPC", Login: "jake@x"}}, []string{"nPHONE"}, "not the paired phone"},
		{"other login", fakeWho{id: Identity{NodeID: "nPHONE", Login: "eve@x"}}, []string{"nPHONE"}, "different Tailscale user"},
	}
	for _, c := range cases {
		g := New(c.who, c.allowed, "jake@x", func(string, map[string]any) {})
		_, err := g.Check(context.Background(), "100.1.2.3:5")
		if c.wantErr == "" && err != nil || c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
			t.Errorf("%s: got %v", c.name, err)
		}
	}
}

func TestMiddleware(t *testing.T) {
	var logged []string
	log := func(e string, f map[string]any) { logged = append(logged, e+":"+f["reason"].(string)) }
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id, ok := FromContext(r.Context())
		if !ok || id.NodeID != "nPHONE" {
			t.Error("identity missing in context")
		}
		w.WriteHeader(200)
	})

	g := New(fakeWho{id: Identity{NodeID: "nPHONE", Login: "jake@x"}}, []string{"nPHONE"}, "jake@x", log)
	rec := httptest.NewRecorder()
	g.Middleware(next).ServeHTTP(rec, httptest.NewRequest("GET", "/", nil))
	if rec.Code != 200 {
		t.Fatalf("allowed got %d", rec.Code)
	}

	// A forged header changes nothing: identity comes only from WhoIs.
	g = New(fakeWho{id: Identity{NodeID: "nPC", NodeName: "<jake340>", Login: "jake@x"}}, []string{"nPHONE"}, "jake@x", log)
	rec = httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/api/status", nil)
	req.Header.Set("Tailscale-User-Login", "jake@x")
	g.Middleware(next).ServeHTTP(rec, req)
	if rec.Code != 403 || !strings.Contains(rec.Body.String(), "&lt;jake340&gt;") || len(logged) != 1 {
		t.Fatalf("refused got %d %q %v", rec.Code, rec.Body.String(), logged)
	}
	if _, ok := FromContext(context.Background()); ok {
		t.Fatal("empty context has identity")
	}
}

func TestRefusalLogIsRateLimited(t *testing.T) {
	var lines []map[string]any
	log := func(_ string, f map[string]any) { lines = append(lines, f) }
	g := New(fakeWho{id: Identity{NodeID: "nPC", Login: "jake@x"}}, []string{"nPHONE"}, "jake@x", log)
	defer func() {
		if len(lines) == 0 || lines[0]["login"] != "j***@x" {
			t.Errorf("logged login not masked: %v", lines)
		}
	}()
	now := time.Date(2026, 11, 21, 3, 0, 0, 0, time.UTC)
	g.SetClock(func() time.Time { return now })
	h := g.Middleware(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	hit := func() {
		h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/", nil))
	}
	hit()
	hit()
	hit()
	if len(lines) != 1 {
		t.Fatalf("logged %d lines in one minute", len(lines))
	}
	now = now.Add(RefusalLogGap)
	hit()
	if len(lines) != 2 || lines[1]["skipped_since_last_line"] != 2 {
		t.Fatalf("second line %v", lines)
	}
	now = now.Add(RefusalLogGap)
	hit()
	if _, ok := lines[2]["skipped_since_last_line"]; ok {
		t.Fatal("stale skip count")
	}
}

func TestMaskLogin(t *testing.T) {
	for in, want := range map[string]string{"": "", "someone@example.com": "s***@example.com", "plain": "p***", "@x": "@***", "émile@x.fr": "é***@x.fr"} {
		if got := MaskLogin(in); got != want {
			t.Errorf("MaskLogin(%q) = %q, want %q", in, got, want)
		}
	}
}
