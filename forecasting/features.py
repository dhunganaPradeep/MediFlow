"""Feature engineering for healthcare time series.

Derived features per target:
- Rolling means: 1h (raw), 6h, 24h, 7d (168h)
- Lags: occupancy [1, 24, 168]; ER wait [1, 2, 24]; ambulance [1, 24, 168]
- Calendar: hour, day_of_week, is_weekend, is_holiday, month, season one-hots
- Weather: temp_c, precip_mm joined at hourly grain
"""

from __future__ import annotations

import holidays as holidays_lib
import pandas as pd

ROLL_WINDOWS = {"roll_6h": 6, "roll_24h": 24, "roll_7d": 168}
LAGS = {
    "occupancy_rate": [1, 24, 168],
    "avg_wait_minutes": [1, 2, 24],
    "dispatch_count": [1, 24, 168],
}


def add_calendar(df: pd.DataFrame, ts_col: str = "ts") -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out[ts_col], utc=True)
    out["hour"] = ts.dt.hour
    out["day_of_week"] = ts.dt.dayofweek
    out["month"] = ts.dt.month
    out["is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
    hol = holidays_lib.country_holidays("US")
    out["is_holiday"] = ts.dt.date.map(lambda d: int(d in hol))
    out["is_winter"] = ts.dt.month.isin([12, 1, 2]).astype(int)
    return out


def add_rolling_and_lags(df: pd.DataFrame, target: str) -> pd.DataFrame:
    out = df.sort_values("ts").copy()
    for name, window in ROLL_WINDOWS.items():
        out[f"{target}_{name}"] = out[target].rolling(window, min_periods=1).mean()
    for lag in LAGS.get(target, [1, 24]):
        out[f"{target}_lag_{lag}"] = out[target].shift(lag)
    return out


def build_features(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Full pipeline; drops warm-up rows that lack lag history."""
    out = add_calendar(df)
    out = add_rolling_and_lags(out, target)
    return out.dropna().reset_index(drop=True)
