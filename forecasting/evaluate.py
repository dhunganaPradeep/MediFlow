"""Evaluation: RMSE for magnitude, MAPE for relative error (operational
threshold language: 'within 15%'), and prediction-interval coverage because
a hospital plans against the upper bound, not the point estimate. MAE alone
hides relative scale and says nothing about interval calibration."""

from __future__ import annotations

import numpy as np


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-6) -> float:
    mask = np.abs(y_true) > eps
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def pi_coverage(y_true: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    """Fraction of actuals inside the interval; target ~0.90 for 90% PIs."""
    return float(np.mean((y_true >= lower) & (y_true <= upper)))


def metrics(y_true, y_pred, lower=None, upper=None) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    out = {"rmse": rmse(y_true, y_pred), "mape": mape(y_true, y_pred)}
    if lower is not None and upper is not None:
        out["pi_coverage"] = pi_coverage(y_true, np.asarray(lower), np.asarray(upper))
    return out
