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
