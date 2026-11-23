// Package tsprobe tells a network that blocks Tailscale apart from a missing
// sign-in. It only looks: one TLS handshake to Tailscale's coordination server
// with the system's own trust roots, then it hangs up. It never retries
// elsewhere, never changes DNS and never trusts a certificate the system does
// not trust (no bypass). Its answer is for the log and the desk script only.
package tsprobe

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net"
	"strings"
	"time"
)

// Host is Tailscale's coordination server, the first thing a sign-in needs.
const Host = "controlplane.tailscale.com"

// Result is what one look found.
type Result struct {
	OK      bool   // a genuine certificate for Host, trusted by this PC
	Blocked bool   // something else answered for Host (a network filter)
	Addrs   string // what Host resolved to, comma separated
	Issuer  string // issuer of the certificate that answered, when one did
	Problem string // plain words for the log and the desk
}

// Probe looks once. dial and roots are for tests; nil means the real network
// and the system roots.
func Probe(ctx context.Context, host string, dial func(ctx context.Context, network, addr string) (net.Conn, error), roots *x509.CertPool) Result {
	if host == "" {
		host = Host
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	var r Result
	if dial == nil {
		if ips, err := net.DefaultResolver.LookupHost(ctx, host); err == nil {
			r.Addrs = strings.Join(ips, ",")
		}
		d := &net.Dialer{}
		dial = d.DialContext
	}
	raw, err := dial(ctx, "tcp", net.JoinHostPort(host, "443"))
	if err != nil {
		r.Problem = "cannot reach " + host + " (" + err.Error() + "): no internet, or the network blocks Tailscale"
		return r
	}
	defer raw.Close()
	c := tls.Client(raw, &tls.Config{ServerName: host, RootCAs: roots, MinVersion: tls.VersionTLS12})
	err = c.HandshakeContext(ctx)
	if err == nil {
		r.OK = true
		if cs := c.ConnectionState(); len(cs.PeerCertificates) > 0 {
			r.Issuer = name(cs.PeerCertificates[0].Issuer.Organization, cs.PeerCertificates[0].Issuer.CommonName)
		}
		return r
	}
	var ua x509.UnknownAuthorityError
	var hn x509.HostnameError
	switch {
	case errors.As(err, &ua) && ua.Cert != nil:
		r.Blocked = true
		r.Issuer = name(ua.Cert.Issuer.Organization, ua.Cert.Issuer.CommonName)
	case errors.As(err, &hn) && hn.Certificate != nil:
		r.Blocked = true
		r.Issuer = name(hn.Certificate.Issuer.Organization, hn.Certificate.Issuer.CommonName)
	}
	if r.Blocked {
		r.Problem = "this network blocks Tailscale: " + host + " was answered by a certificate from \"" + r.Issuer + "\", not Tailscale's. A sign-in will not help. The network's filter has to allow *.tailscale.com, or the PC needs another network"
		return r
	}
	r.Problem = "the secure connection to " + host + " failed (" + err.Error() + ")"
	return r
}

func name(org []string, cn string) string {
	parts := append([]string{}, org...)
	if cn != "" {
		parts = append(parts, cn)
	}
	return strings.Join(parts, " / ")
}
