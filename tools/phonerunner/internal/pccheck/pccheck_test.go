package pccheck

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/gate"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

func TestLogIntact(t *testing.T) {
	dir := t.TempDir()
	st, _ := store.Open(dir)
	st.SetClock(func() time.Time { return time.Unix(0, 0) })
	_ = st.Append("a", nil)
	_ = st.Append("b", nil)
	st2, _ := store.Open(dir) // restart: sequence starts again at 1
	_ = st2.Append("c", nil)
	r := LogIntact(st.LogPath())
	if !r.Pass || !strings.Contains(r.Detail, "3 lines") || !strings.Contains(r.Detail, "1 restarts") || !strings.HasPrefix(r.Line(), "PASS T-11") {
		t.Fatal(r.Line())
	}
	p := filepath.Join(dir, "x.jsonl")
	cases := map[string]string{
		"":                               "empty",
		`{"seq":1,"at":"t","event":"e"}`: "torn",
		"{bad\n":                         "not a whole",
		`{"seq":1,"at":"t","event":"e"}` + "\n" + `{"seq":3,"at":"t","event":"e"}` + "\n": "jumps",
		strings.Repeat("x", 9<<20) + "\n":                                                 "reading log",
	}
	for body, want := range cases {
		os.WriteFile(p, []byte(body), 0o644)
		if r := LogIntact(p); r.Pass || !strings.Contains(r.Detail, want) || !strings.HasPrefix(r.Line(), "FAIL") {
			t.Errorf("%s: %s", want, r.Line())
		}
	}
	if r := LogIntact(filepath.Join(dir, "none")); r.Pass {
		t.Fatal("missing log passed")
	}
}

type who struct{ id gate.Identity }

func (w who) WhoIs(context.Context, string) (gate.Identity, error) { return w.id, nil }

func TestRefused(t *testing.T) {
	ctx := context.Background()
	ok := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("page")) })
	pc := gate.New(who{gate.Identity{NodeID: "nPC", Login: "j"}}, []string{"nPHONE"}, "j", func(string, map[string]any) {})
	srv := httptest.NewServer(pc.Middleware(ok))
	defer srv.Close()
	if r := Refused(ctx, srv.Client(), srv.URL); !r.Pass {
		t.Fatal(r.Line())
	}
	// The paired phone would get the page: as a T-06 result that is a FAIL.
	phone := gate.New(who{gate.Identity{NodeID: "nPHONE", Login: "j"}}, []string{"nPHONE"}, "j", func(string, map[string]any) {})
	srv2 := httptest.NewServer(phone.Middleware(ok))
	defer srv2.Close()
	if r := Refused(ctx, srv2.Client(), srv2.URL); r.Pass {
		t.Fatal("allowed page passed T-06")
	}
	leaky := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(403)
		w.Write([]byte("Not allowed. Try /api/status"))
	}))
	defer leaky.Close()
	if r := Refused(ctx, leaky.Client(), leaky.URL); r.Pass || !strings.Contains(r.Detail, "/api/") {
		t.Fatal(r.Line())
	}
	if r := Refused(ctx, http.DefaultClient, "http://127.0.0.1:1/"); r.Pass || !strings.Contains(r.Detail, "not reachable") {
		t.Fatal(r.Line())
	}
	if r := Refused(ctx, http.DefaultClient, "::bad"); r.Pass || !strings.Contains(r.Detail, "bad address") {
		t.Fatal(r.Line())
	}
}
