"""Idempotent loading. Pattern per task type:

- Event facts (admissions, ER, dispatch): INSERT ... ON CONFLICT
  (source_record_id, <partition ts>) DO NOTHING — reruns are no-ops.
- Snapshot facts (utilization): ON CONFLICT (entity, snapshot_ts)
  DO UPDATE — latest batch wins, still rerun-safe.
- Every row carries batch_id so a bad batch can be surgically deleted.
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.dlq import send_to_dlq

log = logging.getLogger(__name__)


def upsert_event_fact(
    engine: Engine,
    df: pd.DataFrame,
    table: str,
    conflict_cols: tuple[str, str],
    chunk: int = 5_000,
) -> int:
    """Row-chunked idempotent insert; failed chunks fall back to row-by-row
    so single poison records go to the DLQ instead of failing the batch."""
    if df.empty:
        return 0
    cols = list(df.columns)
    stmt = text(
        f"INSERT INTO {table} ({', '.join(cols)}) "  # noqa: S608 - table from internal allowlist
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
    )
    inserted = 0
    records = df.to_dict(orient="records")
    with engine.begin() as conn:
        for start in range(0, len(records), chunk):
            batch = records[start : start + chunk]
            try:
                conn.execute(stmt, batch)
                inserted += len(batch)
            except Exception:
                for row in batch:
                    try:
                        conn.execute(stmt, row)
                        inserted += 1
                    except Exception as exc:
                        send_to_dlq(conn, table, row, str(exc))
    log.info("%s: %d rows processed idempotently", table, inserted)
    return inserted


def upsert_snapshot_fact(engine: Engine, df: pd.DataFrame, table: str) -> int:
    if df.empty:
        return 0
    cols = list(df.columns)
    keys = ("hospital_key", "department_key", "snapshot_ts")
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in keys)
    stmt = text(
        f"INSERT INTO {table} ({', '.join(cols)}) "  # noqa: S608
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}"
    )
    with engine.begin() as conn:
        conn.execute(stmt, df.to_dict(orient="records"))
    return len(df)
