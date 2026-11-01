// Package keyforge provides offline Ed25519 license verification for KeyForge tokens.
//
// Zero external dependencies (Go standard library only). Behaviour is conformant with the
// shared test vectors in sdks/vectors/vectors.json, the npm package and the PyPI package:
// same token grammar, same checks, same order, same error codes.
package keyforge

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// ClockSkewLeewaySeconds is the tolerated difference between the issuer clock and the local
// clock for the signed issued_at claim.
const ClockSkewLeewaySeconds = 300

// Error codes, identical across the Go, JS and Python SDKs.
const (
	CodeEmptyToken               = "ERR_EMPTY_TOKEN"
	CodeInvalidTokenFormat       = "ERR_INVALID_TOKEN_FORMAT"
	CodeInvalidTokenPrefix       = "ERR_INVALID_TOKEN_PREFIX"
	CodeInvalidPublicKey         = "ERR_INVALID_PUBLIC_KEY"
	CodeMalformedBase64Payload   = "ERR_MALFORMED_BASE64_PAYLOAD"
	CodeMalformedBase64Signature = "ERR_MALFORMED_BASE64_SIGNATURE"
	CodeInvalidSignatureLength   = "ERR_INVALID_SIGNATURE_LENGTH"
	CodeSignatureTampered        = "ERR_SIGNATURE_TAMPERED"
	CodeMalformedJSONPayload     = "ERR_MALFORMED_JSON_PAYLOAD"
	CodeInvalidPayloadStructure  = "ERR_INVALID_PAYLOAD_STRUCTURE"
	CodeTierMismatch             = "ERR_TIER_MISMATCH"
	CodeMalformedExpiration      = "ERR_MALFORMED_EXPIRATION"
	CodeLicenseExpired           = "ERR_LICENSE_EXPIRED"
	CodeClockBeforeIssuance      = "ERR_CLOCK_BEFORE_ISSUANCE"
	CodeNodeLockViolation        = "ERR_NODE_LOCK_VIOLATION"
	CodeDomainLockViolation      = "ERR_DOMAIN_LOCK_VIOLATION"
	CodeUnknownKID               = "ERR_UNKNOWN_KID"
)

// Sentinel errors for errors.Is. Every *VerifyError matches exactly one of them.
var (
	ErrInvalidFormat       = errors.New("keyforge: invalid license token format")
	ErrInvalidSignature    = errors.New("keyforge: invalid or tampered signature")
	ErrExpired             = errors.New("keyforge: license has expired")
	ErrInvalidPublicKey    = errors.New("keyforge: invalid ed25519 public key")
	ErrClockBeforeIssuance = errors.New("keyforge: local clock is before token issuance")
	ErrNodeLockViolation   = errors.New("keyforge: machine lock violation")
	ErrDomainLockViolation = errors.New("keyforge: domain lock violation")
	ErrUnknownKID          = errors.New("keyforge: token kid is not in the trusted key ring")
)

// VerifyError carries the cross-SDK error code. Use errors.Is with the sentinels above, or
// errors.As to read Code.
type VerifyError struct{ Code string }

func (e *VerifyError) Error() string { return "keyforge: " + e.Code }

// Is maps the code to its sentinel.
func (e *VerifyError) Is(target error) bool { return sentinelFor(e.Code) == target }

func sentinelFor(code string) error {
	switch code {
	case CodeInvalidPublicKey:
		return ErrInvalidPublicKey
	case CodeMalformedBase64Signature, CodeInvalidSignatureLength, CodeSignatureTampered:
		return ErrInvalidSignature
	case CodeLicenseExpired:
		return ErrExpired
	case CodeClockBeforeIssuance:
		return ErrClockBeforeIssuance
	case CodeNodeLockViolation:
		return ErrNodeLockViolation
	case CodeDomainLockViolation:
		return ErrDomainLockViolation
	case CodeUnknownKID:
		return ErrUnknownKID
	default:
		return ErrInvalidFormat
	}
}

// Code returns the cross-SDK error code of err, or "" when err is not a *VerifyError.
func Code(err error) string {
	var ve *VerifyError
	if errors.As(err, &ve) {
		return ve.Code
	}
	return ""
}

