"""Daily marts build + tests at 02:00 UTC, after the 01:00 etl_core run."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

sys.path.append("/opt/airflow")
from plugins.callbacks import slack_failure_alert  # noqa: E402

with DAG(
    dag_id="dbt_marts",
    schedule="0 2 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args={
        "owner": "mediflow",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "on_failure_callback": slack_failure_alert,
    },
    tags=["dbt"],
) as dag:
    run = BashOperator(
        task_id="dbt_run_int_marts",
        bash_command="cd /opt/dbt/mediflow && dbt run --select intermediate marts --profiles-dir .",
    )
    test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/dbt/mediflow && dbt test --profiles-dir .",
    )
    run >> test
