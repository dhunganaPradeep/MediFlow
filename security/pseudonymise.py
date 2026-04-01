"""Patient ID pseudonymisation: HMAC-SHA256 keyed from Vault.

HMAC (not plain hash) so attackers cannot brute-force MRN -> pseudo-ID
without the key; deterministic so the same patient always maps to the same
pseudo-ID across batches (joins keep working)."""

from __future__ import annotations

import hashlib
import hmac
import os


def _key() -> bytes:
    """Key precedence: Vault (prod) -> env var (dev). Never hardcoded."""
    try:
        from security.vault_client import get_secret

        return get_secret("secret/data/mediflow/hmac", "key").encode()
    except Exception:
        key = os.environ.get("MEDIFLOW_HMAC_KEY")
        if not key:
            raise RuntimeError("No HMAC key: set MEDIFLOW_HMAC_KEY or configure Vault") from None
        return key.encode()


def pseudonymise_patient_id(mrn: str) -> str:
    return hmac.new(_key(), mrn.encode(), hashlib.sha256).hexdigest()
