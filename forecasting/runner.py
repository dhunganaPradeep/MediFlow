"""Operational glue used by the forecasting DAGs:

- predict_all(): load active models, write next-horizon predictions to
  ops.forecast_predictions.
- rolling_mape(days=7): realised MAPE per model from fct_forecast_vs_actual.
- retrain_all(promote_if_better=True): retrain, register in
  ops.model_registry, flip is_active only when holdout MAPE improves.
"""

from __future__ import annotations

import json
import logging
import pickle  # noqa: S403 - artifacts are produced and consumed locally only
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from etl.db import warehouse_engine

log = logging.getLogger(__name__)
ARTIFACTS = Path(__file__).parent.parent / "models_store"


def rolling_mape(days: int = 7) -> dict[str, float]:
    engine = warehouse_engine()
    sql = text(
        "SELECT model_name, avg(ape) AS mape FROM marts.fct_forecast_vs_actual "
        "WHERE forecast_ts >= now() - (:d || ' days')::interval AND ape IS NOT NULL "
        "GROUP BY model_name"
    )
    with engine.connect() as conn:
        return {r.model_name: float(r.mape) for r in conn.execute(sql, {"d": days})}


def _register(conn, name: str, version: str, m: dict, path: str, promote: bool) -> None:
    if promote:
        conn.execute(
            text("UPDATE ops.model_registry SET is_active = false WHERE model_name = :n"),
            {"n": name},
        )
    conn.execute(
        text(
            "INSERT INTO ops.model_registry (model_name, version, metrics, artifact_path, is_active) "
            "VALUES (:n, :v, :m, :p, :a)"
        ),
        {"n": name, "v": version, "m": json.dumps(m), "p": path, "a": promote},
    )


def _active_mape(conn, name: str) -> float:
    row = conn.execute(
        text(
            "SELECT (metrics->>'mape')::float FROM ops.model_registry "
            "WHERE model_name = :n AND is_active"
        ),
        {"n": name},
    ).fetchone()
    return row[0] if row else float("inf")


def retrain_all(promote_if_better: bool = True) -> None:
    from forecasting import lstm_ambulance, prophet_occupancy, sarima_er_wait
    from forecasting.features import add_calendar

    engine = warehouse_engine()
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    occ = pd.read_sql(
        "SELECT snapshot_ts AS ts, avg(occupancy_rate) AS occupancy_rate, "
        "avg(avg_temp_c) AS temp_c FROM marts.fct_occupancy_hourly o "
        "LEFT JOIN marts.fct_ambulance_by_zone_hour w ON w.hour_bucket = o.snapshot_ts "
        "GROUP BY 1 ORDER BY 1",
        engine,
    )
    occ["temp_c"] = occ["temp_c"].fillna(occ["temp_c"].mean())
    occ = add_calendar(occ)
    er = pd.read_sql(
        "SELECT hour_bucket AS ts, avg(avg_wait_minutes) AS y FROM marts.fct_er_wait_rolling "
        "GROUP BY 1 ORDER BY 1", engine,
    ).set_index("ts")["y"]
    amb = pd.read_sql(
        "SELECT hour_bucket AS ts, sum(dispatch_count) AS dispatch_count, "
        "avg(avg_temp_c) AS temp_c, sum(total_precip_mm) AS precip_mm "
        "FROM marts.fct_ambulance_by_zone_hour GROUP BY 1 ORDER BY 1",
        engine, parse_dates=["ts"],
    )

    jobs = [
        ("prophet_occupancy", lambda: prophet_occupancy.train(occ)[:2]),
        ("sarima_er_wait", lambda: sarima_er_wait.train(er)[:2]),
        ("lstm_ambulance", lambda: lstm_ambulance.train(amb)[:2]),
    ]
    with engine.begin() as conn:
        for name, job in jobs:
            model, m = job()
            path = str(ARTIFACTS / f"{name}_{version}.pkl")
            with open(path, "wb") as f:
                pickle.dump(model, f)
            promote = (not promote_if_better) or m["mape"] < _active_mape(conn, name)
            _register(conn, name, version, m, path, promote)
            log.info("%s v%s registered (promoted=%s) %s", name, version, promote, m)


def predict_all(horizon_hours: int = 24) -> None:
    from forecasting import prophet_occupancy, sarima_er_wait
    from forecasting.features import add_calendar

    engine = warehouse_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT model_name, artifact_path FROM ops.model_registry WHERE is_active")
        ).fetchall()
        for name, path in rows:
            with open(path, "rb") as f:
                model = pickle.load(f)  # noqa: S301 - local artifact written by us
            now = pd.Timestamp.utcnow().floor("h")
            future_idx = pd.date_range(now, periods=horizon_hours, freq="1h")
            if name == "prophet_occupancy":
                fut = add_calendar(pd.DataFrame({"ts": future_idx.tz_localize(None)}))
                fut["temp_c"] = 10.0  # next-day climatology placeholder regressor
                out = prophet_occupancy.forecast(model, fut)
                records = [
                    (name, "occupancy_rate", "ALL", r.ds, r.yhat, r.yhat_lower, r.yhat_upper)
                    for r in out.itertuples()
                ]
            elif name == "sarima_er_wait":
                out = sarima_er_wait.forecast(model, horizon_hours)
                records = [
                    (name, "avg_wait_minutes", "ED", future_idx[i], r.yhat, r.yhat_lower, r.yhat_upper)
                    for i, r in enumerate(out.itertuples())
                ]
            else:
                continue  # LSTM inference needs the live feature window; runs in retrain cycle
            conn.execute(
                text(
                    "INSERT INTO ops.forecast_predictions "
                    "(model_name, target, entity, forecast_ts, yhat, yhat_lower, yhat_upper) "
                    "VALUES (:n, :t, :e, :ts, :y, :lo, :hi) ON CONFLICT DO NOTHING"
                ),
                [
                    {"n": n, "t": t, "e": e, "ts": ts, "y": float(y), "lo": float(lo), "hi": float(hi)}
                    for n, t, e, ts, y, lo, hi in records
                ],
            )
            log.info("%s: %d predictions written", name, len(records))