func fail(code string) error { return &VerifyError{Code: code} }

// LicensePayload holds the verified claims. Raw keeps every signed claim as decoded JSON.
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

	// KeyID is the ring entry that verified the token ("" for a single key, the index for a list).
	KeyID string                 `json:"-"`
	Raw   map[string]interface{} `json:"-"`
}

// IsExpired reports whether the license has expired at the given time (nil ExpiresAt = perpetual).
func (p *LicensePayload) IsExpired(at time.Time) bool {
	return p != nil && p.ExpiresAt != nil && at.Unix() > *p.ExpiresAt
}

// HasFeature reports whether the license includes the feature entitlement.
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

// MatchesDomain reports whether domain is allowed by the claims (empty list allows any).
// Same normalisation as verification: case, trailing dot, :port, IDNA punycode (lowercase
// only; full Unicode nameprep would need a dependency).
func (p *LicensePayload) MatchesDomain(domain string) bool {
	return p != nil && matchesAllowedDomains(p.AllowedDomains, domain)
}

// Options tunes verification. Zero value: now, no machine lock, no domain lock.
type Options struct {
	Now       time.Time // zero = time.Now()
	MachineID string    // local machine id; required when the token is machine-locked
	Domain    string    // caller host; required when the token has allowed_domains
}

// Verify checks token against one hex Ed25519 public key at the current time.
func Verify(token, publicKeyHex string) (*LicensePayload, error) {
	return VerifyWithOptions(token, publicKeyHex, Options{})
}

// VerifyAt checks token against one key at a fixed time (deterministic tests).
func VerifyAt(token, publicKeyHex string, at time.Time) (*LicensePayload, error) {
	return VerifyWithOptions(token, publicKeyHex, Options{Now: at})
}

// VerifyWithOptions checks token against one key with machine/domain locks.
func VerifyWithOptions(token, publicKeyHex string, opts Options) (*LicensePayload, error) {
	if _, ok := parseKey(publicKeyHex); !ok {
		return nil, structuralOr(token, CodeInvalidPublicKey)
	}
	return verifyRing(token, []ringEntry{{"", publicKeyHex}}, opts)
}

// VerifyWithKeys tries every key in the list (keys carry no names, so kid is not used to select).
func VerifyWithKeys(token string, publicKeysHex []string, opts Options) (*LicensePayload, error) {
	ring := make([]ringEntry, 0, len(publicKeysHex))
	for i, k := range publicKeysHex {
		if _, ok := parseKey(k); !ok {
			return nil, structuralOr(token, CodeInvalidPublicKey)
		}
		ring = append(ring, ringEntry{strconv.Itoa(i), k})
	}
	if len(ring) == 0 {
		return nil, structuralOr(token, CodeInvalidPublicKey)
	}
	return verifyRing(token, ring, opts)
}

// VerifyWithKeyRing takes {kid: hex}. A token with a signed kid is checked only against that
// key (ERR_UNKNOWN_KID when absent); tokens without kid (v1.0) are tried against every key.
func VerifyWithKeyRing(token string, ring map[string]string, opts Options) (*LicensePayload, error) {
	ids := make([]string, 0, len(ring))
	for id, k := range ring {
		if _, ok := parseKey(k); !ok {
			return nil, structuralOr(token, CodeInvalidPublicKey)
		}
		ids = append(ids, id)
	}
	if len(ids) == 0 {
		return nil, structuralOr(token, CodeInvalidPublicKey)
	}
	sort.Strings(ids)
	entries := make([]ringEntry, 0, len(ids))
	for _, id := range ids {
		entries = append(entries, ringEntry{id, ring[id]})
	}
	if kid, ok := peekKID(token); ok {
		k, found := ring[kid]
		if !found {
			_, err := validateOffline(token, entries[0].hex, opts)
			if c := Code(err); preSignature[c] {
				return nil, err
			}
			return nil, fail(CodeUnknownKID)
		}
		entries = []ringEntry{{kid, k}}
	}
	return verifyRing(token, entries, opts)
}

type ringEntry struct{ id, hex string }

