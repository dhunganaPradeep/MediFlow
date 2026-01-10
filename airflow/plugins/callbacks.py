"""Failure callback: structured Slack alert per failed task."""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)


def slack_failure_alert(context: dict) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        log.error("SLACK_WEBHOOK_URL unset; failure alert dropped")
        return
    ti = context["task_instance"]
    payload = {
        "text": (
            f":rotating_light: *MediFlow task failed*\n"
            f"DAG: `{ti.dag_id}` Task: `{ti.task_id}`\n"
            f"Run: {context['run_id']} Try: {ti.try_number}\n"
            f"Log: {ti.log_url}"
        )
    }
    req = urllib.request.Request(  # noqa: S310 - https webhook from env
        webhook,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)  # noqa: S310
