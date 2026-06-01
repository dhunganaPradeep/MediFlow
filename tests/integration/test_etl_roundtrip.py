"""Requires a Postgres with docker/postgres/init applied (CI main.yml or
local compose stack)."""

import uuid

import pandas as pd
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine():
    from etl.db import warehouse_engine

    return warehouse_engine()


def test_idempotent_upsert_is_rerun_safe(engine):
    from etl.load import upsert_event_fact

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO warehouse.dim_hospital (hospital_id, name, region, bed_capacity, row_hash) "
            "VALUES ('H-TEST', 't', 'north', 100, 'x') ON CONFLICT DO NOTHING"))
        conn.execute(text(
            "INSERT INTO warehouse.dim_department (department_id, name, specialty, bed_count) "
            "VALUES ('D-TEST', 't', 't', 10) ON CONFLICT DO NOTHING"))
        conn.execute(text(
            "INSERT INTO warehouse.dim_patient (patient_pseudo_id, age_band) "
            "VALUES ('P-TEST', '40-64') ON CONFLICT DO NOTHING"))
        conn.execute(text(
            "INSERT INTO warehouse.dim_diagnosis (icd10_code, description, chapter) "
            "VALUES ('Z-TEST', 't', 'I') ON CONFLICT DO NOTHING"))
        keys = conn.execute(text(
            "SELECT (SELECT hospital_key FROM warehouse.dim_hospital WHERE hospital_id='H-TEST'),"
            "(SELECT department_key FROM warehouse.dim_department WHERE department_id='D-TEST'),"
            "(SELECT patient_key FROM warehouse.dim_patient WHERE patient_pseudo_id='P-TEST'),"
            "(SELECT diagnosis_key FROM warehouse.dim_diagnosis WHERE icd10_code='Z-TEST')"
        )).fetchone()

    row = pd.DataFrame([{
        "batch_id": str(uuid.uuid4()),
        "source_record_id": "ADM-ROUNDTRIP-1",
        "time_key": 2025060112,
        "hospital_key": keys[0], "department_key": keys[1],
        "patient_key": keys[2], "diagnosis_key": keys[3],
        "admit_ts": "2025-06-01T12:00:00+00:00",
        "discharge_ts": None, "los_hours": 24.0, "is_readmission": False,
    }])
    from etl.load import upsert_event_fact as upsert

    upsert(engine, row, "warehouse.fact_admissions", ("source_record_id", "admit_ts"))
    upsert(engine, row, "warehouse.fact_admissions", ("source_record_id", "admit_ts"))  # rerun

    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM warehouse.fact_admissions WHERE source_record_id='ADM-ROUNDTRIP-1'"
        )).scalar()
    assert n == 1
