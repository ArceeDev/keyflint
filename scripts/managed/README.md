# KeyFlint Managed: runbook

One isolated Fly.io instance per customer (its own app, volume, signing key and backup prefix).
There is no multi-tenancy: a fault or a leak in one instance never touches another.

## One-time setup

1. **Fly.io**: account with billing, then `fly auth login`.
2. **Cloudflare R2** (or any S3): a private bucket, e.g. `kf-backups`, plus an API token with
   *Object Read & Write* on that bucket only.
3. **Public image**: `ghcr.io/arceedev/keyflint:<version>` must be public (GHCR → Package settings).
4. Shell environment (do not commit it):

   ```bash
   export KF_BACKUP_BUCKET=kf-backups
   export KF_BACKUP_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
   export LITESTREAM_ACCESS_KEY_ID=...        # R2 token
   export LITESTREAM_SECRET_ACCESS_KEY=...
   ```

5. **Vault**: `~/.keyforge-managed/` holds each customer's master key (`<slug>.env`, 0600).
   Back it up encrypted (password manager or an encrypted disk). Without the vault AND without
   Fly, a customer's signing key cannot be recovered.

## New customer (after a Managed payment)

```bash
python scripts/managed/kf_managed.py --dry-run create acme --region cdg --domain lic.acme.com
python scripts/managed/kf_managed.py create acme --region cdg --domain lic.acme.com \
  --image ghcr.io/arceedev/keyflint:1.2.2
```

Send the customer: the URL, the **public key** (printed in the output) and the **admin key**
(in `~/.keyforge-managed/acme.env`) over a secure channel (e.g. a one-time link). If they use a
custom domain: a `CNAME lic.acme.com -> kf-acme.fly.dev`.

When the customer gives you their webhook secret:
`fly secrets set STRIPE_WEBHOOK_SECRET=whsec_... --app kf-acme` (also update the vault).

## Operations

| Task | Command |
|---|---|
| List customers | `kf_managed.py list` |
| Status | `kf_managed.py status acme` |
| New version for one / for all | `kf_managed.py upgrade acme --image ...:1.2.1` / `upgrade --all --image ...` |
| Logs | `fly logs --app kf-acme` |
| Monthly restore drill | `python scripts/e2e_backup.py --s3-endpoint $KF_BACKUP_ENDPOINT --bucket kf-backups` |

**Real recovery** (lost volume): `fly volumes create keyforge_data --size 1 --region cdg --app kf-acme --yes`
and `fly deploy --app kf-acme --config fly.toml --image ... --ha=false`. When it boots with no DB,
the instance restores from `<bucket>/acme`. The key is a Fly secret, so it stays the same and
every license keeps verifying. If the restore fails, the instance refuses to start (fail closed)
instead of booting empty.

## Cancellation

1. Cancel the subscription and give a grace period (e.g. 7 days) for the customer to migrate to self-hosted.
2. `kf_managed.py destroy acme --confirm acme` (archives the vault as `*.destroyed-*`).
3. GDPR erasure: delete the `acme/` prefix from the bucket and the archived vault files.

## Before selling (not technical)

- **DPA / data processing agreement**: you host your customers' data (emails, licenses).
  You need a processing agreement and a privacy policy. Fly and Cloudflare are sub-processors.
- **Costs** *(estimated, not verified)*: Fly shared-cpu-1x 256 MB + 1 GB volume ≈ $2–3/month,
  R2 has a free tier of 10 GB. At $29/month the gross margin is about 85–90%.
- **SQLite = 1 machine**: never `fly scale count` above 1.
- Provisioning is manual on purpose: the payment webhooks are not touched.
