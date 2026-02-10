"""SARIMA for ER wait times: a single dominant 24h seasonal cycle with
autocorrelated shocks — classic SARIMA territory, and pmdarima gives us
defensible automated order selection.

Order selection: auto_arima stepwise AIC search, d/D via KPSS + OCSB tests,
m=24 (hourly data, daily season), bounded search p,q <= 3, P,Q <= 2.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pmdarima as pm

from forecasting.evaluate import metrics

log = logging.getLogger(__name__)


def train(series: pd.Series) -> tuple[pm.arima.ARIMA, dict]:
    """series: hourly avg_wait_minutes indexed by ts. Last 7 days held out."""
    y = series.asfreq("1h").interpolate(limit=3).dropna()
    train_y, test_y = y[:-168], y[-168:]

    model = pm.auto_arima(
        train_y,
        seasonal=True,
        m=24,
        d=None, D=None,                 # let KPSS/OCSB decide differencing
        test="kpss", seasonal_test="ocsb",
        max_p=3, max_q=3, max_P=2, max_Q=2,
        stepwise=True,
        information_criterion="aic",
        suppress_warnings=True,
        error_action="ignore",
    )
    log.info("auto_arima selected order=%s seasonal_order=%s", model.order, model.seasonal_order)

    pred, ci = model.predict(n_periods=len(test_y), return_conf_int=True, alpha=0.10)
    m = metrics(test_y.to_numpy(), np.asarray(pred), ci[:, 0], ci[:, 1])
    log.info("sarima_er_wait holdout: %s", m)
    model.update(test_y)  # fold holdout back in before deployment
    return model, m


def forecast(model: pm.arima.ARIMA, horizon_hours: int = 24) -> pd.DataFrame:
    pred, ci = model.predict(n_periods=horizon_hours, return_conf_int=True, alpha=0.10)
    return pd.DataFrame(
        {"yhat": np.maximum(pred, 0), "yhat_lower": np.maximum(ci[:, 0], 0), "yhat_upper": ci[:, 1]}
    )
