#!/usr/bin/env bash
# Nightly warehouse backup: schema-aware pg_dump + DuckDB file copy.
# Pair with restic for offsite (e.g. Backblaze B2 — free tier covers this).
set -euo pipefail

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="backups/${STAMP}"
mkdir -p "$OUT"

docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-mediflow}" \
  -d "${POSTGRES_DB:-mediflow}" --format=custom \
  --schema=warehouse --schema=marts --schema=ops \
  > "$OUT/warehouse.dump"

[ -f mediflow.duckdb ] && cp mediflow.duckdb "$OUT/"

# Retain 14 days locally
find backups -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
echo "backup complete: $OUT"
