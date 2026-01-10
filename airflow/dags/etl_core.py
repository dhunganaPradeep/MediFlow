"""Hourly core ETL: generate/ingest -> validate -> idempotent load -> dbt staging.

Retries: 3, exponential backoff from 2 min. Failures page Slack.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

sys.path.append("/opt/airflow")
from plugins.callbacks import slack_failure_alert  # noqa: E402

DEFAULT_ARGS = {
    "owner": "mediflow",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "on_failure_callback": slack_failure_alert,
}


def _extract_and_load(**_):
    from etl.db import warehouse_engine
    from etl.late_data import split_late
    from etl.load import upsert_event_fact, upsert_snapshot_fact
    from etl.transform import staged_frames

    engine = warehouse_engine()
    frames = staged_frames(engine, lookback_hours=10000)  # load all historical data from seed
    with engine.begin() as conn:
        adm = split_late(conn, frames["admissions"], "admit_ts", "fact_admissions")
        er = split_late(conn, frames["er_visits"], "arrival_ts", "fact_emergency_visits")
        amb = split_late(conn, frames["dispatch"], "dispatch_ts", "fact_ambulance_dispatch")
    upsert_event_fact(engine, adm, "warehouse.fact_admissions", ("source_record_id", "admit_ts"))
    upsert_event_fact(engine, er, "warehouse.fact_emergency_visits", ("source_record_id", "arrival_ts"))
    upsert_event_fact(engine, amb, "warehouse.fact_ambulance_dispatch", ("source_record_id", "dispatch_ts"))
    upsert_snapshot_fact(engine, frames["utilization"], "warehouse.fact_resource_utilization")


def _validate(**_):
    """great_expectations checkpoint on the raw micro-batch; raises on failure
    so nothing unvalidated ever reaches the warehouse."""
    import great_expectations as gx

    context = gx.get_context(context_root_dir="/opt/airflow/etl/gx")
    result = context.run_checkpoint(checkpoint_name="raw_hourly")
    if not result.success:
        raise ValueError(f"GE validation failed: {result.list_validation_result_identifiers()}")


with DAG(
    dag_id="etl_core",
    schedule="@hourly",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    max_active_runs=1,
    tags=["etl"],
) as dag:
    validate = PythonOperator(task_id="validate_raw_batch", python_callable=_validate)
    load = PythonOperator(task_id="load_warehouse", python_callable=_extract_and_load)
    dbt_staging = BashOperator(
        task_id="dbt_run_staging",
        bash_command="cd /opt/dbt/mediflow && dbt run --select staging --profiles-dir .",
    )
    validate >> load >> dbt_staging
