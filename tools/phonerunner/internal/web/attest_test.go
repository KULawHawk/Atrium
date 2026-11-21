package web

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"testing"

	"github.com/go-webauthn/webauthn/protocol/webauthncbor"
	"github.com/go-webauthn/webauthn/protocol/webauthncose"
)

// attestationBody builds a well-formed "none" attestation the library's parser
// accepts; the fake Passkeys stands in for the real checks.
func attestationBody(t *testing.T) string {
	t.Helper()
	b64 := base64.RawURLEncoding
	priv, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	ecdh, _ := priv.PublicKey.ECDH()
	raw := ecdh.Bytes()
	cose, err := webauthncbor.Marshal(webauthncose.EC2PublicKeyData{
		PublicKeyData: webauthncose.PublicKeyData{KeyType: 2, Algorithm: -7},
		Curve:         1, XCoord: raw[1:33], YCoord: raw[33:],
	})
	if err != nil {
		t.Fatal(err)
	}
	id := []byte("credential-id-16")
	h := sha256.Sum256([]byte("phonerunner.example.ts.net"))
	ad := append(append([]byte{}, h[:]...), 0x45) // UP, UV, AT
	ad = binary.BigEndian.AppendUint32(ad, 0)
	ad = append(ad, make([]byte, 16)...)
	ad = binary.BigEndian.AppendUint16(ad, uint16(len(id)))
	ad = append(append(ad, id...), cose...)
	ao, err := webauthncbor.Marshal(map[string]any{"fmt": "none", "attStmt": map[string]any{}, "authData": ad})
	if err != nil {
		t.Fatal(err)
	}
	cd, _ := json.Marshal(map[string]string{"type": "webauthn.create", "challenge": b64.EncodeToString([]byte("c")), "origin": "https://phonerunner.example.ts.net"})
	body, _ := json.Marshal(map[string]any{
		"id": b64.EncodeToString(id), "rawId": b64.EncodeToString(id), "type": "public-key",
		"response": map[string]any{"clientDataJSON": b64.EncodeToString(cd), "attestationObject": b64.EncodeToString(ao)},
	})
	return string(body)
}
