package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/store"
)

func TestRun(t *testing.T) {
	var b bytes.Buffer
	call := func(args ...string) (int, string) {
		b.Reset()
		return run(args, &b, http.DefaultClient), b.String()
	}
	if rc, _ := call(); rc != 2 {
		t.Fatal("no args")
	}
	if rc, _ := call("log", "--bogus"); rc != 2 {
		t.Fatal("bad flag")
	}
	if rc, _ := call("refused"); rc != 2 {
		t.Fatal("no url")
	}
	dir := t.TempDir()
	st, _ := store.Open(filepath.Join(dir, "s"))
	if rc, out := call("log", "--store", st.Root()); rc != 1 || !strings.HasPrefix(out, "FAIL T-11") {
		t.Fatal(out)
	}
	_ = st.Append("a", nil)
	if rc, out := call("log", "--store", st.Root()); rc != 0 || !strings.HasPrefix(out, "PASS T-11") {
		t.Fatal(out)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(403)
		w.Write([]byte("Not allowed"))
	}))
	defer srv.Close()
	if rc, out := call("refused", "--url", srv.URL); rc != 0 || !strings.HasPrefix(out, "PASS T-06") {
		t.Fatal(out)
	}
}
