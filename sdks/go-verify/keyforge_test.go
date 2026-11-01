package keyforge_test

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	keyforge "github.com/ArceeDev/keyforge/sdks/go-verify"
)

// helper to generate test keypair
func generateTestKeypair(t *testing.T) (ed25519.PublicKey, ed25519.PrivateKey, string) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("failed to generate ed25519 key: %v", err)
	}
	pubHex := hex.EncodeToString(pub)
	return pub, priv, pubHex
}

func TestVerifyValidToken_HexSignature(t *testing.T) {
	pub, priv, pubHex := generateTestKeypair(t)

	now := time.Now().Unix()
	exp := now + 86400 // 1 day in future
	payload := keyforge.LicensePayload{
		LicenseID:  "lic_test_123",
		Tier:       "pro",
		Email:      "alice@example.com",
		CustomerID: "cust_999",
		Features:   []string{"core", "audit_logs", "mcp_gateway"},
		ExpiresAt:  &exp,
		IssuedAt:   &now,
		MachineID:  "mach_abc123",
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal payload: %v", err)
	}

	sigBytes := ed25519.Sign(priv, payloadBytes)
	token := keyforge.FormatToken("pro", payloadBytes, sigBytes, true) // hex signature

	// Verify using public key
	verified, err := keyforge.Verify(token, pubHex)
	if err != nil {
		t.Fatalf("expected valid token, got error: %v", err)
	}

	if verified.LicenseID != "lic_test_123" {
		t.Errorf("expected LicenseID lic_test_123, got %s", verified.LicenseID)
	}
	if verified.Tier != "pro" {
		t.Errorf("expected Tier pro, got %s", verified.Tier)
	}
	if verified.Email != "alice@example.com" {
		t.Errorf("expected email alice@example.com, got %s", verified.Email)
	}
	if !verified.HasFeature("audit_logs") {
		t.Errorf("expected feature audit_logs to be present")
	}
	if verified.HasFeature("non_existent") {
		t.Errorf("did not expect non_existent feature")
	}
}

func TestVerifyValidToken_Base64Signature(t *testing.T) {
	_, priv, pubHex := generateTestKeypair(t)

	exp := time.Now().Unix() + 3600
	payload := keyforge.LicensePayload{
		Tier:      "team",
		Email:     "team@company.org",
		ExpiresAt: &exp,
		Features:  []string{"team_collab"},
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal payload: %v", err)
	}

	sigBytes := ed25519.Sign(priv, payloadBytes)
	token := keyforge.FormatToken("team", payloadBytes, sigBytes, false) // base64url signature

	verified, err := keyforge.Verify(token, pubHex)
	if err != nil {
		t.Fatalf("expected valid base64-signed token, got: %v", err)
	}
	if verified.Tier != "team" {
		t.Errorf("expected tier team, got %s", verified.Tier)
	}
}

func TestVerifyPerpetualLicense(t *testing.T) {
	_, priv, pubHex := generateTestKeypair(t)

	payload := keyforge.LicensePayload{
		Tier:      "enterprise",
		Email:     "admin@enterprise.com",
		ExpiresAt: nil, // perpetual
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal payload: %v", err)
	}

	sigBytes := ed25519.Sign(priv, payloadBytes)
	token := keyforge.FormatToken("enterprise", payloadBytes, sigBytes, true)

	// Verify far in the future
	farFuture := time.Unix(2500000000, 0)
	verified, err := keyforge.VerifyAt(token, pubHex, farFuture)
	if err != nil {
		t.Fatalf("expected perpetual token to never expire, got error: %v", err)
	}
	if verified.IsExpired(farFuture) {
		t.Errorf("perpetual license should report false for IsExpired")
	}
}

