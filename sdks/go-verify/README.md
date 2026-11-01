# keyforge-verify (Go SDK)

The official Go verification SDK for [KeyForge](https://keyforge.dev) — zero-dependency, high-performance offline license verification powered by Ed25519 (RFC 8032).

[![Go Reference](https://pkg.go.dev/badge/github.com/ArceeDev/keyforge/sdks/go-verify.svg)](https://pkg.go.dev/github.com/ArceeDev/keyforge/sdks/go-verify)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Highlights

- **Zero External Dependencies**: Implemented strictly with the Go standard library (`crypto/ed25519`, `encoding/hex`, `encoding/base64`, `encoding/json`).
- **100% Offline**: Validates cryptographic signatures locally without outgoing HTTP requests, phone-home telemetry, or external runtime latency.
- **Sub-Microsecond Verification**: Direct Ed25519 curve verification executes in ~50 microseconds.
- **RFC 8032 Compliant**: Implements the canonical `LIC-<TIER>-<PAYLOAD_B64>.<SIG_HEX>` token specification with backward-compatibility for base64url signatures.
- **Node & Domain Locking**: Built-in support for machine fingerprints, feature entitlement gating, and allowed domain assertions.

---

## Installation

```bash
go get github.com/ArceeDev/keyforge/sdks/go-verify
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

	keyforge "github.com/ArceeDev/keyforge/sdks/go-verify"
)

// Your public key from KeyForge Dashboard (Settings -> Public Keys)
const PublicKeyHex = "d04ab232742bb4ab3a1368bd4615e4e6d0224ab71a016baf8520a332c9778737"

func main() {
	// 1. Read token from environment or config file
	token := os.Getenv("KEYFORGE_LICENSE")
	if token == "" {
		log.Fatal("Missing KEYFORGE_LICENSE environment variable")
	}

	// 2. Verify signature and expiration offline
	license, err := keyforge.Verify(token, PublicKeyHex)
	if err != nil {
		switch {
		case errors.Is(err, keyforge.ErrExpired):
			log.Fatalf("License expired! Please renew your subscription.")
		case errors.Is(err, keyforge.ErrInvalidSignature):
			log.Fatalf("License signature is invalid or has been tampered with!")
		case errors.Is(err, keyforge.ErrInvalidPublicKey):
			log.Fatalf("Configured public key is invalid.")
		case errors.Is(err, keyforge.ErrInvalidFormat):
			log.Fatalf("License token format is malformed.")
		default:
			log.Fatalf("Verification failed: %v", err)
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

	// 5. Check domain lock (if enforced)
	if !license.MatchesDomain("api.mycompany.com") {
		log.Fatalf("License is not authorized for this domain.")
	}
}
```

---

## Token Format Specification

KeyForge tokens are self-contained compact cryptographic strings formatted as:

```text
LIC-<TIER>-<PAYLOAD_B64>.<SIG_HEX>
```

- `LIC`: Fixed protocol prefix.
- `<TIER>`: Tier descriptor (e.g. `PRO`, `STUDIO`, `ENTERPRISE`, `COMMUNITY`).
- `<PAYLOAD_B64>`: URL-safe Base64-encoded canonical JSON claims object.
- `<SIG_HEX>`: 128-character hex-encoded Ed25519 signature (64 bytes) signing the raw decoded payload bytes. Base64url signatures (86 characters) are also accepted transparently.

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

The package provides standard sentinel errors compatible with `errors.Is`:

| Sentinel Error | Description |
| :--- | :--- |
| `ErrInvalidFormat` | Token is empty, missing parts, has invalid prefix, or contains malformed JSON / Base64. |
| `ErrInvalidSignature` | Ed25519 cryptographic verification failed or token claims were modified after signing. |
| `ErrExpired` | The current time is greater than the signed `expires_at` Unix timestamp. |
| `ErrInvalidPublicKey` | The provided public key is not a valid 64-character hexadecimal Ed25519 public key. |

---

## Testing & Deterministic Verification

For automated tests or environments requiring time simulation, use `VerifyAt`:

```go
// Evaluate token validity at a specific point in time
evalTime := time.Unix(1800000000, 0)
payload, err := keyforge.VerifyAt(token, PublicKeyHex, evalTime)
```

To run package tests:

```bash
cd sdks/go-verify
go test -v ./...
```

---

## License

MIT © [ArceeDev / KeyForge](https://github.com/ArceeDev/keyforge)
