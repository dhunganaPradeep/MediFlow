"""forecast_predict (@hourly): inference with active models, write to
ops.forecast_predictions.

forecast_retrain: fires when rolling 7-day MAPE breaches threshold (15%),
checked hourly after prediction; retrains, registers, and promotes only if
the new model beats the old on holdout.

dlq_replay (@daily): one retry for quarantined records."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.operators.empty import EmptyOperator

sys.path.append("/opt/airflow")
from plugins.callbacks import slack_failure_alert  # noqa: E402

DEFAULT_ARGS = {
    "owner": "mediflow",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": slack_failure_alert,
}
MAPE_RETRAIN_THRESHOLD = 0.15


def _predict(**_):
    from forecasting.runner import predict_all

    predict_all()


def _check_drift(**_):
    from forecasting.runner import rolling_mape

    breaches = [m for m, v in rolling_mape(days=7).items() if v > MAPE_RETRAIN_THRESHOLD]
    return "trigger_retrain" if breaches else "no_retrain"


def _retrain(**_):
    from forecasting.runner import retrain_all

    retrain_all(promote_if_better=True)


with DAG(
    dag_id="forecast_predict",
    schedule="@hourly",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    max_active_runs=1,
    tags=["ml"],
) as predict_dag:
    predict = PythonOperator(task_id="predict_all_models", python_callable=_predict)
    drift = BranchPythonOperator(task_id="check_mape_drift", python_callable=_check_drift)
    retrain = PythonOperator(task_id="trigger_retrain", python_callable=_retrain)
    skip = EmptyOperator(task_id="no_retrain")
    predict >> drift >> [retrain, skip]


def _replay(**_):
    from etl.db import warehouse_engine
    from etl.dlq import mark, pending
    from etl.load import upsert_event_fact
    import pandas as pd

    engine = warehouse_engine()
    targets = {
        "warehouse.fact_admissions": ("source_record_id", "admit_ts"),
        "warehouse.fact_emergency_visits": ("source_record_id", "arrival_ts"),
        "warehouse.fact_ambulance_dispatch": ("source_record_id", "dispatch_ts"),
    }
    with engine.begin() as conn:
        for table, conflict in targets.items():
            for rec in pending(conn, table):
                dlq_id = rec.pop("dlq_id")
                try:
                    upsert_event_fact(engine, pd.DataFrame([rec]), table, conflict)
                    mark(conn, dlq_id, "succeeded")
                except Exception:
                    mark(conn, dlq_id, "failed_again")


with DAG(
    dag_id="dlq_replay",
    schedule="0 4 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["etl"],
) as dlq_dag:
    PythonOperator(task_id="replay_pending", python_callable=_replay)
