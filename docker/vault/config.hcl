ui = true

disable_mlock = true

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1   # TLS terminates at nginx; vault is backend-network only
}

# Bootstrap (once, documented in docs/security.md):
#   vault operator init -key-shares=3 -key-threshold=2
#   vault secrets enable -path=secret kv-v2
#   vault kv put secret/mediflow/db username=mediflow password=<strong>
#   vault kv put secret/mediflow/hmac key=<openssl rand -hex 32>
#   vault kv put secret/mediflow/smtp host=... user=... password=...
#   vault auth enable approle
#   vault write auth/approle/role/mediflow-etl token_policies=mediflow-read \
#     secret_id_ttl=90d token_ttl=1h
