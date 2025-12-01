# Running MediFlow

Step-by-step instructions for Windows (WSL2), macOS (Intel and Apple Silicon), and Linux (Ubuntu/Debian).

---

## 1. Prerequisites

| Tool | Minimum version | Check with |
|---|---|---|
| Docker Engine / Docker Desktop | Engine 27.0 / Desktop 4.30 | `docker --version` |
| Docker Compose plugin | v2.27 | `docker compose version` |
| Python | 3.11.x | `python3 --version` |
| Git | 2.40 | `git --version` |
| mkcert | 1.4.4 | `mkcert -version` |
| OpenSSL | 3.x | `openssl version` |

Minimum host resources: **8 GB RAM allocated to Docker, 4 CPUs, 20 GB disk**.

### Windows 10/11 (WSL2 + Docker Desktop)

```powershell
# PowerShell as Administrator
wsl --install -d Ubuntu-24.04
wsl --set-default-version 2
```

1. Install Docker Desktop from https://docs.docker.com/desktop/install/windows-install/ and enable **Settings > Resources > WSL Integration > Ubuntu-24.04**.
2. Allocate resources: create `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=10GB
   processors=4
   ```
   then `wsl --shutdown` and restart Docker Desktop.
3. Inside the Ubuntu shell (all remaining commands run here):
   ```bash
   sudo apt update && sudo apt install -y python3.11 python3.11-venv git libnss3-tools
   curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
   chmod +x mkcert-v*-linux-amd64 && sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
   ```
4. **Clone inside the WSL filesystem** (`~/`, not `/mnt/c/`) — 10x faster I/O and avoids file-permission issues.

### macOS (Intel and Apple Silicon)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install --cask docker        # Docker Desktop
brew install python@3.11 git mkcert nss
open -a Docker                    # start Docker Desktop, allocate 8GB+ in Settings > Resources
```

Apple Silicon note: every image used here ships arm64 builds. If any service
fails with `exec format error`, add `platform: linux/amd64` to that service
in `docker-compose.yml` (Rosetta emulation; expect it only with third-party
image swaps).

### Linux (Ubuntu 22.04/24.04, Debian 12)

```bash
sudo apt update && sudo apt install -y ca-certificates curl git python3.11 python3.11-venv libnss3-tools
# Docker Engine + Compose plugin (official repo)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
# mkcert
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
chmod +x mkcert-v*-linux-amd64 && sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
```

### Linux (Arch Linux and Arch-based distros)

```bash
sudo pacman -Sy ca-certificates curl git python base-devel
# Docker (from official repos)
sudo pacman -S docker docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER && newgrp docker
# Python 3.11 venv support
sudo pacman -S python
# mkcert (from AUR) or download binary
sudo pacman -S mkcert
# Alternative: download binary if not in repos
# curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
# chmod +x mkcert-v*-linux-amd64 && sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
```

**Note:** On Arch Linux:
- `python` refers to Python 3.x (Arch dropped Python 2 support)
- If you need specifically Python 3.11 from AUR: `yay -S python311` or `paru -S python311`
- Docker may need to be started on first boot: `sudo systemctl start docker`
- Ensure you restart your shell or run `newgrp docker` after adding your user to the docker group

---

## 2. Clone and configure

```bash
git clone https://gitlab.com/testing8400624/mediflow.git
cd mediflow
cp .env.example .env
```

Generate real values for `.env` (never commit it):

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install cryptography
python - <<'EOF'
from cryptography.fernet import Fernet
print("AIRFLOW__CORE__FERNET_KEY=" + Fernet.generate_key().decode())
EOF
openssl rand -base64 42   # -> SUPERSET_SECRET_KEY
openssl rand -hex 32      # -> MEDIFLOW_HMAC_KEY
openssl rand -hex 16      # -> POSTGRES_PASSWORD, AIRFLOW_ADMIN_PASSWORD, KEYCLOAK_ADMIN_PASSWORD, GRAFANA_ADMIN_PASSWORD
```

Paste each into `.env`.

## 3. TLS certificates (dev)

```bash
mkcert -install
mkdir -p docker/nginx/certs
mkcert -cert-file docker/nginx/certs/local.pem -key-file docker/nginx/certs/local-key.pem localhost 127.0.0.1
```

## 4. Start the stack (order is handled by compose dependencies)

```bash
docker compose up -d
```

Startup order enforced by healthchecks: `postgres` + `redis` -> `airflow-init`
(runs once, exits 0) -> `airflow-webserver`/`scheduler`/`worker`, `keycloak`
-> `superset` -> `nginx`; `vault`, `prometheus` -> `grafana` in parallel.
First boot takes 3-6 minutes (image pulls + Keycloak realm import).

## 5. One-time initialisation

