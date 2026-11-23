package tsprobe

import (
	"context"
	"crypto/x509"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func serve(t *testing.T) (*httptest.Server, func(ctx context.Context, network, addr string) (net.Conn, error)) {
	s := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	t.Cleanup(s.Close)
	addr := s.Listener.Addr().String()
	return s, func(ctx context.Context, network, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, network, addr)
	}
}

// A filter answering with a certificate this PC does not trust reads as blocked,
// with the filter's issuer named.
func TestUntrustedCertificateIsBlocked(t *testing.T) {
	_, dial := serve(t)
	r := Probe(context.Background(), "example.com", dial, x509.NewCertPool())
	if r.OK || !r.Blocked || r.Issuer == "" || !strings.Contains(r.Problem, "this network blocks Tailscale") {
		t.Fatalf("got %+v", r)
	}
}

// A trusted certificate for another name (a filter with a trusted root but its
// own block page) also reads as blocked.
func TestWrongNameIsBlocked(t *testing.T) {
	s, dial := serve(t)
	roots := x509.NewCertPool()
	roots.AddCert(s.Certificate())
	r := Probe(context.Background(), "controlplane.tailscale.com", dial, roots)
	if r.OK || !r.Blocked {
		t.Fatalf("got %+v", r)
	}
}

// A trusted certificate for the right name is OK (httptest's certificate is for example.com).
func TestTrustedIsOK(t *testing.T) {
	s, dial := serve(t)
	roots := x509.NewCertPool()
	roots.AddCert(s.Certificate())
	r := Probe(context.Background(), "example.com", dial, roots)
	if !r.OK || r.Blocked {
		t.Fatalf("got %+v", r)
	}
}

func TestUnreachable(t *testing.T) {
	dial := func(ctx context.Context, network, addr string) (net.Conn, error) {
		return nil, &net.OpError{Op: "dial", Err: net.UnknownNetworkError("refused")}
	}
	r := Probe(context.Background(), "", dial, nil)
	if r.OK || r.Blocked || !strings.Contains(r.Problem, "cannot reach controlplane.tailscale.com") {
		t.Fatalf("got %+v", r)
	}
}
