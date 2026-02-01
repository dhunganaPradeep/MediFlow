"""Synthetic data orchestrator.

Usage:
    python -m data_generation.generate --days 365 --hospitals 5 --load

Writes CSVs to ./seed_output/ and, with --load, bulk-loads the raw schema.
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from data_generation import distributions as dist
from data_generation.weather import fetch_weather
from security.pseudonymise import pseudonymise_patient_id

log = logging.getLogger(__name__)
fake = Faker()
Faker.seed(42)

DEPARTMENTS = [
    ("ED", "Emergency", "emergency", 40),
    ("ICU", "Intensive Care", "critical_care", 18),
    ("MED", "Internal Medicine", "medicine", 60),
    ("SUR", "Surgery", "surgery", 45),
    ("PED", "Pediatrics", "pediatrics", 30),
]
ICD10 = [
    ("J11.1", "Influenza with respiratory manifestations", "X", False),
    ("I21.9", "Acute myocardial infarction", "IX", False),
    ("J44.9", "COPD, unspecified", "X", True),
    ("E11.9", "Type 2 diabetes mellitus", "IV", True),
    ("S72.0", "Fracture of femur neck", "XIX", False),
    ("N39.0", "Urinary tract infection", "XIV", False),
    ("I50.9", "Heart failure, unspecified", "IX", True),
    ("K35.8", "Acute appendicitis", "XI", False),
]
AGE_BANDS = ["0-17", "18-39", "40-64", "65-79", "80+"]
AGE_WEIGHTS = [0.12, 0.24, 0.30, 0.22, 0.12]  # hospital population skews old
ZONES = [f"Z{i}" for i in range(1, 9)]


def build_frames(days: int, hospitals: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    end = pd.Timestamp.utcnow().floor("h")
    idx = pd.date_range(end - pd.Timedelta(days=days), end, freq="1h", tz="UTC")
    weather = fetch_weather(str(idx[0].date()), str(idx[-1].date()))
    weather = weather.set_index("ts").reindex(idx).ffill().reset_index(names="ts")

    hosp = pd.DataFrame(
        {
            "hospital_id": [f"H{i:03d}" for i in range(1, hospitals + 1)],
            "name": [f"{fake.city()} General Hospital" for _ in range(hospitals)],
            "region": rng.choice(["north", "south", "east", "west"], hospitals),
            "bed_capacity": rng.integers(150, 600, hospitals),
            "trauma_level": rng.integers(1, 4, hospitals),
        }
    )

    patients = pd.DataFrame(
        {
            "mrn": [f"MRN{i:07d}" for i in range(20_000)],
            "sex": rng.choice(["F", "M", "O"], 20_000, p=[0.51, 0.48, 0.01]),
            "age_band": rng.choice(AGE_BANDS, 20_000, p=AGE_WEIGHTS),
            "zip3": [fake.postcode()[:3] for _ in range(20_000)],
            "birth_year": rng.integers(1930, 2024, 20_000),
        }
    )
    patients["patient_pseudo_id"] = patients["mrn"].map(pseudonymise_patient_id)
    patients = patients.drop(columns=["mrn"])  # raw MRN never leaves this function

    adm_counts = dist.admission_counts(idx)
    er_counts = dist.er_visit_counts(idx)
    batch = str(uuid.uuid4())

    adm_rows = idx.repeat(adm_counts)
    n_adm = len(adm_rows)
    age_idx = rng.choice(len(AGE_BANDS), n_adm, p=AGE_WEIGHTS)
    diag_idx = rng.integers(0, len(ICD10), n_adm)
    is_chronic = np.array([ICD10[i][3] for i in diag_idx])
    admissions = pd.DataFrame(
        {
            "source_record_id": [f"ADM-{uuid.uuid4().hex[:12]}" for _ in range(n_adm)],
            "batch_id": batch,
            "admit_ts": adm_rows + pd.to_timedelta(rng.integers(0, 3600, n_adm), unit="s"),
            "hospital_id": rng.choice(hosp["hospital_id"], n_adm),
            "department_id": rng.choice([d[0] for d in DEPARTMENTS], n_adm, p=[0.30, 0.10, 0.30, 0.20, 0.10]),
            "patient_pseudo_id": rng.choice(patients["patient_pseudo_id"], n_adm),
            "icd10_code": [ICD10[i][0] for i in diag_idx],
            "los_hours": dist.length_of_stay_hours(age_idx, is_chronic),
        }
    )
    admissions["discharge_ts"] = admissions["admit_ts"] + pd.to_timedelta(
        admissions["los_hours"], unit="h"
    )

    er_rows = idx.repeat(er_counts)
    n_er = len(er_rows)
    triage = rng.choice([1, 2, 3, 4, 5], n_er, p=[0.03, 0.15, 0.40, 0.30, 0.12])
    er = pd.DataFrame(
        {
            "source_record_id": [f"ER-{uuid.uuid4().hex[:12]}" for _ in range(n_er)],
            "batch_id": batch,
            "arrival_ts": er_rows + pd.to_timedelta(rng.integers(0, 3600, n_er), unit="s"),
            "hospital_id": rng.choice(hosp["hospital_id"], n_er),
            "patient_pseudo_id": rng.choice(patients["patient_pseudo_id"], n_er),
            "triage_level": triage,
            "wait_minutes": dist.er_wait_minutes(np.repeat(er_counts, er_counts), triage),
        }
    )

    util_frames = []
    for _, h in hosp.iterrows():
        for dep_id, _, _, beds in DEPARTMENTS:
            occ_ratio = np.clip(
                0.72
                + 0.10 * np.sin(2 * np.pi * (idx.dayofyear - 25) / 365.25 * -1)
                + rng.normal(0, 0.05, len(idx)),
                0.3,
                1.0,
            )
            util_frames.append(
                pd.DataFrame(
                    {
                        "batch_id": batch,
                        "snapshot_ts": idx,
                        "hospital_id": h["hospital_id"],
                        "department_id": dep_id,
                        "beds_total": beds,
                        "beds_occupied": (beds * occ_ratio).round().astype(int),
                        "staff_on_shift": dist.staff_on_shift(adm_counts, planned=max(6, beds // 4)),
                    }
                )
            )
    utilization = pd.concat(util_frames, ignore_index=True)

    amb_counts = dist.ambulance_counts(idx, weather["temp_c"].to_numpy(), weather["precip_mm"].to_numpy())
    amb_rows = idx.repeat(amb_counts)
    n_amb = len(amb_rows)
    wx = weather.set_index("ts").loc[amb_rows]
    priority = rng.choice([1, 2, 3], n_amb, p=[0.25, 0.45, 0.30])
    dispatch = pd.DataFrame(
        {
            "source_record_id": [f"AMB-{uuid.uuid4().hex[:12]}" for _ in range(n_amb)],
            "batch_id": batch,
            "dispatch_ts": amb_rows + pd.to_timedelta(rng.integers(0, 3600, n_amb), unit="s"),
            "zone": rng.choice(ZONES, n_amb),
            "priority": priority,
            "response_minutes": dist.response_minutes(priority, wx["precip_mm"].to_numpy()),
            "temp_c": wx["temp_c"].to_numpy(),
            "precip_mm": wx["precip_mm"].to_numpy(),
            "hospital_id": rng.choice(hosp["hospital_id"], n_amb),
        }
    )

    return {
        "hospitals": hosp,
        "patients": patients,
        "admissions": admissions,
        "er_visits": er,
        "utilization": utilization,
        "dispatch": dispatch,
        "weather": weather,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--hospitals", type=int, default=5)
    p.add_argument("--load", action="store_true", help="bulk load into Postgres raw schema")
    args = p.parse_args()

    frames = build_frames(args.days, args.hospitals)
    out = Path("seed_output")
    out.mkdir(exist_ok=True)
    for name, df in frames.items():
        df.to_csv(out / f"{name}.csv", index=False)
        log.info("wrote %s: %d rows", name, len(df))

    if args.load:
        from sqlalchemy import create_engine

        engine = create_engine(
            "postgresql+psycopg2://{u}:{p}@{h}:{port}/{db}".format(
                u=os.environ["POSTGRES_USER"],
                p=os.environ["POSTGRES_PASSWORD"],
                h=os.environ.get("POSTGRES_HOST", "localhost"),
                port=os.environ.get("POSTGRES_PORT", "5432"),
                db=os.environ["POSTGRES_DB"],
            )
        )
        for name, df in frames.items():
            df.to_sql(name, engine, schema="raw", if_exists="append", index=False, chunksize=10_000)
            log.info("loaded raw.%s", name)


if __name__ == "__main__":
    main()