func TestVerifyExpiredToken(t *testing.T) {
	_, priv, pubHex := generateTestKeypair(t)

	past := time.Now().Unix() - 3600 // expired 1 hour ago
	payload := keyforge.LicensePayload{
		Tier:      "pro",
		Email:     "bob@example.com",
		ExpiresAt: &past,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal payload: %v", err)
	}

	sigBytes := ed25519.Sign(priv, payloadBytes)
	token := keyforge.FormatToken("pro", payloadBytes, sigBytes, true)

	_, err = keyforge.Verify(token, pubHex)
	if !errors.Is(err, keyforge.ErrExpired) {
		t.Fatalf("expected ErrExpired, got %v", err)
	}
}

func TestVerifyTampering(t *testing.T) {
	_, priv, pubHex := generateTestKeypair(t)

	exp := time.Now().Unix() + 3600
	payload := keyforge.LicensePayload{
		Tier:      "pro",
		Email:     "carol@example.com",
		ExpiresAt: &exp,
		Features:  []string{"basic"},
	}

	payloadBytes, _ := json.Marshal(payload)
	sigBytes := ed25519.Sign(priv, payloadBytes)

	// Case 1: Tamper with payload by elevating tier in payload without re-signing
	tamperedPayload := keyforge.LicensePayload{
		Tier:      "enterprise",
		Email:     "carol@example.com",
		ExpiresAt: &exp,
		Features:  []string{"unlimited"},
	}
	tamperedPayloadBytes, _ := json.Marshal(tamperedPayload)
	tamperedPayloadB64 := base64.RawURLEncoding.EncodeToString(tamperedPayloadBytes)
	tamperedToken := "LIC-ENTERPRISE-" + tamperedPayloadB64 + "." + hex.EncodeToString(sigBytes)

	_, err := keyforge.Verify(tamperedToken, pubHex)
	if !errors.Is(err, keyforge.ErrInvalidSignature) {
		t.Fatalf("expected ErrInvalidSignature on tampered payload, got: %v", err)
	}

	// Case 2: Tamper with signature bytes
	corruptedSig := make([]byte, len(sigBytes))
	copy(corruptedSig, sigBytes)
	corruptedSig[0] ^= 0xFF // flip bits
	corruptedToken := keyforge.FormatToken("pro", payloadBytes, corruptedSig, true)

	_, err = keyforge.Verify(corruptedToken, pubHex)
	if !errors.Is(err, keyforge.ErrInvalidSignature) {
		t.Fatalf("expected ErrInvalidSignature on corrupted signature, got: %v", err)
	}
}

func TestVerifyWrongPublicKey(t *testing.T) {
	_, priv1, _ := generateTestKeypair(t)
	_, _, pubHex2 := generateTestKeypair(t) // different key

	payload := keyforge.LicensePayload{
		Tier:  "pro",
		Email: "david@example.com",
	}
	payloadBytes, _ := json.Marshal(payload)
	sigBytes := ed25519.Sign(priv1, payloadBytes)
	token := keyforge.FormatToken("pro", payloadBytes, sigBytes, true)

	// 1. Wrong (different) valid public key
	_, err := keyforge.Verify(token, pubHex2)
	if !errors.Is(err, keyforge.ErrInvalidSignature) {
		t.Fatalf("expected ErrInvalidSignature when verifying against wrong key, got: %v", err)
	}

	// 2. Malformed public keys (length != 64 or invalid hex)
	badKeys := []string{
		"",
		"invalid_hex_string",
		"123456",
		"d04ab232742bb4ab3a1368bd4615e4e6d0224ab71a016baf8520a332c97787",   // 62 chars
		"d04ab232742bb4ab3a1368bd4615e4e6d0224ab71a016baf8520a332c9778737aa", // 66 chars
		"zz4ab232742bb4ab3a1368bd4615e4e6d0224ab71a016baf8520a332c9778737",   // invalid hex characters
	}

	for _, badKey := range badKeys {
		_, err := keyforge.Verify(token, badKey)
		if !errors.Is(err, keyforge.ErrInvalidPublicKey) {
			t.Errorf("for key %q expected ErrInvalidPublicKey, got %v", badKey, err)
		}
	}
}

