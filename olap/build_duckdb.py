"""DuckDB analytical layer over Postgres marts.

Why DuckDB over ClickHouse here: single-node columnar OLAP with zero extra
ops burden, reads Postgres directly via the postgres extension, fits the
<$10/month VPS constraint; ClickHouse only pays off at multi-node scale.

Usage: python -m olap.build_duckdb --db ./mediflow.duckdb
"""

from __future__ import annotations

import argparse
import os

import duckdb

VIEWS = {
    "v_occupancy_hourly": """
        SELECT snapshot_ts, hospital_id, department_id, occupancy_rate,
               patients_per_staff, is_capacity_alert
        FROM pg.marts.fct_occupancy_hourly""",
    "v_er_wait_rolling": """
        SELECT hour_bucket, hospital_key, visit_count,
               avg_wait_minutes, p90_wait_minutes, wait_7d_rolling_avg
        FROM pg.marts.fct_er_wait_rolling""",
    "v_ambulance_zone_hour": """
        SELECT hour_bucket, zone, dispatch_count,
               avg_response_minutes, p90_response_minutes
        FROM pg.marts.fct_ambulance_by_zone_hour""",
    "v_staff_ratio_by_shift": """
        SELECT date_trunc('day', snapshot_ts) AS day,
               CASE WHEN extract(hour FROM snapshot_ts) BETWEEN 7 AND 14 THEN 'day'
                    WHEN extract(hour FROM snapshot_ts) BETWEEN 15 AND 22 THEN 'evening'
                    ELSE 'night' END AS shift,
               department_id,
               avg(patients_per_staff) AS avg_patients_per_staff
        FROM pg.marts.fct_occupancy_hourly
        GROUP BY 1, 2, 3""",
}


def build(db_path: str) -> None:
    con = duckdb.connect(db_path)
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(
        "ATTACH 'host={h} port={p} dbname={d} user={u} password={pw}' AS pg (TYPE postgres, READ_ONLY)".format(
            h=os.environ.get("POSTGRES_HOST", "localhost"),
            p=os.environ.get("POSTGRES_PORT", "5432"),
            d=os.environ.get("POSTGRES_DB", "mediflow"),
            u=os.environ["POSTGRES_USER"],
            pw=os.environ["POSTGRES_PASSWORD"],
        )
    )
    for name, sql in VIEWS.items():
        # Materialize as local columnar tables for sub-second dashboard slicing
        con.execute(f"CREATE OR REPLACE TABLE {name} AS {sql}")
    con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="mediflow.duckdb")
    build(p.parse_args().db)
