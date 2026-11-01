// Package keyforge provides offline Ed25519 cryptographic license verification for KeyForge.
//
// Zero external dependencies. Uses only Go standard library packages:
// crypto/ed25519, encoding/hex, encoding/base64, encoding/json.
package keyforge

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

var (
	// ErrInvalidFormat is returned when the license token format or internal JSON payload is malformed.
	ErrInvalidFormat = errors.New("keyforge: invalid license token format")

	// ErrInvalidSignature is returned when the cryptographic signature fails verification or has been tampered with.
	ErrInvalidSignature = errors.New("keyforge: invalid or tampered signature")

	// ErrExpired is returned when the license expiration timestamp has passed.
	ErrExpired = errors.New("keyforge: license has expired")

	// ErrInvalidPublicKey is returned when the provided public key is not a valid 64-character hex Ed25519 key.
	ErrInvalidPublicKey = errors.New("keyforge: invalid ed25519 public key")
)

// LicensePayload represents the verified claims encoded within a KeyForge license token.
type LicensePayload struct {
	LicenseID      string                 `json:"license_id,omitempty"`
	Tier           string                 `json:"tier"`
	Email          string                 `json:"email,omitempty"`
	CustomerID     string                 `json:"customer_id,omitempty"`
	Features       []string               `json:"features,omitempty"`
	ExpiresAt      *int64                 `json:"expires_at,omitempty"`
	IssuedAt       *int64                 `json:"issued_at,omitempty"`
	MachineID      string                 `json:"machine_id,omitempty"`
	AllowedDomains []string               `json:"allowed_domains,omitempty"`
	KID            string                 `json:"kid,omitempty"`
	Metadata       map[string]interface{} `json:"metadata,omitempty"`
}

// IsExpired reports whether the license has expired relative to the given time.
// A nil ExpiresAt represents a perpetual license (never expires).
func (p *LicensePayload) IsExpired(at time.Time) bool {
	if p == nil || p.ExpiresAt == nil {
		return false
	}
	return at.Unix() > *p.ExpiresAt
}

// HasFeature reports whether the license includes the specified feature entitlement.
func (p *LicensePayload) HasFeature(feature string) bool {
	if p == nil {
		return false
	}
	for _, f := range p.Features {
		if f == feature {
			return true
		}
	}
	return false
}

// MatchesDomain reports whether the provided domain is permitted by the license claims.
func (p *LicensePayload) MatchesDomain(domain string) bool {
	if p == nil || len(p.AllowedDomains) == 0 {
		return true
	}
	cleanDomain := strings.ToLower(strings.TrimSpace(domain))
	if cleanDomain == "" {
		return false
	}
	for _, pattern := range p.AllowedDomains {
		pat := strings.ToLower(strings.TrimSpace(pattern))
		if pat == cleanDomain {
			return true
		}
		if strings.HasPrefix(pat, "*.") {
			suffix := strings.TrimPrefix(pat, "*.")
			if cleanDomain == suffix || strings.HasSuffix(cleanDomain, "."+suffix) {
				return true
			}
		}
	}
	return false
}

// Verify validates a KeyForge license token using the provided Ed25519 public key.
// The token format adheres to RFC 8032: LIC-<TIER>-<PAYLOAD_B64>.<SIG_HEX> (with dual compatibility
// for base64url signatures).
//
// Returns the decoded LicensePayload if valid, or an error if invalid, tampered, or expired.
func Verify(token string, publicKeyHex string) (*LicensePayload, error) {
	return VerifyAt(token, publicKeyHex, time.Now())
}

