package keyflint_test

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	keyflint "github.com/ArceeDev/keyflint/sdks/go-verify"
)

func keypair(t *testing.T) (ed25519.PrivateKey, string) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return priv, hex.EncodeToString(pub)
}

func sign(t *testing.T, priv ed25519.PrivateKey, tier string, claims map[string]interface{}) string {
	t.Helper()
	b, err := json.Marshal(claims)
	if err != nil {
		t.Fatal(err)
	}
	return keyflint.FormatToken(tier, b, ed25519.Sign(priv, b))
}

func TestValidTokenAndClaims(t *testing.T) {
	priv, pub := keypair(t)
	exp := time.Now().Unix() + 86400
	tok := sign(t, priv, "pro", map[string]interface{}{
		"license_id": "lic_1", "tier": "pro", "email": "a@example.com",
		"features": []string{"core", "audit_logs"}, "expires_at": exp, "machine_id": "Node-1",
	})
	p, err := keyflint.VerifyWithOptions(tok, pub, keyflint.Options{MachineID: " node-1 "})
	if err != nil {
		t.Fatal(err)
	}
	if p.LicenseID != "lic_1" || p.Email != "a@example.com" || *p.ExpiresAt != exp {
		t.Fatalf("bad claims: %+v", p)
	}
	if !p.HasFeature("audit_logs") || p.HasFeature("nope") {
		t.Fatal("feature gating broken")
	}
	// Machine-locked token without a local machine id is rejected (fail closed).
	if _, err := keyflint.Verify(tok, pub); !errors.Is(err, keyflint.ErrNodeLockViolation) {
		t.Fatalf("want node lock violation, got %v", err)
	}
}

func TestErrorsMapToSentinels(t *testing.T) {
	priv, pub := keypair(t)
	_, other := keypair(t)
	past := time.Now().Unix() - 10
	expired := sign(t, priv, "pro", map[string]interface{}{"tier": "pro", "expires_at": past})
	ok := sign(t, priv, "pro", map[string]interface{}{"tier": "pro"})

	cases := []struct {
		tok, key string
		code     string
		sentinel error
	}{
		{expired, pub, keyflint.CodeLicenseExpired, keyflint.ErrExpired},
		{ok, other, keyflint.CodeSignatureTampered, keyflint.ErrInvalidSignature},
		{ok, "zz", keyflint.CodeInvalidPublicKey, keyflint.ErrInvalidPublicKey},
		{"", pub, keyflint.CodeEmptyToken, keyflint.ErrInvalidFormat},
		{"X-PRO-abc.def", pub, keyflint.CodeInvalidTokenPrefix, keyflint.ErrInvalidFormat},
	}
	for _, c := range cases {
		_, err := keyflint.Verify(c.tok, c.key)
		if keyflint.Code(err) != c.code || !errors.Is(err, c.sentinel) {
			t.Errorf("token %.20q: got %v, want %s", c.tok, err, c.code)
		}
	}
}

func TestDomainMatching(t *testing.T) {
	p := &keyflint.LicensePayload{AllowedDomains: []string{"api.acme.corp", "*.internal.net"}}
	for d, want := range map[string]bool{
		"API.acme.corp.": true, "api.acme.corp:8443": true, "svc.internal.net": true,
		"internal.net": true, "xn--bcher-kva.example": false, "evil-internal.net": false, "a_b.internal.net": false, "": false,
	} {
		if p.MatchesDomain(d) != want {
			t.Errorf("MatchesDomain(%q) != %v", d, want)
		}
	}
	idn := &keyflint.LicensePayload{AllowedDomains: []string{"Bücher.example", "*.münchen.de"}}
	if !idn.MatchesDomain("xn--bcher-kva.example") || !idn.MatchesDomain("api.xn--mnchen-3ya.de") {
		t.Error("IDNA patterns must match their punycode form")
	}
	if !(&keyflint.LicensePayload{}).MatchesDomain("any.org") {
		t.Error("empty allowed_domains must allow any domain")
	}
}

type vectorFile struct {
	Keys    map[string]string `json:"keys"`
	Vectors []struct {
		Name       string   `json:"name"`
		Token      string   `json:"token"`
		PublicKeys []string `json:"public_keys"`
		Now        int64    `json:"now"`
		MachineID  *string  `json:"machine_id"`
		Domain     *string  `json:"domain"`
		Expected   struct {
			Valid bool    `json:"valid"`
			Error *string `json:"error"`
		} `json:"expected"`
	} `json:"vectors"`
}

