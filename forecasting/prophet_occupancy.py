"""Prophet for bed occupancy: strong multi-seasonality (daily, weekly,
yearly flu cycle), interpretable, native holiday handling and prediction
intervals — the right tool for a smooth bounded rate series.

Regressors: temp_c, is_holiday, is_winter.
Seasonality: yearly (fourier 10), weekly (fourier 6), daily (fourier 8),
multiplicative — seasonal swing scales with level.
"""

from __future__ import annotations

import logging

import pandas as pd
from prophet import Prophet

from forecasting.evaluate import metrics

log = logging.getLogger(__name__)
HORIZON_HOURS = 24 * 30  # 30-day planning horizon


def build_model() -> Prophet:
    m = Prophet(
        growth="flat",
        seasonality_mode="multiplicative",
        yearly_seasonality=10,
        weekly_seasonality=6,
        daily_seasonality=8,
        interval_width=0.90,
        changepoint_prior_scale=0.05,
    )
    m.add_country_holidays(country_name="US")
    m.add_regressor("temp_c")
    m.add_regressor("is_holiday")
    m.add_regressor("is_winter")
    return m


def train(df: pd.DataFrame) -> tuple[Prophet, dict]:
    """df: columns ts, occupancy_rate, temp_c, is_holiday, is_winter.
    Last 14 days held out for evaluation."""
    data = df.rename(columns={"ts": "ds", "occupancy_rate": "y"}).copy()
    data["ds"] = pd.to_datetime(data["ds"]).dt.tz_localize(None)
    cutoff = data["ds"].max() - pd.Timedelta(days=14)
    train_df, test_df = data[data["ds"] <= cutoff], data[data["ds"] > cutoff]

    model = build_model()
    model.fit(train_df)
    pred = model.predict(test_df.drop(columns=["y"]))
    m = metrics(test_df["y"].to_numpy(), pred["yhat"].to_numpy(),
                pred["yhat_lower"].to_numpy(), pred["yhat_upper"].to_numpy())
    log.info("prophet_occupancy holdout: %s", m)
    return model, m


def forecast(model: Prophet, future_regressors: pd.DataFrame) -> pd.DataFrame:
    pred = model.predict(future_regressors.rename(columns={"ts": "ds"}))
    return pred[["ds", "yhat", "yhat_lower", "yhat_upper"]].clip(lower=0)
