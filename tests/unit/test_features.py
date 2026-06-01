import numpy as np
import pandas as pd
import pytest

from forecasting.evaluate import mape, metrics, pi_coverage
from forecasting.features import build_features

pytestmark = pytest.mark.unit


def test_build_features_shape_and_no_nan(hourly_index):
    df = pd.DataFrame({"ts": hourly_index, "occupancy_rate": np.random.default_rng(0).uniform(0.5, 0.9, len(hourly_index))})
    out = build_features(df, "occupancy_rate")
    assert not out.isna().any().any()
    assert {"occupancy_rate_roll_24h", "occupancy_rate_lag_168", "is_holiday"} <= set(out.columns)
    assert len(out) == len(df) - 168  # longest lag consumed as warm-up


def test_mape_known_value():
    assert mape(np.array([100.0, 200.0]), np.array([110.0, 180.0])) == pytest.approx(0.10)


def test_pi_coverage():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert pi_coverage(y, y - 1, y + 1) == 1.0
    assert pi_coverage(y, y + 0.1, y + 1) == 0.0


def test_metrics_keys():
    m = metrics([1, 2], [1, 2], [0, 1], [2, 3])
    assert set(m) == {"rmse", "mape", "pi_coverage"}
