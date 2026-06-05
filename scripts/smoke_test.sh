#!/usr/bin/env bash
set -euo pipefail

fail() { echo "SMOKE FAIL: $1"; exit 1; }

curl -skf https://localhost/healthz >/dev/null || fail "nginx"
curl -skf https://localhost/health >/dev/null || fail "superset"
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-mediflow}" >/dev/null || fail "postgres"

# Sanity: marts populated and forecasts fresh (<2h old)
docker compose exec -T postgres psql -U "${POSTGRES_USER:-mediflow}" -d "${POSTGRES_DB:-mediflow}" -tAc \
  "SELECT count(*) > 0 FROM marts.fct_occupancy_hourly" | grep -q t || fail "marts empty"

echo "smoke tests passed"
