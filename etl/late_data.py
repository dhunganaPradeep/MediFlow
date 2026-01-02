"""Late-arriving data policy:

- Each fact table keeps a high-water mark in ops.etl_watermarks.
- Records older than the watermark but within GRACE_HOURS (48h) are loaded
  normally — the idempotent upsert makes this safe, and dbt incremental
  models use a 48h lookback so marts pick them up.
- Records older than 48h are too late: routed to the DLQ with reason
  'late_arrival' for explicit replay/backfill decisions, never silently
  merged into already-published aggregates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text

from etl.dlq import send_to_dlq

GRACE_HOURS = 48


def get_watermark(conn, source_table: str) -> datetime:
    row = conn.execute(
        text("SELECT high_water FROM ops.etl_watermarks WHERE source_table = :t"),
        {"t": source_table},
    ).fetchone()
    return row[0] if row else datetime(2024, 1, 1, tzinfo=timezone.utc)


def set_watermark(conn, source_table: str, ts: datetime) -> None:
    conn.execute(
        text(
            "INSERT INTO ops.etl_watermarks (source_table, high_water) VALUES (:t, :w) "
            "ON CONFLICT (source_table) DO UPDATE SET high_water = GREATEST("
            "ops.etl_watermarks.high_water, EXCLUDED.high_water), updated_at = now()"
        ),
        {"t": source_table, "w": ts},
    )


def split_late(conn, df: pd.DataFrame, ts_col: str, source_table: str) -> pd.DataFrame:
    """Return on-time + in-grace rows; ship too-late rows to the DLQ."""
    watermark = get_watermark(conn, source_table)
    cutoff = watermark - timedelta(hours=GRACE_HOURS)
    ts = pd.to_datetime(df[ts_col], utc=True)
    too_late = df[ts < cutoff]
    for row in too_late.to_dict(orient="records"):
        send_to_dlq(conn, source_table, row, "late_arrival: older than 48h grace window")
    keep = df[ts >= cutoff]
    if not keep.empty:
        set_watermark(conn, source_table, ts.max().to_pydatetime())
    return keep