var preSignature = map[string]bool{
	CodeEmptyToken: true, CodeInvalidTokenFormat: true, CodeInvalidTokenPrefix: true,
	CodeInvalidPublicKey: true, CodeMalformedBase64Payload: true,
	CodeMalformedBase64Signature: true, CodeInvalidSignatureLength: true,
}

func verifyRing(token string, ring []ringEntry, opts Options) (*LicensePayload, error) {
	for _, e := range ring {
		p, err := validateOffline(token, e.hex, opts)
		if Code(err) == CodeSignatureTampered {
			continue
		}
		if err != nil {
			return nil, err
		}
		p.KeyID = e.id
		return p, nil
	}
	return nil, fail(CodeSignatureTampered)
}

// structuralOr reports a token structure error first (same precedence as the other SDKs).
func structuralOr(token, code string) error {
	if c := structuralCode(token); c != "" {
		return fail(c)
	}
	return fail(code)
}

func structuralCode(token string) string {
	if token == "" {
		return CodeEmptyToken
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		return CodeInvalidTokenFormat
	}
	if !strings.HasPrefix(parts[0], "LIC-") {
		return CodeInvalidTokenPrefix
	}
	sub := strings.SplitN(parts[0], "-", 3)
	if len(sub) != 3 || sub[1] == "" || sub[2] == "" {
		return CodeInvalidTokenFormat
	}
	return ""
}

func parseKey(h string) ([]byte, bool) {
	b, err := hex.DecodeString(strings.TrimSpace(h))
	return b, err == nil && len(b) == ed25519.PublicKeySize
}

var b64url = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

func decodeB64URL(s string) ([]byte, error) {
	if !b64url.MatchString(s) {
		return nil, errors.New("bad base64url")
	}
	return base64.RawURLEncoding.DecodeString(s)
}

func peekKID(token string) (string, bool) {
	head := strings.SplitN(token, ".", 2)[0]
	sub := strings.SplitN(head, "-", 3)
	if len(sub) != 3 {
		return "", false
	}
	raw, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(sub[2], "="))
	if err != nil {
		return "", false
	}
	var m map[string]interface{}
	if json.Unmarshal(raw, &m) != nil {
		return "", false
	}
	kid, ok := m["kid"].(string)
	return kid, ok
}

