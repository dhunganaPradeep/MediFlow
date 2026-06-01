import os

import pytest

os.environ.setdefault("MEDIFLOW_HMAC_KEY", "test-key")


@pytest.fixture
def hourly_index():
    import pandas as pd

    return pd.date_range("2025-01-06", periods=24 * 28, freq="1h", tz="UTC")  # starts Monday
