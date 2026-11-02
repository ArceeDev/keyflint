# Restore drill (Litestream → temp file)

Proves the R2 replica can rebuild the database without touching production. Read-only for the
live DB; writes only `/tmp/restore.db` on the machine. Last run: 2026-11-02, generation
`bd9a672752339c6b`, counts matched (licenses 2, customers 1), `integrity_check` = `ok`.

The gateway writes its Litestream config to `/tmp/litestream.yml` at boot (`app/bootstrap.py`);
credentials come from the machine's environment, so nothing secret is typed or printed.

```bash
fly ssh console -a keyflint-gateway
```

Inside the machine:

```sh
litestream generations -config /tmp/litestream.yml /app/data/keyforge.db
rm -f /tmp/restore.db
litestream restore -config /tmp/litestream.yml -o /tmp/restore.db /app/data/keyforge.db
python - <<'EOF'
import sqlite3
for p in ("/app/data/keyforge.db", "/tmp/restore.db"):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    counts = {t: c.execute(f"select count(*) from {t}").fetchone()[0]
              for t in ("licenses", "customers", "activations", "usage_events")}
    print(p, counts, c.execute("pragma integrity_check").fetchone()[0])
EOF
rm -f /tmp/restore.db
```

Pass: both lines show the same counts and `ok`. Counts can differ only by writes made in the last
second (sync interval 1s).

Real recovery (lost volume): create a fresh volume and deploy; the container restores from R2
before starting and refuses to start if the restore fails. See the README backup section.

## Retention and alerts

- Retention: `LITESTREAM_RETENTION` (default `720h`): any point in the last 30 days can be restored.
  Snapshots every 24h. Raise it only if you need older restore points; R2 cost is negligible.
- Hourly self-check (`BACKUP_CHECK_INTERVAL_SECONDS`, default 3600): the gateway restores the replica
  to a temp file and checks that `licenses`, `customers` and `webhook_events` are not behind the live
  DB. Result in `GET /api/v1/health` → `backup.status` (`ok` / `failed` / `disabled`); details in
  `fly logs` (`BACKUP VERIFICATION FAILED`).
- Alerting: create a check at healthchecks.io (period 1 hour, grace 2 hours, email notification) and
  set its ping URL as a secret. You get an email if a check fails or if pings stop (machine down,
  R2 credentials revoked, replica stale):

```bash
fly secrets set BACKUP_HEARTBEAT_URL=https://hc-ping.com/<uuid> -a keyflint-gateway
```