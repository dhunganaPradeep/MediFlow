"""Statistical demand models. Every signal is a parameterised stochastic
process, not uniform noise:

- Admissions: non-homogeneous Poisson, rate = base * dow * hour * season.
  Monday-morning multiplier peaks at 1.65 (weekend backlog effect).
- ER arrivals: Poisson with a two-Gaussian time-of-day intensity
  (lunch bump + dominant 18:00-22:00 surge).
- Flu season: annual sinusoid peaking late January + gamma-distributed noise.
- Staffing: negatively correlated with admission load via a Gaussian copula
  (rho = -0.45): busy days are exactly the days people call in sick.
- Ambulance demand: log-link on hour-of-day, weekend nights, cold and rain.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

RNG = np.random.default_rng(42)

# Day-of-week multipliers, Monday=0. Monday spike, weekend trough.
DOW_ADMISSION_MULT = np.array([1.35, 1.10, 1.02, 1.00, 1.05, 0.78, 0.70])


def hourly_admission_profile() -> np.ndarray:
    """24-vector: morning-heavy admissions (scheduled + post-weekend backlog).
    Gaussian bump centred 09:00, sd 2.5h, floor 0.35 overnight."""
    hours = np.arange(24)
    bump = stats.norm.pdf(hours, loc=9, scale=2.5)
    profile = 0.35 + bump / bump.max() * 1.3
    return profile / profile.mean()


def hourly_er_profile() -> np.ndarray:
    """24-vector: mixture of two Gaussians — minor 12:00 bump (w=0.3) and a
    dominant 19:30 surge (w=0.7) covering the 18:00-22:00 window."""
    hours = np.arange(24)
    mix = 0.3 * stats.norm.pdf(hours, loc=12, scale=2.0) + 0.7 * stats.norm.pdf(
        hours, loc=19.5, scale=1.8
    )
    profile = 0.30 + mix / mix.max() * 1.6
    return profile / profile.mean()


def seasonal_multiplier(day_of_year: np.ndarray) -> np.ndarray:
    """Annual sinusoid peaking ~Jan 25 (flu season), amplitude 0.30,
    plus gamma noise (k=20, theta=1/20 -> mean 1, modest right skew)."""
    phase = 2 * np.pi * (day_of_year - 25) / 365.25
    base = 1.0 + 0.30 * np.cos(phase)
    noise = stats.gamma.rvs(a=20, scale=1 / 20, size=len(day_of_year), random_state=RNG)
    return base * noise


def admission_counts(ts_index, base_rate: float = 6.0) -> np.ndarray:
    """Hourly admission counts: Poisson(lambda_t) with composed rate.
    ts_index: pandas DatetimeIndex at hourly grain."""
    hour_prof = hourly_admission_profile()
    lam = (
        base_rate
        * DOW_ADMISSION_MULT[ts_index.dayofweek]
        * hour_prof[ts_index.hour]
        * seasonal_multiplier(ts_index.dayofyear.to_numpy())
    )
    # Monday 07:00-11:00 backlog spike on top of dow multiplier
    monday_morning = (ts_index.dayofweek == 0) & (ts_index.hour >= 7) & (ts_index.hour <= 11)
    lam = lam * np.where(monday_morning, 1.22, 1.0)
    return stats.poisson.rvs(mu=lam, random_state=RNG)


def er_visit_counts(ts_index, base_rate: float = 9.0) -> np.ndarray:
    hour_prof = hourly_er_profile()
    weekend_night = (ts_index.dayofweek >= 5) & ((ts_index.hour >= 22) | (ts_index.hour <= 2))
    lam = (
        base_rate
        * hour_prof[ts_index.hour]
        * seasonal_multiplier(ts_index.dayofyear.to_numpy())
        * np.where(weekend_night, 1.35, 1.0)
    )
    return stats.poisson.rvs(mu=lam, random_state=RNG)


def er_wait_minutes(queue_depth: np.ndarray, triage_level: np.ndarray) -> np.ndarray:
    """Wait time ~ lognormal whose median scales with queue depth and triage.
    Triage 1 (resus) is seen near-immediately regardless of load."""
    base_median = 12.0 + 6.5 * queue_depth
    triage_mult = np.array([0.05, 0.35, 1.0, 1.5, 2.1])[triage_level - 1]
    median = base_median * triage_mult
    return stats.lognorm.rvs(s=0.45, scale=median, random_state=RNG).round(1)


def staff_on_shift(admission_load: np.ndarray, planned: int = 24) -> np.ndarray:
    """Gaussian copula, rho=-0.45: convert admission load to its empirical
    normal score, anti-correlate, map to binomial attendance probability."""
    rho = -0.45
    z_load = stats.zscore(admission_load.astype(float))
    z_staff = rho * z_load + np.sqrt(1 - rho**2) * RNG.standard_normal(len(admission_load))
    attendance_p = np.clip(0.93 + 0.04 * z_staff, 0.70, 0.99)
    return stats.binom.rvs(n=planned, p=attendance_p, random_state=RNG)


def ambulance_counts(ts_index, temp_c: np.ndarray, precip_mm: np.ndarray) -> np.ndarray:
    """Log-linear intensity: nights/weekends up, cold snaps (<0C) up 25%,
    heavy rain (>5mm) up 18%."""
    hour_effect = np.where(np.isin(ts_index.hour, [0, 1, 2, 22, 23]), 0.25, 0.0)
    weekend_effect = np.where(ts_index.dayofweek >= 5, 0.15, 0.0)
    cold_effect = np.where(temp_c < 0, 0.22, 0.0)
    rain_effect = np.where(precip_mm > 5, 0.17, 0.0)
    log_lam = np.log(2.2) + hour_effect + weekend_effect + cold_effect + rain_effect
    return stats.poisson.rvs(mu=np.exp(log_lam), random_state=RNG)


def response_minutes(priority: np.ndarray, precip_mm: np.ndarray) -> np.ndarray:
    """Gamma-distributed response times; rain slows everything by 15%."""
    base_mean = np.array([7.5, 11.0, 16.0])[priority - 1]
    mean = base_mean * np.where(precip_mm > 5, 1.15, 1.0)
    return stats.gamma.rvs(a=4.0, scale=mean / 4.0, random_state=RNG).round(1)


def length_of_stay_hours(age_band_idx: np.ndarray, is_chronic: np.ndarray) -> np.ndarray:
    """Weibull LOS: older + chronic -> longer right tail."""
    scale = 36.0 * (1 + 0.25 * age_band_idx) * np.where(is_chronic, 1.4, 1.0)
    return stats.weibull_min.rvs(c=1.3, scale=scale, random_state=RNG).round(2)
