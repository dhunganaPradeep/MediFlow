"""Daily dimension maintenance at 00:30, before etl_core's hourly fact loads.

- dim_department / dim_diagnosis: Type 1 upsert from canonical reference lists.
- dim_patient: insert-only from raw.patients (already pseudonymised upstream).
- dim_hospital: SCD Type 2 from raw.hospitals — close changed rows
  (valid_to = now, is_current = false), insert new versions. Mirrors
  dbt/mediflow/macros/scd2_merge.sql for in-DAG execution.
- dim_staff: same SCD2 pattern from raw.staff when the table exists.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.append("/opt/airflow")
from plugins.callbacks import slack_failure_alert  # noqa: E402

HOSPITAL_TRACKED = ["name", "region", "bed_capacity", "trauma_level"]
STAFF_TRACKED = ["role", "seniority", "fte", "department_id"]


def _scd2_sql(target: str, source: str, nk: str, tracked: list[str]) -> list[str]:
    hash_expr = " || '|' || ".join(f"coalesce({c}::text, '')" for c in tracked)
    cols = ", ".join(tracked)
    src_cols = ", ".join(f"s.{c}" for c in tracked)
    return [
        # 1. close current rows whose tracked attributes changed
        f"""
        UPDATE {target} t
        SET valid_to = now(), is_current = false
        FROM (SELECT {nk}, md5({hash_expr}) AS row_hash FROM {source}) s
        WHERE t.{nk} = s.{nk} AND t.is_current AND t.row_hash <> s.row_hash
        """,
        # 2. insert new versions for changed and brand-new natural keys
        f"""
        INSERT INTO {target} ({nk}, {cols}, row_hash, valid_from, valid_to, is_current)
        SELECT s.{nk}, {src_cols}, md5({hash_expr.replace("coalesce(", "coalesce(s.")}),
               now(), 'infinity', true
        FROM {source} s
        LEFT JOIN {target} t ON t.{nk} = s.{nk} AND t.is_current
        WHERE t.{nk} IS NULL
        """,
    ]


def _upsert_reference_dims(**_):
    from sqlalchemy import text

    from data_generation.generate import DEPARTMENTS, ICD10
    from etl.db import warehouse_engine

    engine = warehouse_engine()
    with engine.begin() as conn:
        for dep_id, name, specialty, beds in DEPARTMENTS:
            conn.execute(
                text(
                    "INSERT INTO warehouse.dim_department (department_id, name, specialty, bed_count) "
                    "VALUES (:i, :n, :s, :b) ON CONFLICT (department_id) DO UPDATE SET "
                    "name = EXCLUDED.name, specialty = EXCLUDED.specialty, bed_count = EXCLUDED.bed_count"
                ),
                {"i": dep_id, "n": name, "s": specialty, "b": beds},
            )
        for code, desc, chapter, chronic in ICD10:
            conn.execute(
                text(
                    "INSERT INTO warehouse.dim_diagnosis (icd10_code, description, chapter, is_chronic) "
                    "VALUES (:c, :d, :ch, :cr) ON CONFLICT (icd10_code) DO UPDATE SET "
                    "description = EXCLUDED.description, chapter = EXCLUDED.chapter, "
                    "is_chronic = EXCLUDED.is_chronic"
                ),
                {"c": code, "d": desc, "ch": chapter, "cr": chronic},
            )


def _upsert_patients(**_):
    from sqlalchemy import text

    from etl.db import warehouse_engine

    engine = warehouse_engine()
    with engine.begin() as conn:
        conn.execute(text("SET app.user = 'airflow:dims_scd2'"))
        conn.execute(
            text(
                "INSERT INTO warehouse.dim_patient (patient_pseudo_id, sex, age_band) "
                "SELECT DISTINCT patient_pseudo_id, sex, age_band FROM raw.patients "
                "ON CONFLICT (patient_pseudo_id) DO NOTHING"
            )
        )


def _scd2_hospitals(**_):
    from sqlalchemy import text

    from etl.db import warehouse_engine

    engine = warehouse_engine()
    with engine.begin() as conn:
        for stmt in _scd2_sql(
            "warehouse.dim_hospital", "raw.hospitals", "hospital_id", HOSPITAL_TRACKED
        ):
            conn.execute(text(stmt))


def _scd2_staff(**_):
    from sqlalchemy import text

    from etl.db import warehouse_engine

    engine = warehouse_engine()
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT to_regclass('raw.staff')")).scalar()
        if not exists:
            return  # staff feed not landed yet; DAG stays green, facts unaffected
        conn.execute(text("SET app.user = 'airflow:dims_scd2'"))
        for stmt in _scd2_sql("warehouse.dim_staff", "raw.staff", "staff_id", STAFF_TRACKED):
            conn.execute(text(stmt))


with DAG(
    dag_id="dims_scd2",
    schedule="30 0 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args={
        "owner": "mediflow",
        "retries": 3,
        "retry_delay": timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "on_failure_callback": slack_failure_alert,
    },
    tags=["etl", "dims"],
) as dag:
    refs = PythonOperator(task_id="upsert_reference_dims", python_callable=_upsert_reference_dims)
    patients = PythonOperator(task_id="upsert_patients", python_callable=_upsert_patients)
    hospitals = PythonOperator(task_id="scd2_dim_hospital", python_callable=_scd2_hospitals)
    staff = PythonOperator(task_id="scd2_dim_staff", python_callable=_scd2_staff)
    refs >> [patients, hospitals, staff]
