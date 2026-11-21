// Package approve is the Run button's approval check: one passkey signature
// from Jake's phone per tap, bound to one exact request.
//
// How the binding works. Each tap asks the service for a challenge. The
// service draws 32 random bytes (the library's own generator), and stores them
// against the exact request: item id, the sha256 of the item's manifest, the
// action, and the Tailscale device the tap came from. The phone signs that
// challenge after Jake unlocks it. On the way back the service:
//
//  1. finds the stored request by the challenge and deletes it at once, so a
//     second use (a replay) finds nothing;
//  2. refuses it if older than the time limit (2 minutes);
//  3. refuses it unless it comes from the same Tailscale device;
//  4. checks the signature, with user verification (his phone unlock) required;
//  5. re-reads the item's manifest and refuses it if the sha256 changed.
//
// The challenge is random rather than a hash of the request on purpose: the
// library warns that a derived challenge weakens it, and the stored, single-use
// mapping binds the signature to the request just as tightly.
//
// Registration. A passkey can be added only while a registration window is
// open (opened at the desk), only from the phone's own Tailscale device, and
// only one per window: if a second arrives in the same window, both are
// refused. The new credential waits until Jake confirms it at the desk.
package approve

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/go-webauthn/webauthn/protocol"
	"github.com/go-webauthn/webauthn/webauthn"
)

// TTL is how long a tap's challenge stays valid.
const TTL = 2 * time.Minute

// RegWindow is how long a desk-opened registration window stays open.
const RegWindow = 5 * time.Minute

// Request is exactly what one tap approves.
type Request struct {
	ItemID      string `json:"item_id"`
	ManifestSHA string `json:"manifest_sha"`
	Action      string `json:"action"`
	DeviceID    string `json:"device_id"`
}

// Errors, each a refusal with its reason.
var (
	ErrNoPasskey       = errors.New("no passkey is registered yet")
	ErrUnknown         = errors.New("unknown or already used challenge (a replay is refused)")
	ErrExpired         = errors.New("the approval took longer than 2 minutes; tap Run again")
	ErrWrongDevice     = errors.New("the approval did not come from the phone that tapped Run")
	ErrManifestChange  = errors.New("the item's files changed after you tapped Run; review it again")
	ErrBadRequest      = errors.New("item, manifest, action and device are all required")
	ErrRegClosed       = errors.New("registration is closed; open it at the desk first")
	ErrRegNotPhone     = errors.New("passkeys can be registered only from your phone")
	ErrRegTwo          = errors.New("two passkeys arrived in one registration window; both were refused")
	ErrNothingPending  = errors.New("no new passkey is waiting for confirmation")
	ErrConfirmMismatch = errors.New("the code typed at the desk does not match the waiting passkey")
)

// Owner is Jake's account as the passkey library sees it.
type Owner struct {
	ID          []byte                `json:"id"`
	Credentials []webauthn.Credential `json:"credentials"`
}

// WebAuthnID implements webauthn.User.
func (o *Owner) WebAuthnID() []byte { return o.ID }

// WebAuthnName implements webauthn.User.
func (o *Owner) WebAuthnName() string { return "jake" }

// WebAuthnDisplayName implements webauthn.User.
func (o *Owner) WebAuthnDisplayName() string { return "Jake" }

// WebAuthnCredentials implements webauthn.User.
func (o *Owner) WebAuthnCredentials() []webauthn.Credential { return o.Credentials }

type pending struct {
	req     Request
	session webauthn.SessionData
	at      time.Time
}

type regState struct {
	until    time.Time
	phone    string
	session  *webauthn.SessionData
	waiting  *webauthn.Credential
	arrivals int
}

// ceremony is the part of the passkey library used here (a seam for tests).
type ceremony interface {
	BeginLogin(user webauthn.User, opts ...webauthn.LoginOption) (*protocol.CredentialAssertion, *webauthn.SessionData, error)
	ValidateLogin(user webauthn.User, session webauthn.SessionData, resp *protocol.ParsedCredentialAssertionData) (*webauthn.Credential, error)
	BeginRegistration(user webauthn.User, opts ...webauthn.RegistrationOption) (*protocol.CredentialCreation, *webauthn.SessionData, error)
	CreateCredential(user webauthn.User, session webauthn.SessionData, resp *protocol.ParsedCredentialCreationData) (*webauthn.Credential, error)
}