// VerifyAt validates a KeyForge license token against a specific point in time.
// This is particularly useful for deterministic unit testing and time-skew handling.
func VerifyAt(token string, publicKeyHex string, at time.Time) (*LicensePayload, error) {
	// 1. Validate and parse public key (64 hex characters -> 32 bytes)
	pubKeyHex := strings.TrimSpace(publicKeyHex)
	if len(pubKeyHex) != 64 {
		return nil, ErrInvalidPublicKey
	}
	pubKeyBytes, err := hex.DecodeString(pubKeyHex)
	if err != nil || len(pubKeyBytes) != ed25519.PublicKeySize {
		return nil, ErrInvalidPublicKey
	}

	// 2. Validate token structure
	token = strings.TrimSpace(token)
	if token == "" {
		return nil, ErrInvalidFormat
	}

	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return nil, ErrInvalidFormat
	}

	headerPart := parts[0]
	sigPart := parts[1]

	if !strings.HasPrefix(headerPart, "LIC-") {
		return nil, ErrInvalidFormat
	}

	headerSubparts := strings.SplitN(headerPart, "-", 3)
	if len(headerSubparts) != 3 || headerSubparts[0] != "LIC" || headerSubparts[1] == "" || headerSubparts[2] == "" {
		return nil, ErrInvalidFormat
	}

	headerTier := headerSubparts[1]
	payloadB64 := headerSubparts[2]

	// 3. Decode base64 payload
	payloadBytes, err := decodeBase64(payloadB64)
	if err != nil || len(payloadBytes) == 0 {
		return nil, ErrInvalidFormat
	}

	// 4. Parse JSON payload
	var payload LicensePayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		return nil, ErrInvalidFormat
	}

	// Verify tier consistency if specified in JSON payload
	if payload.Tier != "" && !strings.EqualFold(payload.Tier, headerTier) {
		return nil, ErrInvalidFormat
	}

	// 5. Decode signature: RFC 8032 format uses hex (128 chars), also support base64url (86 chars)
	var sigBytes []byte
	sigPart = strings.TrimSpace(sigPart)
	if len(sigPart) == 128 {
		var err error
		sigBytes, err = hex.DecodeString(sigPart)
		if err != nil || len(sigBytes) != ed25519.SignatureSize {
			return nil, ErrInvalidSignature
		}
	} else {
		var err error
		sigBytes, err = decodeBase64(sigPart)
		if err != nil || len(sigBytes) != ed25519.SignatureSize {
			return nil, ErrInvalidSignature
		}
	}

	// 6. Cryptographic signature verification over decoded payload bytes
	if !ed25519.Verify(ed25519.PublicKey(pubKeyBytes), payloadBytes, sigBytes) {
		return nil, ErrInvalidSignature
	}

	// 7. Expiration check
	if payload.ExpiresAt != nil && *payload.ExpiresAt > 0 {
		if at.Unix() > *payload.ExpiresAt {
			return nil, ErrExpired
		}
	}

	return &payload, nil
}

// FormatToken constructs a canonical KeyForge license token string.
// If hexSignature is true, uses RFC 8032 <SIG_HEX>; otherwise uses unpadded base64url.
func FormatToken(tier string, payloadBytes []byte, sigBytes []byte, hexSignature bool) string {
	payloadB64 := base64.RawURLEncoding.EncodeToString(payloadBytes)
	tierUpper := strings.ToUpper(strings.TrimSpace(tier))
	if hexSignature {
		return fmt.Sprintf("LIC-%s-%s.%s", tierUpper, payloadB64, hex.EncodeToString(sigBytes))
	}
	return fmt.Sprintf("LIC-%s-%s.%s", tierUpper, payloadB64, base64.RawURLEncoding.EncodeToString(sigBytes))
}

func decodeBase64(s string) ([]byte, error) {
	// 1. Try unpadded URL-safe base64 (KeyForge standard)
	if b, err := base64.RawURLEncoding.DecodeString(s); err == nil {
		return b, nil
	}
	// 2. Try padded URL-safe base64
	if b, err := base64.URLEncoding.DecodeString(s); err == nil {
		return b, nil
	}
	// 3. Try unpadded standard base64
	if b, err := base64.RawStdEncoding.DecodeString(s); err == nil {
		return b, nil
	}
	// 4. Try padded standard base64
	return base64.StdEncoding.DecodeString(s)
}
