# Threat model and mitigations

| Vector | Mitigation (implemented) |
|---|---|
| SQL injection in ETL | Parameterised SQLAlchemy everywhere; table names from internal allowlists only (`etl/load.py`, `etl/transform.py`) |
| Credential exposure in logs | Vault AppRole at runtime; `AIRFLOW__LOGGING__MASK_SECRETS_IN_LOGS=true`; detect-secrets in pre-commit and CI |
| Re-identification of patients | HMAC-SHA256 pseudo-IDs (key in Vault), age bands not DOB, zip3/birth-year AES-256 via pgcrypto, analyst role denied encrypted columns |
| Unauthorized data access | Keycloak OIDC -> Superset role mapping; Postgres RLS scoping analysts by region; viewers limited to marts |
| Tamper/repudiation | Append-only `ops.audit_log` via SECURITY DEFINER triggers; UPDATE/DELETE revoked even from admin |
| Container escape / lateral movement | `cap_drop: ALL`, `no-new-privileges`, read-only fs + tmpfs where possible, three segmented networks (frontend/backend/data) |
| Transport interception | TLS at nginx (mkcert dev / certbot prod), HSTS, TLS1.2+, internal services never exposed on host ports |
| Insecure deserialization in Airflow | No pickled XComs across tasks; model artifacts written/read only by the worker itself; DAG folder mounted read-only |
| Vulnerable dependencies/images | Trivy (HIGH/CRITICAL, fail-closed) on every PR; pinned image tags |
| Poison records / data-layer DoS | GE validation gate before load; per-row DLQ fallback so one bad record cannot fail a batch |

Vault bootstrap commands are documented in `docker/vault/config.hcl`.