```bash
# 5a. Vault: init, unseal, seed secrets
docker compose exec vault vault operator init -key-shares=3 -key-threshold=2
#   -> store the 3 unseal keys + root token in a password manager
docker compose exec vault vault operator unseal   # run twice with 2 different keys
docker compose exec -e VAULT_TOKEN=<root-token> vault vault secrets enable -path=secret kv-v2
docker compose exec -e VAULT_TOKEN=<root-token> vault vault kv put secret/mediflow/db username=mediflow password=<POSTGRES_PASSWORD>
docker compose exec -e VAULT_TOKEN=<root-token> vault vault kv put secret/mediflow/hmac key=<MEDIFLOW_HMAC_KEY>

# 5b. Superset: metadata DB, admin, dashboards
docker compose exec postgres psql -U mediflow -c 'CREATE DATABASE superset_meta'
docker compose exec superset superset db upgrade
docker compose exec superset superset fab create-admin --username admin --firstname a --lastname d --email admin@mediflow.local --password <choose>
docker compose exec superset superset init
# Import Dashboards:
# 1. Open Superset in your browser: https://localhost/ (login with admin)
# 2. Go to Settings (top right) -> Import Dashboards
# 3. Upload the `superset/mediflow_assets.zip` file.

# 5c. Keycloak: copy the superset client secret into .env
#   https://localhost/auth > realm 'mediflow' > Clients > superset > Credentials
#   -> KEYCLOAK_SUPERSET_CLIENT_SECRET in .env, then:
docker compose up -d superset
```

## 6. Seed data, build marts, train models

```bash
source .venv/bin/activate && pip install -e .[dev]
set -a && source .env && set +a
POSTGRES_HOST=localhost make seed        # 365 days x 5 hospitals into raw schema
# Airflow UI: enable dags dims_scd2 -> etl_core -> dbt_marts -> forecast_predict, dlq_replay
# or run immediately:
docker compose exec airflow-scheduler airflow dags trigger dims_scd2
docker compose exec airflow-scheduler airflow dags trigger etl_core
docker compose exec airflow-scheduler airflow dags trigger dbt_marts
POSTGRES_HOST=localhost make forecast    # first model training (~5 min)
POSTGRES_HOST=localhost python -m olap.build_duckdb --db mediflow.duckdb
```

## 7. Verify every service

```bash
docker compose ps          # every service: status 'running (healthy)'
curl -k https://localhost/healthz                  # nginx  -> ok
curl -k https://localhost/health                   # superset -> OK
docker compose exec postgres pg_isready -U mediflow  # -> accepting connections
docker compose exec redis redis-cli ping             # -> PONG
curl -s http://localhost:9090/-/healthy              # prometheus (if port published)
docker compose exec vault vault status               # Sealed: false
docker compose logs airflow-scheduler --tail 20      # no tracebacks
bash scripts/smoke_test.sh                           # full end-to-end check
```

## 8. Service URLs and credentials

| Service | URL | Credentials |
|---|---|---|
| Superset (dashboards) | https://localhost/ | Keycloak SSO: `ops-admin` / `er-coordinator` / `health-planner`, temp password `change-on-first-login` (forced reset) or local `admin` from step 5b |
| Keycloak admin | https://localhost/auth/ | `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` from `.env` |
| Airflow | http://localhost:8080 (add `ports: ["8080:8080"]` to airflow-webserver for dev) | `admin` / `AIRFLOW_ADMIN_PASSWORD` |
| Grafana (infra) | https://localhost/grafana/ | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| Vault UI | http://localhost:8200 (backend network; `docker compose port vault 8200` or temp port mapping) | root token from `vault operator init` |
| Prometheus | internal only: `docker compose exec prometheus wget -qO- localhost:9090/-/healthy` | none |
| Postgres | `localhost:5432` (add port mapping for dev) | `POSTGRES_USER` / `POSTGRES_PASSWORD` |

## 9. Common errors and exact fixes

| Symptom | Cause | Fix |
|---|---|---|
| `bind: address already in use` on 443/80 | Host web server running | `sudo lsof -i :443` then stop it, or change nginx ports to `8443:443` |
| `airflow-init` exits non-zero, `relation does not exist` | init raced Postgres first boot | `docker compose up -d airflow-init` again (idempotent) |
| Airflow worker OOM-killed (exit 137) | Docker RAM too low | Allocate >= 8 GB (Docker Desktop Resources / `.wslconfig`) |
| `exec format error` (Apple Silicon) | amd64-only image | add `platform: linux/amd64` to that service |
| Keycloak healthcheck never passes | realm import takes ~90s on first boot | wait; check `docker compose logs keycloak`; confirm `realm-export.json` is valid JSON |
| Superset login loop after SSO | wrong client secret or redirect URI | re-copy secret (step 5c); redirect must be exactly `https://localhost/oauth-authorized/keycloak` |
| `Vault is sealed` after restart | file backend seals on every restart by design | `docker compose exec vault vault operator unseal` x2 |
| `NET::ERR_CERT_AUTHORITY_INVALID` | mkcert CA not trusted in this browser/OS | rerun `mkcert -install`; on WSL2 import the CA (`mkcert -CAROOT`) into Windows cert store |
| `permission denied: /var/run/docker.sock` (Linux) | user not in docker group | `sudo usermod -aG docker $USER && newgrp docker` |
| dbt `relation "raw.admissions" does not exist` | marts run before seeding | run `make seed`, then trigger `dims_scd2` and `etl_core` first |
| GE checkpoint fails on first run | raw schema empty | seed first; the validation gate is supposed to block empty/invalid loads |

## 10. Shutdown / reset

```bash
docker compose down              # stop, keep data
docker compose down -v           # stop and DELETE all volumes (full reset)
make backup                      # before any reset you care about
```
