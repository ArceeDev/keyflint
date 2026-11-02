# keyflint-verify (Go SDK)

The official Go verification SDK for [KeyFlint](https://keyflint.dev) — zero-dependency, high-performance offline license verification powered by Ed25519 (RFC 8032).

[![Go Reference](https://pkg.go.dev/badge/github.com/ArceeDev/keyflint/sdks/go-verify.svg)](https://pkg.go.dev/github.com/ArceeDev/keyflint/sdks/go-verify)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Highlights

- **Zero External Dependencies**: Implemented strictly with the Go standard library (`crypto/ed25519`, `encoding/hex`, `encoding/base64`, `encoding/json`).
- **100% Offline**: Validates cryptographic signatures locally without outgoing HTTP requests, phone-home telemetry, or external runtime latency.
- **Fast**: one Ed25519 verification (tens of microseconds).
- **Strict RFC 8032**: rejects malleable (`s >= L`) and non-canonical point encodings.
- **Cross-SDK conformance**: passes the same `sdks/vectors/vectors.json` as the npm and PyPI packages, with the same `ERR_*` codes.
- **Locks and key rotation**: machine lock, domain lock (port, trailing dot, IDNA), clock-rollback check, and `kid` key rings.

---

## Installation

```bash
go get github.com/ArceeDev/keyflint/sdks/go-verify
```

*Requires Go 1.20 or newer.*

---

## Quickstart

```go
package main

import (
	"errors"
	"fmt"
	"log"
	"os"

	keyflint "github.com/ArceeDev/keyflint/sdks/go-verify"
)

// Your gateway public key: GET /api/v1/licenses/public-key (also in every license email)
const PublicKeyHex = "d04ab232742bb4ab3a1368bd4615e4e6d0224ab71a016baf8520a332c9778737"

func main() {
	// 1. Read token from environment or config file
	token := os.Getenv("KEYFLINT_LICENSE")
	if token == "" {
		log.Fatal("Missing KEYFLINT_LICENSE environment variable")
	}

	// 2. Verify offline (pass MachineID / Domain only if your tokens are locked)
	license, err := keyflint.VerifyWithOptions(token, PublicKeyHex, keyflint.Options{
		Domain: "api.mycompany.com",
	})
	if err != nil {
		switch {
		case errors.Is(err, keyflint.ErrExpired):
			log.Fatalf("License expired! Please renew your subscription.")
		case errors.Is(err, keyflint.ErrInvalidSignature):
			log.Fatalf("License signature is invalid or has been tampered with!")
		case errors.Is(err, keyflint.ErrInvalidPublicKey):
			log.Fatalf("Configured public key is invalid.")
		case errors.Is(err, keyflint.ErrDomainLockViolation):
			log.Fatalf("License is not authorized for this domain.")
		default:
			log.Fatalf("Verification failed: %s", keyflint.Code(err)) // e.g. ERR_INVALID_TOKEN_FORMAT
		}
	}

	// 3. Inspect verified claims
	fmt.Printf("License Verified Successfully!\n")
	fmt.Printf("  Tier:      %s\n", license.Tier)
	fmt.Printf("  Email:     %s\n", license.Email)
	fmt.Printf("  LicenseID: %s\n", license.LicenseID)

	// 4. Gate premium features
	if license.HasFeature("analytics_export") {
		fmt.Println("Feature [analytics_export] enabled.")
	}

}
```

---

## Token Format Specification

KeyFlint tokens are self-contained compact cryptographic strings formatted as:

```text
LIC-<TIER>-<PAYLOAD_B64URL>.<SIG_B64URL>
```

- `LIC`: Fixed protocol prefix.
- `<TIER>`: Tier descriptor (e.g. `PRO`, `STUDIO`, `ENTERPRISE`, `COMMUNITY`).
- `<PAYLOAD_B64URL>`: unpadded base64url of the JSON claims object.
- `<SIG_B64URL>`: unpadded base64url (86 chars) of the 64-byte Ed25519 signature over the decoded payload bytes.

### Payload Claims Schema (`LicensePayload`)

```go
type LicensePayload struct {
    LicenseID      string                 `json:"license_id,omitempty"`
    Tier           string                 `json:"tier"`
    Email          string                 `json:"email,omitempty"`
    CustomerID     string                 `json:"customer_id,omitempty"`
    Features       []string               `json:"features,omitempty"`
    ExpiresAt      *int64                 `json:"expires_at,omitempty"` // Unix epoch; nil = perpetual
    IssuedAt       *int64                 `json:"issued_at,omitempty"`
    MachineID      string                 `json:"machine_id,omitempty"`
    AllowedDomains []string               `json:"allowed_domains,omitempty"`
    KID            string                 `json:"kid,omitempty"`
    Metadata       map[string]interface{} `json:"metadata,omitempty"`
}
```

---

## Error Handling

Every failure is a `*keyflint.VerifyError` whose `Code` is the cross-SDK `ERR_*` code (`keyflint.Code(err)`), and it matches one sentinel with `errors.Is`:

| Sentinel | Codes |
| :--- | :--- |
| `ErrInvalidFormat` | `ERR_EMPTY_TOKEN`, `ERR_INVALID_TOKEN_FORMAT`, `ERR_INVALID_TOKEN_PREFIX`, `ERR_MALFORMED_BASE64_PAYLOAD`, `ERR_MALFORMED_JSON_PAYLOAD`, `ERR_INVALID_PAYLOAD_STRUCTURE`, `ERR_TIER_MISMATCH`, `ERR_MALFORMED_EXPIRATION` |
| `ErrInvalidSignature` | `ERR_SIGNATURE_TAMPERED`, `ERR_MALFORMED_BASE64_SIGNATURE`, `ERR_INVALID_SIGNATURE_LENGTH` |
| `ErrInvalidPublicKey` | `ERR_INVALID_PUBLIC_KEY` |
| `ErrExpired` | `ERR_LICENSE_EXPIRED` |
| `ErrClockBeforeIssuance` | `ERR_CLOCK_BEFORE_ISSUANCE` (local clock > 300 s before `issued_at`) |
| `ErrNodeLockViolation` | `ERR_NODE_LOCK_VIOLATION` (token locked and `Options.MachineID` differs or is empty, or vice versa) |
| `ErrDomainLockViolation` | `ERR_DOMAIN_LOCK_VIOLATION` |
| `ErrUnknownKID` | `ERR_UNKNOWN_KID` (only `VerifyWithKeyRing`) |

## Key rotation

```go
// Tokens with a signed "kid" are checked only against that key; v1.0 tokens try every key.
license, err := keyflint.VerifyWithKeyRing(token, map[string]string{
	"legacy": "d04ab2...8737",
	"k2":     "a09aa5...a4f0",
}, keyflint.Options{})
// license.KeyID == "k2"
```

`VerifyWithKeys(token, []string{...}, opts)` tries every key in order (lists carry no names).

---

## Testing & Deterministic Verification

For tests, fix the clock with `VerifyAt` or `Options.Now`:

```go
// Evaluate token validity at a specific point in time
evalTime := time.Unix(1800000000, 0)
payload, err := keyflint.VerifyAt(token, PublicKeyHex, evalTime)
```

To run package tests:

```bash
cd sdks/go-verify
go test -v ./...
```

---

## License

MIT © [ArceeDev / KeyFlint](https://github.com/ArceeDev/keyflint)
