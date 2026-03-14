"""
KAIRI-SIO — s_t.py
S_t: Temporal Integrity Score

Penalizes latency and gaps in the 1h window.
Based on TEC_Formulas_Sc_Veto_v1.1.txt section 4.

For historical batch data (no real-time ts_sensor):
  - Latency is computed as gap to previous expected timestamp
  - Gap rate W1 = fraction of expected rows missing in last 1h window

S_t = L(lat) * G(gap_rate_W1)

L(lat) piecewise (breakpoints configurable por confederación via sensor_config):
  1.0  if lat <= t1
  0.7  if t1 < lat <= t2
  0.4  if t2 < lat <= LAT_CRITICAL_S
  0.1  if lat > LAT_CRITICAL_S

Default CHG: t1=60s, t2=300s, LAT_CRITICAL_S=900s

G(gap_rate) = 1 - gap_rate

Usage:
    from src.config.sensor_config import get_latency_config
    lat_cfg = get_latency_config('CHG')
    s_t = compute_s_t(df, latency_config=lat_cfg)
"""

import pandas as pd
import numpy as np
from typing import Optional

# Fallback inline — evita import circular si se usa s_t.py de forma aislada
_DEFAULT_LATENCY_CONFIG = {
    "lat_breakpoints_s": [60, 300, 900],
    "lat_scores":        [1.0, 0.7, 0.4, 0.1],
    "lat_critical_s":    900,
    "confederation":     "DEFAULT",
}


def _latency_score(lat_seconds: pd.Series, latency_config: dict) -> pd.Series:
    """
    Piecewise latency penalty.

    Parameters
    ----------
    lat_seconds     : excess latency in seconds (already clipped to >= 0)
    latency_config  : dict from sensor_config.get_latency_config()
                      keys: lat_breakpoints_s, lat_scores
    """
    bp = latency_config["lat_breakpoints_s"]   # [t1, t2, LAT_CRITICAL_S]
    sc = latency_config["lat_scores"]          # [s0, s1, s2, s3]

    L = pd.Series(sc[0], index=lat_seconds.index, dtype=float)
    L[lat_seconds > bp[0]] = sc[1]
    L[lat_seconds > bp[1]] = sc[2]
    L[lat_seconds > bp[2]] = sc[3]
    return L


def compute_s_t(
    df: pd.DataFrame,
    expected_resolution_hours: float = 1.0,
    latency_config: Optional[dict] = None,
) -> pd.Series:
    """
    Compute S_t for every row in df.

    For historical data:
      - lat_seconds = actual gap to previous row (in seconds) - expected (3600s)
        If gap == expected (1h), lat = 0 -> L = 1.0
        If gap > expected (e.g. DST 2h gap), lat = 3600s -> L = 0.1
      - gap_rate_W1 = fraction of NaN values across H_level, Q_inflow, P_rain
        in the current row (point-in-time proxy for 1h window)

    Parameters
    ----------
    df : curated DataFrame sorted by ts_station
    expected_resolution_hours : 1.0 for SAIH hourly data
    latency_config : dict from sensor_config.get_latency_config(confederation)
                     If None, uses DEFAULT (CHG — 60/300/900s)

    Returns
    -------
    pd.Series of float [0.0, 1.0]
    """
    cfg = latency_config or _DEFAULT_LATENCY_CONFIG
    expected_seconds = expected_resolution_hours * 3600.0

    # ── Latency from time gap ──────────────────────────────────────────────
    ts = pd.to_datetime(df['ts_station'])
    actual_gap_s = ts.diff().dt.total_seconds().fillna(expected_seconds)

    # Latency = excess seconds beyond expected
    lat_seconds = (actual_gap_s - expected_seconds).clip(lower=0)
    L = _latency_score(lat_seconds, cfg)

    # ── Gap rate W1 (point proxy) ──────────────────────────────────────────
    value_fields = [c for c in ['H_level', 'Q_inflow', 'P_rain'] if c in df.columns]
    n_fields = len(value_fields)

    if n_fields > 0:
        null_count = df[value_fields].isna().sum(axis=1)
        gap_rate   = null_count / n_fields
    else:
        gap_rate = pd.Series(0.0, index=df.index)

    G = (1.0 - gap_rate).clip(lower=0.0, upper=1.0)

    s_t = (L * G).clip(lower=0.0, upper=1.0)
    return s_t


def get_s_t_components(
    df: pd.DataFrame,
    expected_resolution_hours: float = 1.0,
    latency_config: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Returns DataFrame with S_t and its components for forensic logging.

    Columns: s_t, lat_seconds, L_lat, gap_rate_W1, G_gap, lat_critical_s, confederation

    Parameters
    ----------
    df : curated DataFrame sorted by ts_station
    expected_resolution_hours : 1.0 for SAIH hourly data
    latency_config : dict from sensor_config.get_latency_config(confederation)
                     If None, uses DEFAULT (CHG — 60/300/900s)
    """
    cfg = latency_config or _DEFAULT_LATENCY_CONFIG
    expected_seconds = expected_resolution_hours * 3600.0

    ts = pd.to_datetime(df['ts_station'])
    actual_gap_s = ts.diff().dt.total_seconds().fillna(expected_seconds)
    lat_seconds  = (actual_gap_s - expected_seconds).clip(lower=0)
    L = _latency_score(lat_seconds, cfg)

    value_fields = [c for c in ['H_level', 'Q_inflow', 'P_rain'] if c in df.columns]
    n_fields = len(value_fields)
    null_count = df[value_fields].isna().sum(axis=1) if n_fields > 0 else pd.Series(0, index=df.index)
    gap_rate   = null_count / n_fields if n_fields > 0 else pd.Series(0.0, index=df.index)
    G = (1.0 - gap_rate).clip(lower=0.0, upper=1.0)

    return pd.DataFrame({
        's_t':            (L * G).clip(0.0, 1.0),
        'lat_seconds':    lat_seconds,
        'L_lat':          L,
        'gap_rate_W1':    gap_rate,
        'G_gap':          G,
        'lat_critical_s': cfg["lat_critical_s"],      # para registro forense
        'confederation':  cfg["confederation"],        # para trazabilidad
    }, index=df.index)