# KeyFlint production runbook

Single Fly machine (`keyflint-gateway`, cdg) + SQLite on volume `keyforge_data` + Litestream → R2.
Do not scale horizontally (SQLite = one writer).

## Release → deploy (≈10 min, no laptop needed)
1. Merge to `main`, tag `vX.Y.Z` → `release.yml` runs gates and pushes `ghcr.io/arceedev/keyflint:X.Y.Z` (+ SBOM/provenance).
2. Actions → **Deploy to Fly.io** → version `X.Y.Z` → approve the `production` environment.
3. The job runs `scripts/smoke_prod.py` (retries ~3 min). Red = roll back (below).

One-time: `fly tokens create deploy -a keyflint-gateway` → repo secret `FLY_API_TOKEN`; create environment `production` with you as required reviewer.

## Rollback (≈3 min)
Run **Deploy to Fly.io** with the previous version. Schema migrations are additive; never roll back past a release whose notes say otherwise.

## Monitoring
| Signal | Where | Action |
|---|---|---|
| Uptime, health, backup, landing | `monitor.yml` every ~15 min → issue labelled `outage` | Read issue, `fly logs -a keyflint-gateway`, roll back if a deploy caused it |
| Backup heartbeat | healthchecks.io (`BACKUP_HEARTBEAT_URL`) | `RESTORE_DRILL.md` |
| Business alerts | `OPS_ALERT_EMAIL` (tier_unresolved, missing email, ambiguous refund, webhook crash) | Resolve by hand in Stripe / `resend-license` |
| Machine health | Fly `/readyz` check | Fly restarts the machine |

Local check any time: `python scripts/smoke_prod.py` (add `--json` for machine output).

## Incidents
- **Gateway down**: licenses keep verifying offline in customers' apps (Ed25519); only activation, metering and webhooks stop. Stripe retries webhooks for 3 days, so no purchase is lost if fixed within that window.
- **Backup failed**: do not deploy; follow `RESTORE_DRILL.md` to verify the replica.
- **Signing key leak**: rotate with a new `kid` (v1.1+), publish the new public key, revoke the old kid in SDK configs. Keep the private key only in a password manager / encrypted USB, never in plain files.

## Capacity (estimate, unverified load test)
256 MB shared-cpu-1x handles SQLite writes in the low hundreds/s; first bottleneck is memory. Upgrade path: `fly scale memory 512` (~+$2/month) before anything else.
