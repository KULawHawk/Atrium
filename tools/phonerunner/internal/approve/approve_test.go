package approve

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/go-webauthn/webauthn/protocol"
	"github.com/go-webauthn/webauthn/protocol/webauthncbor"
	"github.com/go-webauthn/webauthn/protocol/webauthncose"
	"github.com/go-webauthn/webauthn/webauthn"
)

const (
	rpID   = "phonerunner.tail1234.ts.net"
	origin = "https://phonerunner.tail1234.ts.net"
	phone  = "nPHONE"
	pc     = "nPC"
)

var b64 = base64.RawURLEncoding

// softKey is a software passkey standing in for the phone in tests.
type softKey struct {
	priv  *ecdsa.PrivateKey
	id    []byte
	count uint32
	uv    bool
}

func newSoftKey(t *testing.T) *softKey {
	t.Helper()
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	id := make([]byte, 16)
	_, _ = rand.Read(id)
	return &softKey{priv: k, id: id, uv: true}
}

func (k *softKey) flags(extra byte) byte {
	f := byte(0x01) | extra // user present
	if k.uv {
		f |= 0x04
	}
	return f
}

func (k *softKey) authData(extra byte, attested []byte) []byte {
	h := sha256.Sum256([]byte(rpID))
	b := append([]byte{}, h[:]...)
	b = append(b, k.flags(extra))
	b = binary.BigEndian.AppendUint32(b, k.count)
	return append(b, attested...)
}

func clientData(typ string, challenge []byte, org string) []byte {
	b, _ := json.Marshal(map[string]string{"type": typ, "challenge": b64.EncodeToString(challenge), "origin": org})
	return b
}

// register answers a registration challenge.
func (k *softKey) register(t *testing.T, cc *protocol.CredentialCreation, org string) *protocol.ParsedCredentialCreationData {
	t.Helper()
	ecdh, err := k.priv.PublicKey.ECDH()
	if err != nil {
		t.Fatal(err)
	}
	raw := ecdh.Bytes() // 0x04 || X || Y
	cose, err := webauthncbor.Marshal(webauthncose.EC2PublicKeyData{
		PublicKeyData: webauthncose.PublicKeyData{KeyType: 2, Algorithm: -7},
		Curve:         1, XCoord: raw[1:33], YCoord: raw[33:],
	})
	if err != nil {
		t.Fatal(err)
	}
	att := make([]byte, 16) // AAGUID
	att = binary.BigEndian.AppendUint16(att, uint16(len(k.id)))
	att = append(att, k.id...)
	att = append(att, cose...)
	ao, err := webauthncbor.Marshal(map[string]any{"fmt": "none", "attStmt": map[string]any{}, "authData": k.authData(0x40, att)})
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]any{
		"id": b64.EncodeToString(k.id), "rawId": b64.EncodeToString(k.id), "type": "public-key",
		"response": map[string]any{
			"clientDataJSON":    b64.EncodeToString(clientData("webauthn.create", cc.Response.Challenge, org)),
			"attestationObject": b64.EncodeToString(ao),
		},
	})
	p, err := protocol.ParseCredentialCreationResponseBytes(body)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// sign answers a login challenge.
func (k *softKey) sign(t *testing.T, ca *protocol.CredentialAssertion, userID []byte, org string) *protocol.ParsedCredentialAssertionData {
	t.Helper()
	k.count++
	ad := k.authData(0, nil)
	cd := clientData("webauthn.get", ca.Response.Challenge, org)
	h := sha256.Sum256(cd)
	digest := sha256.Sum256(append(append([]byte{}, ad...), h[:]...))
	sig, err := ecdsa.SignASN1(rand.Reader, k.priv, digest[:])
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]any{
		"id": b64.EncodeToString(k.id), "rawId": b64.EncodeToString(k.id), "type": "public-key",
		"response": map[string]any{
			"clientDataJSON":    b64.EncodeToString(cd),
			"authenticatorData": b64.EncodeToString(ad),
			"signature":         b64.EncodeToString(sig),
			"userHandle":        b64.EncodeToString(userID),
		},
	})
	p, err := protocol.ParseCredentialRequestResponseBytes(body)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

type clock struct{ t time.Time }

func (c *clock) now() time.Time { return c.t }

func setup(t *testing.T) (*Approver, *softKey, *clock, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "passkeys.json")
	a, err := New(rpID, origin, path)
	if err != nil {
		t.Fatal(err)
	}
	c := &clock{t: time.Date(2026, 11, 21, 3, 0, 0, 0, time.UTC)}
	a.SetClock(c.now)
	k := newSoftKey(t)
	a.OpenRegistration(phone)
	cc, err := a.BeginRegistration(phone)
	if err != nil {
		t.Fatal(err)
	}
	code, err := a.FinishRegistration(phone, k.register(t, cc, origin))
	if err != nil {
		t.Fatal(err)
	}
	if w, ok := a.Waiting(); !ok || w != code || a.Count() != 0 {
		t.Fatal("passkey must wait for the desk")
	}
	if err := a.Confirm("00000000"); !errors.Is(err, ErrConfirmMismatch) {
		t.Fatal(err)
	}
	if err := a.Confirm(code); err != nil {
		t.Fatal(err)
	}
	if a.Count() != 1 {
		t.Fatal("not stored")
	}
	return a, k, c, path
}