var (
	marshal     = json.Marshal
	newWebAuthn = webauthn.New
)

// Approver holds passkeys and outstanding challenges. Safe for concurrent use.
type Approver struct {
	wa    ceremony
	path  string // private\passkeys.json, SYSTEM/Administrators only
	now   func() time.Time
	write func(string, []byte) error

	mu      sync.Mutex
	owner   Owner
	pending map[string]pending
	reg     *regState
}

// New builds an Approver for the page's address, loading passkeys from path.
// A missing file means none registered yet.
func New(rpID, origin, path string) (*Approver, error) {
	if rpID == "" || origin != "https://"+rpID {
		return nil, fmt.Errorf("approve: the page address must be https://%s (got %q)", rpID, origin)
	}
	wa, err := newWebAuthn(&webauthn.Config{RPID: rpID, RPDisplayName: "PhoneRunner", RPOrigins: []string{origin}})
	if err != nil {
		return nil, fmt.Errorf("approve: %w", err)
	}
	a := &Approver{wa: wa, path: path, now: time.Now, write: writeAtomic, pending: map[string]pending{}}
	b, err := os.ReadFile(path)
	switch {
	case errors.Is(err, os.ErrNotExist):
		a.owner.ID = randomID()
	case err != nil:
		return nil, fmt.Errorf("approve: %w", err)
	default:
		if err := json.Unmarshal(b, &a.owner); err != nil || len(a.owner.ID) == 0 {
			return nil, fmt.Errorf("approve: %s is damaged: refusing to start (%v)", path, err)
		}
	}
	return a, nil
}

// SetClock replaces the clock (tests).
func (a *Approver) SetClock(now func() time.Time) { a.now = now }

// Count is how many passkeys are registered.
func (a *Approver) Count() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return len(a.owner.Credentials)
}

