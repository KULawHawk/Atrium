package web

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
)

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
	h := Handler(src{shot: []byte("png")}, config.Defaults(), wrap)
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
	if r := get(t, Handler(src{}, config.Defaults(), wrap), "GET", "/api/shot"); r.Code != 404 {
		t.Fatalf("no shot %d", r.Code)
	}
	// Watch-only: nothing accepts a state change.
	for _, p := range []string{"/", "/api/status", "/api/run"} {
		if r := get(t, h, "POST", p); r.Code != http.StatusMethodNotAllowed && r.Code != 404 {
			t.Errorf("POST %s got %d", p, r.Code)
		}
	}
	if r := get(t, h, "GET", "/other"); r.Code != 404 {
		t.Fatalf("unknown path %d", r.Code)
	}
}
