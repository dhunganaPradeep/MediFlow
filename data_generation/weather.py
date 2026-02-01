"""Open-Meteo historical weather client with an offline synthetic fallback,
so `make seed` never depends on network availability."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import requests
from scipy import stats

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather(start: str, end: str, lat: float = 52.52, lon: float = 13.41) -> pd.DataFrame:
    """Hourly temperature_2m and precipitation from Open-Meteo (free, no key)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": "temperature_2m,precipitation",
        "timezone": "UTC",
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
        resp.raise_for_status()
        h = resp.json()["hourly"]
        return pd.DataFrame(
            {
                "ts": pd.to_datetime(h["time"], utc=True),
                "temp_c": h["temperature_2m"],
                "precip_mm": h["precipitation"],
            }
        )
    except (requests.RequestException, KeyError) as exc:
        log.warning("Open-Meteo unavailable (%s); using synthetic weather", exc)
        return synthetic_weather(start, end)


def synthetic_weather(start: str, end: str, seed: int = 7) -> pd.DataFrame:
    """Seasonal sinusoid temperature + AR(1) noise; precipitation as a
    Bernoulli-gamma mixture (rains ~18% of hours)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="1h", tz="UTC")
    doy = idx.dayofyear.to_numpy()
    hod = idx.hour.to_numpy()
    seasonal = 10 - 12 * np.cos(2 * np.pi * (doy - 15) / 365.25)
    diurnal = 4 * np.sin(2 * np.pi * (hod - 9) / 24)
    ar = np.zeros(len(idx))
    for i in range(1, len(idx)):
        ar[i] = 0.95 * ar[i - 1] + rng.normal(0, 0.8)
    temp = seasonal + diurnal + ar
    raining = stats.bernoulli.rvs(p=0.18, size=len(idx), random_state=rng)
    amounts = stats.gamma.rvs(a=1.2, scale=2.5, size=len(idx), random_state=rng)
    return pd.DataFrame(
        {"ts": idx, "temp_c": temp.round(1), "precip_mm": (raining * amounts).round(1)}
    )