var req = Request{ItemID: "pod-start", ManifestSHA: "abc", Action: "run", DeviceID: phone}

func same(string) (string, error) { return "abc", nil }

func TestApproveHappyAndReplay(t *testing.T) {
	a, k, _, path := setup(t)
	ca, err := a.Begin(req)
	if err != nil {
		t.Fatal(err)
	}
	if ca.Response.UserVerification != protocol.VerificationRequired {
		t.Fatal("phone unlock must be required")
	}
	resp := k.sign(t, ca, a.owner.ID, origin)
	got, err := a.Finish(phone, resp, same)
	if err != nil || got != req {
		t.Fatal(got, err)
	}
	// T-03: the same answer again is refused.
	if _, err := a.Finish(phone, resp, same); !errors.Is(err, ErrUnknown) {
		t.Fatal(err)
	}
	// The counter was saved, and a fresh Approver reloads the passkey.
	b, err := New(rpID, origin, path)
	if err != nil || b.Count() != 1 || b.owner.Credentials[0].Authenticator.SignCount != 1 {
		t.Fatal(err)
	}
}

func TestApproveRefusals(t *testing.T) {
	a, k, c, _ := setup(t)
	try := func(dev string, manifest func(string) (string, error), mutate func(*softKey), org string, wait time.Duration) error {
		ca, err := a.Begin(req)
		if err != nil {
			t.Fatal(err)
		}
		if mutate != nil {
			mutate(k)
		}
		resp := k.sign(t, ca, a.owner.ID, org)
		c.t = c.t.Add(wait)
		return a.finishErr(dev, resp, manifest)
	}
	cases := []struct {
		name string
		err  error
		want string
	}{
		{"T-04 expired", try(phone, same, nil, origin, TTL+time.Second), ErrExpired.Error()},
		{"other device", try(pc, same, nil, origin, 0), ErrWrongDevice.Error()},
		{"manifest changed", try(phone, func(string) (string, error) { return "def", nil }, nil, origin, 0), ErrManifestChange.Error()},
		{"manifest unreadable", try(phone, func(string) (string, error) { return "", errors.New("gone") }, nil, origin, 0), "cannot re-read"},
		{"no phone unlock", try(phone, same, func(k *softKey) { k.uv = false }, origin, 0), "signature refused"},
		{"wrong site", try(phone, same, func(k *softKey) { k.uv = true }, "https://evil.example", 0), "signature refused"},
	}
	for _, cs := range cases {
		if cs.err == nil || !strings.Contains(cs.err.Error(), cs.want) {
			t.Errorf("%s: %v", cs.name, cs.err)
		}
	}
	// A copied passkey: the counter goes backwards.
	ca, _ := a.Begin(req)
	a.owner.Credentials[0].Authenticator.SignCount = 50
	if _, err := a.Finish(phone, k.sign(t, ca, a.owner.ID, origin), same); err == nil {
		t.Fatal("counter going backwards must be refused")
	}
}

// finishErr is Finish with only the error, so table cases read as one line.
func (a *Approver) finishErr(dev string, resp *protocol.ParsedCredentialAssertionData, m func(string) (string, error)) error {
	_, err := a.Finish(dev, resp, m)
	return err
}