// Begin issues the challenge for one tap.
func (a *Approver) Begin(req Request) (*protocol.CredentialAssertion, error) {
	if req.ItemID == "" || req.ManifestSHA == "" || req.Action == "" || req.DeviceID == "" {
		return nil, ErrBadRequest
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if len(a.owner.Credentials) == 0 {
		return nil, ErrNoPasskey
	}
	a.sweep()
	opts, sess, err := a.wa.BeginLogin(&a.owner, webauthn.WithUserVerification(protocol.VerificationRequired))
	if err != nil {
		return nil, fmt.Errorf("approve: %w", err)
	}
	a.pending[sess.Challenge] = pending{req: req, session: *sess, at: a.now()}
	return opts, nil
}

// Finish checks one tap's signed answer. manifest returns the item's current
// manifest sha256. On success it returns the request that was approved.
func (a *Approver) Finish(deviceID string, resp *protocol.ParsedCredentialAssertionData, manifest func(itemID string) (string, error)) (Request, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	key := resp.Response.CollectedClientData.Challenge // base64url, as stored by Begin
	p, ok := a.pending[key]
	if !ok {
		return Request{}, ErrUnknown
	}
	delete(a.pending, key) // single use, whatever happens next
	if a.now().Sub(p.at) > TTL {
		return Request{}, ErrExpired
	}
	if deviceID != p.req.DeviceID {
		return Request{}, ErrWrongDevice
	}
	cred, err := a.wa.ValidateLogin(&a.owner, p.session, resp)
	if err != nil {
		return Request{}, fmt.Errorf("approve: signature refused: %w", err)
	}
	if cred.Authenticator.CloneWarning {
		return Request{}, errors.New("approve: the passkey's counter went backwards (a copied passkey?); refused")
	}
	cur, err := manifest(p.req.ItemID)
	if err != nil {
		return Request{}, fmt.Errorf("approve: cannot re-read the manifest: %w", err)
	}
	if cur != p.req.ManifestSHA {
		return Request{}, ErrManifestChange
	}
	for i := range a.owner.Credentials {
		if string(a.owner.Credentials[i].ID) == string(cred.ID) {
			a.owner.Credentials[i].Authenticator.SignCount = cred.Authenticator.SignCount
		}
	}
	if err := a.save(); err != nil {
		return Request{}, err
	}
	return p.req, nil
}

func (a *Approver) sweep() {
	for k, p := range a.pending {
		if a.now().Sub(p.at) > TTL {
			delete(a.pending, k)
		}
	}
}

// OpenRegistration opens a 5-minute window for the phone with Tailscale device
// phoneID. It is called only from the desk (an elevated command).
func (a *Approver) OpenRegistration(phoneID string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.reg = &regState{until: a.now().Add(RegWindow), phone: phoneID}
}

func (a *Approver) regOpen() bool { return a.reg != nil && a.now().Before(a.reg.until) }

// BeginRegistration starts adding a passkey from deviceID.
func (a *Approver) BeginRegistration(deviceID string) (*protocol.CredentialCreation, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if !a.regOpen() {
		return nil, ErrRegClosed
	}
	if deviceID != a.reg.phone {
		return nil, ErrRegNotPhone
	}
	var excl []protocol.CredentialDescriptor
	for _, c := range a.owner.Credentials {
		excl = append(excl, c.Descriptor())
	}
	opts, sess, err := a.wa.BeginRegistration(&a.owner,
		webauthn.WithAuthenticatorSelection(protocol.AuthenticatorSelection{
			AuthenticatorAttachment: protocol.Platform,
			ResidentKey:             protocol.ResidentKeyRequirementRequired,
			UserVerification:        protocol.VerificationRequired,
		}),
		webauthn.WithExclusions(excl))
	if err != nil {
		return nil, fmt.Errorf("approve: %w", err)
	}
	a.reg.session = sess
	return opts, nil
}

// FinishRegistration receives the phone's new passkey. It waits for Jake's
// confirmation at the desk; the returned code is shown on the phone and at the
// desk so he can check they match.
func (a *Approver) FinishRegistration(deviceID string, resp *protocol.ParsedCredentialCreationData) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if !a.regOpen() || a.reg.session == nil {
		return "", ErrRegClosed
	}
	if deviceID != a.reg.phone {
		return "", ErrRegNotPhone
	}
	a.reg.arrivals++
	if a.reg.arrivals > 1 {
		a.reg.waiting = nil
		a.reg.until = a.now() // close the window
		return "", ErrRegTwo
	}
	cred, err := a.wa.CreateCredential(&a.owner, *a.reg.session, resp)
	if err != nil {
		return "", fmt.Errorf("approve: new passkey refused: %w", err)
	}
	a.reg.waiting = cred
	return Code(cred.ID), nil
}

// Code is a short fingerprint of a credential id, shown on phone and desk.
func Code(id []byte) string {
	h := sha256.Sum256(id)
	return hex.EncodeToString(h[:4])
}

// Waiting returns the code of the passkey waiting for confirmation, if any.
func (a *Approver) Waiting() (string, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if !a.regOpen() || a.reg.waiting == nil {
		return "", false
	}
	return Code(a.reg.waiting.ID), true
}

// Confirm stores the waiting passkey if code matches. Desk only.
func (a *Approver) Confirm(code string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if !a.regOpen() || a.reg.waiting == nil {
		return ErrNothingPending
	}
	if Code(a.reg.waiting.ID) != code {
		return ErrConfirmMismatch
	}
	a.owner.Credentials = append(a.owner.Credentials, *a.reg.waiting)
	a.reg = nil
	return a.save()
}

func (a *Approver) save() error {
	b, err := marshal(a.owner)
	if err != nil {
		return fmt.Errorf("approve: %w", err)
	}
	if err := a.write(a.path, b); err != nil {
		return fmt.Errorf("approve: saving passkeys: %w", err)
	}
	return nil
}

func writeAtomic(path string, b []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Clean(path))
}

func randomID() []byte {
	b := make([]byte, 64)
	_, _ = rand.Read(b) // crypto/rand.Read never fails (it aborts the program instead)
	return b
}
