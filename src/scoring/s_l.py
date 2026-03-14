"""
KAIRI-SIO — s_l.py
S_l: Logical Coherence Score

Detects inconsistencies between variables that don't violate physical rules
but indicate sensor/telemetry problems.
Based on TEC_Formulas_Sc_Veto_v1.0.txt section 5.

Three components:
  C_PH : rain -> level change coherence
  C_QH : flow -> level change coherence
  C_z  : robust z-score (median + MAD) for each variable

S_l = min(C_PH, C_QH, C_z)

Calibration from E32_VADOMOJON real data:
  eps_H = 0.0137m  (p99 of |dH_1h| historically)
  P_min = 1.0 mm   (significant rainfall threshold)
"""

import pandas as pd
import numpy as np


# Calibrated from E32_VADOMOJON Sprint 0 inspection
# eps_H: p99 of |dH_1h| = 0.0137m — use a round value for auditability
EPS_H_DEFAULT  = 0.02    # meters — level change considered significant
P_MIN_DEFAULT  = 1.0     # mm/h  — rainfall considered significant
W24_MIN_PERIODS = 6      # minimum observations for rolling stats


def _robust_zscore(series: pd.Series, window: int = 24) -> pd.Series:
    """
    Robust z-score using rolling median and MAD.
    z = |x - median_W24| / (MAD_W24 + 1e-6)
    """
    rolling = series.rolling(window=window, min_periods=W24_MIN_PERIODS)
    med  = rolling.median()
    mad  = rolling.apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True)
    z    = (series - med).abs() / (mad + 1e-6)
    return z.fillna(0.0)


def _c_ph(
    df: pd.DataFrame,
    eps_H: float = EPS_H_DEFAULT,
    p_min: float = P_MIN_DEFAULT,
) -> pd.Series:
    """
    C_PH: Rain -> Level change coherence.

    If P_1h < P_min AND dH_1h > eps_H  (level rising with no rain)  -> 0.4
    If P_1h < P_min AND dH_1h < -eps_H (level falling with no rain) -> 0.7 (could be release)
    Otherwise -> 1.0

    Both variables must be present; if either is NaN, C_PH = 1.0 (no penalty).
    """
    C_PH = pd.Series(1.0, index=df.index)

    if 'P_rain' not in df.columns or 'H_level' not in df.columns:
        return C_PH

    P   = df['P_rain']
    dH  = df['H_level'].diff(1)

    both_valid = P.notna() & dH.notna()

    # Anomaly: level rising but no rain
    rising_no_rain  = both_valid & (P < p_min) & (dH >  eps_H)
    # Suspicious: level falling but no rain (could be release — penalize less)
    falling_no_rain = both_valid & (P < p_min) & (dH < -eps_H)

    C_PH[rising_no_rain]  = 0.4
    C_PH[falling_no_rain] = 0.7

    return C_PH


def _c_qh(df: pd.DataFrame, eps_H: float = EPS_H_DEFAULT) -> pd.Series:
    """
    C_QH: Flow -> Level change coherence.

    If Q_inflow > 0 but level not responding (dH ~ 0 over 1h) -> 0.5
    If Q_inflow == 0 but level rising significantly -> 0.5
    Otherwise -> 1.0

    Both variables must be present; if either is NaN, C_QH = 1.0.
    """
    C_QH = pd.Series(1.0, index=df.index)

    if 'Q_inflow' not in df.columns or 'H_level' not in df.columns:
        return C_QH

    Q   = df['Q_inflow']
    dH  = df['H_level'].diff(1)

    both_valid = Q.notna() & dH.notna()

    # High inflow but level not changing
    q_nonzero = Q[Q > 0]; q_thresh = q_nonzero.quantile(0.90) if len(q_nonzero) > 0 else 10.0
    inflow_no_response = both_valid & (Q > q_thresh) & (dH.abs() < eps_H * 0.1)

    # No inflow but level rising fast
    # (only flag if dH is really large — top 1%)
    dH_p99 = dH.abs().quantile(0.99)
    no_inflow_rising = both_valid & (Q == 0.0) & (dH > dH_p99)

    C_QH[inflow_no_response] = 0.5
    C_QH[no_inflow_rising]   = 0.5

    return C_QH


def _c_z(df: pd.DataFrame, window: int = 24) -> pd.Series:
    """
    C_z: Robust z-score penalty (worst across all available fields).

    z <= 3  -> 1.0
    3 < z <= 6 -> 0.7
    z > 6   -> 0.3
    """
    fields = [c for c in ['H_level', 'Q_inflow', 'P_rain'] if c in df.columns]
    if not fields:
        return pd.Series(1.0, index=df.index)

    worst_z = pd.Series(0.0, index=df.index)
    for field in fields:
        z = _robust_zscore(df[field].ffill(), window=window)
        worst_z = np.maximum(worst_z, z)

    C_z = pd.Series(1.0, index=df.index)
    C_z[worst_z > 6] = 0.3
    C_z[(worst_z > 3) & (worst_z <= 6)] = 0.7

    return C_z


def compute_s_l(
    df: pd.DataFrame,
    eps_H: float = EPS_H_DEFAULT,
    p_min: float = P_MIN_DEFAULT,
) -> pd.Series:
    """
    Compute S_l = min(C_PH, C_QH, C_z) for every row.

    Parameters
    ----------
    df     : curated DataFrame sorted by ts_station
    eps_H  : threshold for significant level change (meters)
    p_min  : threshold for significant rainfall (mm/h)

    Returns
    -------
    pd.Series of float [0.0, 1.0]
    """
    C_PH = _c_ph(df, eps_H, p_min)
    C_QH = _c_qh(df, eps_H)
    C_z  = _c_z(df)

    s_l = pd.concat([C_PH, C_QH, C_z], axis=1).min(axis=1)
    return s_l.clip(0.0, 1.0)


def get_s_l_components(
    df: pd.DataFrame,
    eps_H: float = EPS_H_DEFAULT,
    p_min: float = P_MIN_DEFAULT,
) -> pd.DataFrame:
    """
    Returns DataFrame with S_l and components for forensic logging.
    Columns: s_l, C_PH, C_QH, C_z
    """
    C_PH = _c_ph(df, eps_H, p_min)
    C_QH = _c_qh(df, eps_H)
    C_z  = _c_z(df)

    s_l = pd.concat([C_PH, C_QH, C_z], axis=1).min(axis=1).clip(0.0, 1.0)

    return pd.DataFrame({
        's_l':  s_l,
        'C_PH': C_PH,
        'C_QH': C_QH,
        'C_z':  C_z,
    }, index=df.index)