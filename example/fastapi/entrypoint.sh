#!/usr/bin/env bash
set -e

echo "Waiting for Postgres at ${DB_HOST:-localhost}:${DB_PORT:-5432}..."
python - <<'PY'
import os, time, socket
host, port = os.environ.get("DB_HOST", "localhost"), int(os.environ.get("DB_PORT", "5432"))
for _ in range(60):
    try:
        socket.create_connection((host, port), timeout=1).close()
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("Postgres did not become available in time")
PY

python -m app.seed

exec "$@"
