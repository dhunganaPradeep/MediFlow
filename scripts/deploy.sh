#!/usr/bin/env bash
# Manual VPS deploy (release.yml automates this on tag push).
set -euo pipefail
git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
bash scripts/smoke_test.sh