func TestVerifyInvalidFormat(t *testing.T) {
	_, _, pubHex := generateTestKeypair(t)

	badTokens := []string{
		"",
		"   ",
		"LIC-PRO-abc",                     // missing dot
		"LIC-PRO-abc.sig.extra",           // too many dots
		"INVALID-PRO-abc.sig",             // wrong prefix
		"LIC--abc.sig",                    // missing tier
		"LIC-PRO-.sig",                    // missing payload
		"LIC-PRO-not!base64!.deadbeef",    // invalid base64 payload
		"LIC-PRO-bm90LWpzb24.deadbeef",    // base64 but not JSON ("not-json")
	}

	for _, badToken := range badTokens {
		_, err := keyforge.Verify(badToken, pubHex)
		if !errors.Is(err, keyforge.ErrInvalidFormat) {
			t.Errorf("for token %q expected ErrInvalidFormat, got %v", badToken, err)
		}
	}
}

func TestVerifyTierMismatch(t *testing.T) {
	_, priv, pubHex := generateTestKeypair(t)

	payload := keyforge.LicensePayload{
		Tier:  "community",
		Email: "user@example.com",
	}
	payloadBytes, _ := json.Marshal(payload)
	sigBytes := ed25519.Sign(priv, payloadBytes)

	// Format token with header tier "ENTERPRISE", but JSON body tier says "community"
	token := keyforge.FormatToken("enterprise", payloadBytes, sigBytes, true)

	_, err := keyforge.Verify(token, pubHex)
	if !errors.Is(err, keyforge.ErrInvalidFormat) {
		t.Fatalf("expected ErrInvalidFormat on tier mismatch, got %v", err)
	}
}

func TestDomainMatching(t *testing.T) {
	p := &keyforge.LicensePayload{
		AllowedDomains: []string{"api.acme.corp", "*.internal.net"},
	}

	if !p.MatchesDomain("api.acme.corp") {
		t.Errorf("expected exact match to succeed")
	}
	if !p.MatchesDomain("service.internal.net") {
		t.Errorf("expected wildcard match to succeed")
	}
	if !p.MatchesDomain("deep.sub.internal.net") {
		t.Errorf("expected deep subdomain wildcard match to succeed")
	}
	if p.MatchesDomain("malicious.com") {
		t.Errorf("did not expect unlisted domain to match")
	}

	emptyPayload := &keyforge.LicensePayload{}
	if !emptyPayload.MatchesDomain("anything.org") {
		t.Errorf("empty AllowedDomains should permit all domains")
	}
}

// TestVectorsJSON runs against test vectors in sdks/vectors/vectors.json if present
func TestVectorsJSON(t *testing.T) {
	vectorsPath := filepath.Join("..", "vectors", "vectors.json")
	data, err := os.ReadFile(vectorsPath)
	if err != nil {
		t.Skipf("skipping vectors.json test: %v", err)
		return
	}

	var parsed struct {
		Vectors []struct {
			Name       string   `json:"name"`
			Token      string   `json:"token"`
			PublicKeys []string `json:"public_keys"`
			Now        *int64   `json:"now"`
			Expected   struct {
				Valid bool    `json:"valid"`
				Error *string `json:"error"`
			} `json:"expected"`
		} `json:"vectors"`
	}

	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("failed to parse vectors.json: %v", err)
	}

	for _, vec := range parsed.Vectors {
		t.Run(vec.Name, func(t *testing.T) {
			if len(vec.PublicKeys) == 0 {
				return
			}
			pubKey := vec.PublicKeys[0]

			evalTime := time.Now()
			if vec.Now != nil {
				evalTime = time.Unix(*vec.Now, 0)
			}

			payload, err := keyforge.VerifyAt(vec.Token, pubKey, evalTime)

			if vec.Expected.Valid {
				if err != nil {
					t.Fatalf("vector %s expected valid, got error: %v", vec.Name, err)
				}
				if payload == nil {
					t.Fatalf("vector %s expected non-nil payload", vec.Name)
				}
			} else {
				if err == nil {
					t.Fatalf("vector %s expected error %v, got nil", vec.Name, vec.Expected.Error)
				}
			}
		})
	}
}