func validateOffline(token, publicKeyHex string, opts Options) (*LicensePayload, error) {
	if c := structuralCode(token); c != "" {
		return nil, fail(c)
	}
	parts := strings.Split(token, ".")
	sub := strings.SplitN(parts[0], "-", 3)
	headerTier, payloadB64, sigB64 := sub[1], sub[2], parts[1]

	pub, ok := parseKey(publicKeyHex)
	if !ok {
		return nil, fail(CodeInvalidPublicKey)
	}
	payloadBytes, err := decodeB64URL(payloadB64)
	if err != nil {
		return nil, fail(CodeMalformedBase64Payload)
	}
	sig, err := decodeB64URL(sigB64)
	if err != nil {
		return nil, fail(CodeMalformedBase64Signature)
	}
	if len(sig) != ed25519.SignatureSize {
		return nil, fail(CodeInvalidSignatureLength)
	}
	if !strictVerify(pub, payloadBytes, sig) {
		return nil, fail(CodeSignatureTampered)
	}

	var anyPayload interface{}
	dec := json.NewDecoder(bytes.NewReader(payloadBytes))
	dec.UseNumber()
	var trailing interface{}
	if err := dec.Decode(&anyPayload); err != nil || dec.Decode(&trailing) != io.EOF {
		return nil, fail(CodeMalformedJSONPayload)
	}
	raw, ok := anyPayload.(map[string]interface{})
	if !ok {
		return nil, fail(CodeInvalidPayloadStructure)
	}

	tier, _ := raw["tier"].(string)
	if _, isStr := raw["tier"].(string); !isStr || !strings.EqualFold(tier, headerTier) {
		return nil, fail(CodeTierMismatch)
	}

	now := opts.Now
	if now.IsZero() {
		now = time.Now()
	}
	nowF := float64(now.Unix())
	p := &LicensePayload{Tier: tier, Raw: raw}

	if v, present := raw["expires_at"]; present && v != nil {
		n, isNum := v.(json.Number)
		f, ferr := n.Float64()
		if !isNum || ferr != nil {
			return nil, fail(CodeMalformedExpiration)
		}
		if nowF > f {
			return nil, fail(CodeLicenseExpired)
		}
		e := int64(f)
		p.ExpiresAt = &e
	}
	if n, isNum := raw["issued_at"].(json.Number); isNum {
		if f, ferr := n.Float64(); ferr == nil {
			if nowF+ClockSkewLeewaySeconds < f {
				return nil, fail(CodeClockBeforeIssuance)
			}
			i := int64(f)
			p.IssuedAt = &i
		}
	}

	if v, present := raw["machine_id"]; present && v != nil {
		s, isStr := v.(string)
		if !isStr {
			return nil, fail(CodeInvalidPayloadStructure)
		}
		p.MachineID = s
	}
	locked := strings.ToLower(strings.TrimSpace(p.MachineID))
	expected := strings.ToLower(strings.TrimSpace(opts.MachineID))
	if locked != expected {
		return nil, fail(CodeNodeLockViolation)
	}

	if v, present := raw["allowed_domains"]; present && v != nil {
		list, isList := v.([]interface{})
		if !isList {
			return nil, fail(CodeInvalidPayloadStructure)
		}
		for _, d := range list {
			s, isStr := d.(string)
			if !isStr {
				return nil, fail(CodeInvalidPayloadStructure)
			}
			p.AllowedDomains = append(p.AllowedDomains, s)
		}
		if len(p.AllowedDomains) > 0 && !matchesAllowedDomains(p.AllowedDomains, opts.Domain) {
			return nil, fail(CodeDomainLockViolation)
		}
	}

	p.LicenseID, _ = raw["license_id"].(string)
	p.Email, _ = raw["email"].(string)
	p.CustomerID, _ = raw["customer_id"].(string)
	p.KID, _ = raw["kid"].(string)
	p.Metadata, _ = raw["metadata"].(map[string]interface{})
	if fs, isList := raw["features"].([]interface{}); isList {
		for _, f := range fs {
			if s, isStr := f.(string); isStr {
				p.Features = append(p.Features, s)
			}
		}
	}
	return p, nil
}

var fieldP = new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 255), big.NewInt(19))

// canonicalPoint rejects encodings that RFC 8032 decoding refuses: y >= p, and x = 0 with
// the sign bit set (y = 1 or y = p-1). crypto/ed25519 checks s < L and curve membership.
func canonicalPoint(enc []byte) bool {
	le := make([]byte, 32)
	copy(le, enc)
	sign := le[31] >> 7
	le[31] &= 0x7f
	for i, j := 0, 31; i < j; i, j = i+1, j-1 {
		le[i], le[j] = le[j], le[i]
	}
	y := new(big.Int).SetBytes(le)
	if y.Cmp(fieldP) >= 0 {
		return false
	}
	if sign == 1 && (y.Cmp(big.NewInt(1)) == 0 || y.Cmp(new(big.Int).Sub(fieldP, big.NewInt(1))) == 0) {
		return false
	}
	return true
}

func strictVerify(pub, msg, sig []byte) bool {
	if !canonicalPoint(pub) || !canonicalPoint(sig[:32]) {
		return false
	}
	return ed25519.Verify(ed25519.PublicKey(pub), msg, sig)
}

var badHostChars = "/\\@?# \t\r\n"

