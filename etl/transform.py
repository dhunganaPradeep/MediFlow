"""Raw -> warehouse conformance: resolve surrogate keys, derive time_key,
select only the current hour's micro-batch. All lookups via parameterised
SQL — string interpolation never touches user data."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def _key_map(engine: Engine, sql: str) -> dict:
    with engine.connect() as conn:
        return dict(conn.execute(text(sql)).fetchall())


def staged_frames(engine: Engine, lookback_hours: int = 2) -> dict[str, pd.DataFrame]:
    hosp = _key_map(engine, "SELECT hospital_id, hospital_key FROM warehouse.dim_hospital WHERE is_current")
    dept = _key_map(engine, "SELECT department_id, department_key FROM warehouse.dim_department")
    pat = _key_map(engine, "SELECT patient_pseudo_id, patient_key FROM warehouse.dim_patient")
    diag = _key_map(engine, "SELECT icd10_code, diagnosis_key FROM warehouse.dim_diagnosis")

    def read(table: str, ts_col: str) -> pd.DataFrame:
        return pd.read_sql(
            text(f"SELECT * FROM raw.{table} WHERE {ts_col} >= now() - interval '{int(lookback_hours)} hours'"),  # noqa: S608
            engine,
        )

    adm = read("admissions", "admit_ts")
    if not adm.empty:
        adm["hospital_key"] = adm["hospital_id"].map(hosp)
        adm["department_key"] = adm["department_id"].map(dept)
        adm["patient_key"] = adm["patient_pseudo_id"].map(pat)
        adm["diagnosis_key"] = adm["icd10_code"].map(diag)
        adm["time_key"] = pd.to_datetime(adm["admit_ts"], utc=True).dt.strftime("%Y%m%d%H").astype(int)
        adm = adm[["source_record_id", "batch_id", "time_key", "hospital_key", "department_key",
                   "patient_key", "diagnosis_key", "admit_ts", "discharge_ts", "los_hours"]].dropna(
            subset=["hospital_key", "department_key", "patient_key", "diagnosis_key"])

    er = read("er_visits", "arrival_ts")
    if not er.empty:
        er["hospital_key"] = er["hospital_id"].map(hosp)
        er["patient_key"] = er["patient_pseudo_id"].map(pat)
        er["time_key"] = pd.to_datetime(er["arrival_ts"], utc=True).dt.strftime("%Y%m%d%H").astype(int)
        er = er[["source_record_id", "batch_id", "time_key", "hospital_key", "patient_key",
                 "arrival_ts", "triage_level", "wait_minutes"]].dropna(subset=["hospital_key", "patient_key"])

    util = read("utilization", "snapshot_ts")
    if not util.empty:
        util["hospital_key"] = util["hospital_id"].map(hosp)
        util["department_key"] = util["department_id"].map(dept)
        util["time_key"] = pd.to_datetime(util["snapshot_ts"], utc=True).dt.strftime("%Y%m%d%H").astype(int)
        util = util[["batch_id", "time_key", "hospital_key", "department_key", "snapshot_ts",
                     "beds_total", "beds_occupied", "staff_on_shift"]].dropna(
            subset=["hospital_key", "department_key"])

    amb = read("dispatch", "dispatch_ts")
    if not amb.empty:
        amb["hospital_key"] = amb["hospital_id"].map(hosp)
        amb["time_key"] = pd.to_datetime(amb["dispatch_ts"], utc=True).dt.strftime("%Y%m%d%H").astype(int)
        amb = amb[["source_record_id", "batch_id", "time_key", "hospital_key", "dispatch_ts",
                   "zone", "priority", "response_minutes", "temp_c", "precip_mm"]]

    return {"admissions": adm, "er_visits": er, "utilization": util, "dispatch": amb}