func TestBeginRefusals(t *testing.T) {
	path := filepath.Join(t.TempDir(), "passkeys.json")
	a, err := New(rpID, origin, path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := a.Begin(Request{ItemID: "x"}); !errors.Is(err, ErrBadRequest) {
		t.Fatal(err)
	}
	if _, err := a.Begin(req); !errors.Is(err, ErrNoPasskey) {
		t.Fatal(err)
	}
}

func TestRegistrationRules(t *testing.T) {
	a, err := New(rpID, origin, filepath.Join(t.TempDir(), "p.json"))
	if err != nil {
		t.Fatal(err)
	}
	c := &clock{t: time.Unix(1000, 0)}
	a.SetClock(c.now)
	if _, err := a.BeginRegistration(phone); !errors.Is(err, ErrRegClosed) {
		t.Fatal(err)
	}
	if _, err := a.FinishRegistration(phone, nil); !errors.Is(err, ErrRegClosed) {
		t.Fatal(err)
	}
	if err := a.Confirm("x"); !errors.Is(err, ErrNothingPending) {
		t.Fatal(err)
	}
	a.OpenRegistration(phone)
	// T-17: from the PC, refused.
	if _, err := a.BeginRegistration(pc); !errors.Is(err, ErrRegNotPhone) {
		t.Fatal(err)
	}
	cc, err := a.BeginRegistration(phone)
	if err != nil {
		t.Fatal(err)
	}
	k1, k2 := newSoftKey(t), newSoftKey(t)
	if _, err := a.FinishRegistration(pc, k1.register(t, cc, origin)); !errors.Is(err, ErrRegNotPhone) {
		t.Fatal(err)
	}
	if _, err := a.FinishRegistration(phone, k1.register(t, cc, origin)); err != nil {
		t.Fatal(err)
	}
	// A second passkey in the same window: both refused, window closed.
	if _, err := a.FinishRegistration(phone, k2.register(t, cc, origin)); !errors.Is(err, ErrRegTwo) {
		t.Fatal(err)
	}
	if _, ok := a.Waiting(); ok || a.Count() != 0 {
		t.Fatal("both must be refused")
	}
	// A bad answer (wrong site) is refused and nothing waits.
	a.OpenRegistration(phone)
	cc, _ = a.BeginRegistration(phone)
	if _, err := a.FinishRegistration(phone, k1.register(t, cc, "https://evil.example")); err == nil || !strings.Contains(err.Error(), "refused") {
		t.Fatal(err)
	}
	// The window closes after 5 minutes.
	a.OpenRegistration(phone)
	c.t = c.t.Add(RegWindow + time.Second)
	if _, err := a.BeginRegistration(phone); !errors.Is(err, ErrRegClosed) {
		t.Fatal(err)
	}
}

func TestNewAndSave(t *testing.T) {
	if _, err := New("", "", filepath.Join(t.TempDir(), "p.json")); err == nil {
		t.Fatal("empty site must fail")
	}
	newWebAuthn = func(*webauthn.Config) (*webauthn.WebAuthn, error) { return nil, errors.New("lib") }
	if _, err := New(rpID, origin, filepath.Join(t.TempDir(), "p.json")); err == nil {
		t.Fatal("library failure must surface")
	}
	newWebAuthn = webauthn.New
	d := t.TempDir()
	bad := filepath.Join(d, "bad.json")
	_ = os.WriteFile(bad, []byte("{"), 0o600)
	if _, err := New(rpID, origin, bad); err == nil || !strings.Contains(err.Error(), "damaged") {
		t.Fatal(err)
	}
	if _, err := New(rpID, origin, d); err == nil { // a folder, not a file
		t.Fatal("unreadable file must fail")
	}
	a, k, _, _ := setup(t)
	a.write = func(string, []byte) error { return errors.New("disk full") }
	ca, _ := a.Begin(req)
	if err := a.finishErr(phone, k.sign(t, ca, a.owner.ID, origin), same); err == nil || !strings.Contains(err.Error(), "saving passkeys") {
		t.Fatal(err)
	}
	if err := writeAtomic(filepath.Join(d, "missing", "x"), nil); err == nil {
		t.Fatal("missing folder must fail")
	}
	if Code([]byte{1}) == Code([]byte{2}) || len(Code([]byte{1})) != 8 {
		t.Fatal("code")
	}
}

type failing struct {
	ceremony
	login, reg bool
}

func (f failing) BeginLogin(u webauthn.User, o ...webauthn.LoginOption) (*protocol.CredentialAssertion, *webauthn.SessionData, error) {
	if f.login {
		return nil, nil, errors.New("lib")
	}
	return f.ceremony.BeginLogin(u, o...)
}

func (f failing) BeginRegistration(u webauthn.User, o ...webauthn.RegistrationOption) (*protocol.CredentialCreation, *webauthn.SessionData, error) {
	if f.reg {
		return nil, nil, errors.New("lib")
	}
	return f.ceremony.BeginRegistration(u, o...)
}

func TestLibraryFailures(t *testing.T) {
	a, _, c, _ := setup(t)
	real := a.wa
	a.wa = failing{ceremony: real, login: true}
	if _, err := a.Begin(req); err == nil {
		t.Fatal("library failure must surface")
	}
	a.wa = failing{ceremony: real, reg: true}
	a.OpenRegistration(phone)
	if _, err := a.BeginRegistration(phone); err == nil {
		t.Fatal("library failure must surface")
	}
	a.wa = real
	// Old challenges are swept on the next tap.
	if _, err := a.Begin(req); err != nil {
		t.Fatal(err)
	}
	c.t = c.t.Add(TTL + time.Second)
	if _, err := a.Begin(req); err != nil || len(a.pending) != 1 {
		t.Fatal(len(a.pending), err)
	}
	marshal = func(any) ([]byte, error) { return nil, errors.New("enc") }
	defer func() { marshal = json.Marshal }()
	if err := a.save(); err == nil {
		t.Fatal("encode failure must surface")
	}
}
