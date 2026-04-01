"""HashiCorp Vault client via hvac, AppRole auth.

Secret paths:
    secret/mediflow/db    -> {username, password}
    secret/mediflow/hmac  -> {key}
    secret/mediflow/smtp  -> {host, port, user, password}
"""

from __future__ import annotations

import os
from functools import lru_cache

import hvac


@lru_cache(maxsize=1)
def _client() -> hvac.Client:
    client = hvac.Client(url=os.environ.get("VAULT_ADDR", "http://vault:8200"))
    client.auth.approle.login(
        role_id=os.environ["VAULT_ROLE_ID"],
        secret_id=os.environ["VAULT_SECRET_ID"],
    )
    if not client.is_authenticated():
        raise RuntimeError("Vault AppRole authentication failed")
    return client


def get_secret(path: str, field: str) -> str:
    """path example: 'secret/data/mediflow/db'. KV v2 read."""
    mount, _, rel = path.partition("/data/")
    resp = _client().secrets.kv.v2.read_secret_version(path=rel, mount_point=mount)
    return resp["data"]["data"][field]
