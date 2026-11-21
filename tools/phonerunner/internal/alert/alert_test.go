package alert

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestSend(t *testing.T) {
	var body, click string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		body, click = string(b), r.Header.Get("Click")
		if r.URL.Path == "/bad" {
			w.WriteHeader(500)
		}
	}))
	defer srv.Close()
	n := New(srv.URL+"/", "topic", "https://phonerunner.example.ts.net/")
	clock := time.Unix(0, 0)
	n.now = func() time.Time { return clock }
	ctx := context.Background()

	if r, err := n.Send(ctx, NeedsYou); r != Sent || err != nil || body != string(NeedsYou) || click == "" {
		t.Fatalf("%v %v %q %q", r, err, body, click)
	}
	if r, _ := n.Send(ctx, NeedsYou); r != Skipped {
		t.Fatalf("not rate limited: %v", r)
	}
	clock = clock.Add(2 * MinGap)
	if r, _ := n.Send(ctx, NeedsYou); r != Sent {
		t.Fatalf("after gap: %v", r)
	}
	n.PageURL = ""
	if r, _ := n.Send(ctx, Done); r != Sent {
		t.Fatal("done not sent")
	}

	bad := New(srv.URL, "bad", "")
	if _, err := bad.Send(ctx, Locked); err == nil {
		t.Fatal("500 not reported")
	}
	if r, _ := New(srv.URL, "", "").Send(ctx, Started); r != Disabled {
		t.Fatal("no topic should be disabled")
	}
	if _, err := New("http://127.0.0.1:1", "t", "").Send(ctx, CopyLag); err == nil {
		t.Fatal("connection error not reported")
	}
	if _, err := New("http://bad host", "t", "").Send(ctx, CopyLag); err == nil {
		t.Fatal("bad url not reported")
	}
}
