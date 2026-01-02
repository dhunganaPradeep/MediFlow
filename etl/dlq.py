"""Dead letter queue: poison records are quarantined with their error,
replayed daily by the dlq_replay DAG, and marked failed_again after a
second strike (human triage from there)."""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)


def send_to_dlq(conn, source_table: str, payload: dict, reason: str) -> None:
    conn.execute(
        text(
            "INSERT INTO ops.dead_letter_queue (source_table, batch_id, payload, error_reason) "
            "VALUES (:t, :b, :p, :r)"
        ),
        {
            "t": source_table,
            "b": str(payload.get("batch_id", "00000000-0000-0000-0000-000000000000")),
            "p": json.dumps(payload, default=str),
            "r": reason[:2000],
        },
    )
    log.warning("DLQ <- %s: %s", source_table, reason[:120])


def pending(conn, source_table: str) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT dlq_id, payload FROM ops.dead_letter_queue "
            "WHERE source_table = :t AND replay_status = 'pending' LIMIT 1000"
        ),
        {"t": source_table},
    )
    return [{"dlq_id": r.dlq_id, **r.payload} for r in rows]


def mark(conn, dlq_id: int, status: str) -> None:
    conn.execute(
        text(
            "UPDATE ops.dead_letter_queue SET replay_status = :s, replayed_at = now() "
            "WHERE dlq_id = :i"
        ),
        {"s": status, "i": dlq_id},
    )
