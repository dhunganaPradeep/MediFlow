"""Single place for warehouse connections. Credentials from Vault, env fallback."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def warehouse_engine() -> Engine:
    try:
        from security.vault_client import get_secret

        user = get_secret("secret/data/mediflow/db", "username")
        password = get_secret("secret/data/mediflow/db", "password")
    except Exception:
        user = os.environ["POSTGRES_USER"]
        password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "mediflow")
    return create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}",
        pool_pre_ping=True,
    )
