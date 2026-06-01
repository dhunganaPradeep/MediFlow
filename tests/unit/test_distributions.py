import numpy as np
import pytest

from data_generation import distributions as dist

pytestmark = pytest.mark.unit


def test_monday_admissions_exceed_midweek(hourly_index):
    counts = dist.admission_counts(hourly_index)
    monday = counts[hourly_index.dayofweek == 0].mean()
    wednesday = counts[hourly_index.dayofweek == 2].mean()
    assert monday > wednesday * 1.15


def test_er_evening_surge(hourly_index):
    counts = dist.er_visit_counts(hourly_index)
    surge = counts[(hourly_index.hour >= 18) & (hourly_index.hour <= 22)].mean()
    early = counts[(hourly_index.hour >= 3) & (hourly_index.hour <= 6)].mean()
    assert surge > early * 2


def test_winter_seasonality():
    winter = dist.seasonal_multiplier(np.full(500, 25)).mean()   # late January
    summer = dist.seasonal_multiplier(np.full(500, 207)).mean()  # late July
    assert winter > summer * 1.3


def test_staffing_anticorrelated_with_load():
    rng = np.random.default_rng(0)
    load = rng.poisson(8, 5000).astype(float)
    staff = dist.staff_on_shift(load, planned=24)
    assert np.corrcoef(load, staff)[0, 1] < -0.15


def test_rain_slows_ambulance_response():
    priority = np.full(4000, 2)
    dry = dist.response_minutes(priority, np.zeros(4000)).mean()
    wet = dist.response_minutes(priority, np.full(4000, 10.0)).mean()
    assert wet > dry