func loadVectors(t *testing.T) vectorFile {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("..", "vectors", "vectors.json"))
	if err != nil {
		t.Fatalf("vectors.json is required for conformance: %v", err)
	}
	var vf vectorFile
	if err := json.Unmarshal(data, &vf); err != nil {
		t.Fatal(err)
	}
	return vf
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// TestVectors: exact error-code parity with the JS and Python SDKs.
func TestVectors(t *testing.T) {
	vf := loadVectors(t)
	if len(vf.Vectors) == 0 {
		t.Fatal("no vectors")
	}
	for _, v := range vf.Vectors {
		v := v
		t.Run(v.Name, func(t *testing.T) {
			opts := keyflint.Options{Now: time.Unix(v.Now, 0), MachineID: deref(v.MachineID), Domain: deref(v.Domain)}
			var err error
			if len(v.PublicKeys) == 1 {
				_, err = keyflint.VerifyWithOptions(v.Token, v.PublicKeys[0], opts)
			} else {
				_, err = keyflint.VerifyWithKeys(v.Token, v.PublicKeys, opts)
			}
			if got, want := keyflint.Code(err), deref(v.Expected.Error); got != want || (err == nil) != v.Expected.Valid {
				t.Fatalf("got %q (err=%v), want %q", got, err, want)
			}
		})
	}
}

func vector(t *testing.T, vf vectorFile, name string) (string, int64) {
	for _, v := range vf.Vectors {
		if v.Name == name {
			return v.Token, v.Now
		}
	}
	t.Fatalf("vector %s missing", name)
	return "", 0
}

func TestKeyRing(t *testing.T) {
	vf := loadVectors(t)
	k1, k2 := vf.Keys["k1"], vf.Keys["k2"]

	tok, now := vector(t, vf, "ring_kid_token_new_key")
	opts := keyflint.Options{Now: time.Unix(now, 0)}
	p, err := keyflint.VerifyWithKeyRing(tok, map[string]string{"legacy": k1, "k2": k2}, opts)
	if err != nil || p.KeyID != "k2" || p.KID != "k2" {
		t.Fatalf("kid selection: %v %+v", err, p)
	}
	if _, err := keyflint.VerifyWithKeyRing(tok, map[string]string{"legacy": k1}, opts); keyflint.Code(err) != keyflint.CodeUnknownKID {
		t.Fatalf("want ERR_UNKNOWN_KID, got %v", err)
	}

	legacy, now := vector(t, vf, "ring_legacy_token_old_key")
	p, err = keyflint.VerifyWithKeyRing(legacy, map[string]string{"k2": k2, "legacy": k1}, keyflint.Options{Now: time.Unix(now, 0)})
	if err != nil || p.KeyID != "legacy" {
		t.Fatalf("legacy token: %v %+v", err, p)
	}

	other, now := vector(t, vf, "kid_claim_signed_by_other_key")
	opts = keyflint.Options{Now: time.Unix(now, 0)}
	if _, err := keyflint.VerifyWithKeyRing(other, map[string]string{"legacy": k1, "k2": k2}, opts); keyflint.Code(err) != keyflint.CodeSignatureTampered {
		t.Fatalf("kid must bind to its key, got %v", err)
	}
	if _, err := keyflint.VerifyWithKeys(other, []string{k2, k1}, opts); err != nil {
		t.Fatalf("lists try every key: %v", err)
	}

	basic, now := vector(t, vf, "valid_basic")
	opts = keyflint.Options{Now: time.Unix(now, 0)}
	if _, err := keyflint.VerifyWithKeys(basic, nil, opts); keyflint.Code(err) != keyflint.CodeInvalidPublicKey {
		t.Fatalf("empty ring: %v", err)
	}
	if _, err := keyflint.VerifyWithKeyRing("", map[string]string{}, opts); keyflint.Code(err) != keyflint.CodeEmptyToken {
		t.Fatalf("structural error wins: %v", err)
	}
	head := tok[:len(tok)-4]
	if _, err := keyflint.VerifyWithKeyRing(head, map[string]string{"legacy": k1}, opts); keyflint.Code(err) != keyflint.CodeInvalidSignatureLength {
		t.Fatalf("structural error wins over unknown kid: %v", err)
	}
	exp, now := vector(t, vf, "expired")
	if _, err := keyflint.VerifyWithKeys(exp, []string{k2, k1}, keyflint.Options{Now: time.Unix(now, 0)}); keyflint.Code(err) != keyflint.CodeLicenseExpired {
		t.Fatalf("expired from matching key: %v", err)
	}
}
