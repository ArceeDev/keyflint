# Security policy

## Reporting a vulnerability
Email **support@keyflint.dev** with "SECURITY" in the subject, or open a private report via
GitHub → Security → *Report a vulnerability*. Please do not open a public issue.

We acknowledge within 2 business days and aim to ship a fix for critical issues within 7 days.
We credit reporters in the release notes unless you prefer otherwise.

## Scope
- The gateway (`app/`), the container image `ghcr.io/arceedev/keyflint`, and the verifier SDKs
  (`keyflint-verify` on npm, PyPI and Go).
- The hosted gateway at `licenses.keyflint.dev` (no load or DoS testing, please).

## Supported versions
The latest minor release receives security fixes (currently 1.2.x).