func normalizeHost(raw string, allowWildcard bool) string {
	s := strings.TrimSpace(raw)
	if s == "" || strings.ContainsAny(s, badHostChars) {
		return ""
	}
	wildcard := false
	if strings.HasPrefix(s, "*.") {
		if !allowWildcard {
			return ""
		}
		wildcard, s = true, s[2:]
	} else if strings.Contains(s, "*") {
		return ""
	}
	if i := strings.LastIndex(s, ":"); i >= 0 {
		port := s[i+1:]
		n, err := strconv.Atoi(port)
		if port == "" || err != nil || strings.ContainsAny(port, "+-") || n < 1 || n > 65535 {
			return ""
		}
		s = s[:i]
	}
	s = strings.TrimRight(s, ".")
	if s == "" || strings.HasPrefix(s, ".") || strings.Contains(s, "..") {
		return ""
	}
	labels := strings.Split(s, ".")
	if wildcard && len(labels) < 2 {
		return ""
	}
	for i, l := range labels {
		if l == "" {
			return ""
		}
		if !isASCII(l) {
			enc, ok := punycodeLabel(strings.ToLower(l))
			if !ok {
				return ""
			}
			l = enc
		}
		if len(l) > 63 || l[0] == '-' || l[len(l)-1] == '-' {
			return ""
		}
		for _, ch := range []byte(l) {
			alnum := (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9')
			if !alnum && ch != '-' {
				return ""
			}
		}
		labels[i] = strings.ToLower(l)
	}
	out := strings.Join(labels, ".")
	if wildcard {
		return "*." + out
	}
	return out
}

func matchesAllowedDomains(allowed []string, domain string) bool {
	if len(allowed) == 0 {
		return true
	}
	cand := normalizeHost(domain, false)
	if cand == "" {
		return false
	}
	for _, pattern := range allowed {
		pat := normalizeHost(pattern, true)
		if pat == "" {
			continue
		}
		if pat == cand {
			return true
		}
		if strings.HasPrefix(pat, "*.") {
			suffix := pat[2:]
			if strings.Contains(suffix, ".") && (cand == suffix || strings.HasSuffix(cand, "."+suffix)) {
				return true
			}
		}
	}
	return false
}

// FormatToken builds LIC-<TIER>-<base64url(payload)>.<base64url(sig)> (the format the server emits).
func FormatToken(tier string, payloadBytes, sigBytes []byte) string {
	return "LIC-" + strings.ToUpper(strings.TrimSpace(tier)) + "-" +
		base64.RawURLEncoding.EncodeToString(payloadBytes) + "." +
		base64.RawURLEncoding.EncodeToString(sigBytes)
}

func isASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= 0x80 {
			return false
		}
	}
	return true
}

// punycodeLabel encodes one label as "xn--" + RFC 3492 punycode.
func punycodeLabel(label string) (string, bool) {
	const (
		base, tmin, tmax, skew, damp = 36, 1, 26, 38, 700
		initialBias, initialN        = 72, 128
	)
	input := []rune(label)
	var out []byte
	for _, r := range input {
		if r < 0x80 {
			out = append(out, byte(r))
		}
	}
	b := len(out)
	h := b
	if b > 0 {
		out = append(out, '-')
	}
	digit := func(d int) byte {
		if d < 26 {
			return byte('a' + d)
		}
		return byte('0' + d - 26)
	}
	adapt := func(delta, numPoints int, first bool) int {
		if first {
			delta /= damp
		} else {
			delta /= 2
		}
		delta += delta / numPoints
		k := 0
		for delta > ((base-tmin)*tmax)/2 {
			delta /= base - tmin
			k += base
		}
		return k + (base-tmin+1)*delta/(delta+skew)
	}
	n, delta, bias := initialN, 0, initialBias
	for h < len(input) {
		m := int(^uint(0) >> 1)
		for _, r := range input {
			if int(r) >= n && int(r) < m {
				m = int(r)
			}
		}
		if m-n > (int(^uint32(0)>>1)-delta)/(h+1) {
			return "", false
		}
		delta += (m - n) * (h + 1)
		n = m
		for _, r := range input {
			if int(r) < n {
				delta++
			}
			if int(r) == n {
				q := delta
				for k := base; ; k += base {
					t := k - bias
					if t < tmin {
						t = tmin
					} else if t > tmax {
						t = tmax
					}
					if q < t {
						break
					}
					out = append(out, digit(t+(q-t)%(base-t)))
					q = (q - t) / (base - t)
				}
				out = append(out, digit(q))
				bias = adapt(delta, h+1, h == b)
				delta = 0
				h++
			}
		}
		delta++
		n++
	}
	return "xn--" + string(out), true
}
