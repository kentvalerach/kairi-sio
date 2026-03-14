"""
KAIRI-SIO — s_f.py
S_f: Physical Integrity Score

Binary deterministic check: 1 if data is physically plausible, 0 if impossible.
Based on TEC_Formulas_Sc_Veto_v1.0.txt section 3.

Checks:
  - Value exists (not None/NaN)
  - Within physical range [x_min, x_max] for the sensor
  - Non-negative where required (Q_inflow, P_rain)
"""

import pandas as pd
import numpy as np


# Physical bounds per embalse per field — calibrated from real data (Sprint 0 inspection)
# Format: (min, max)
PHYSICAL_BOUNDS = {
    'E32_VADOMOJON': {
        'H_level':  (325.0, 375.0),   # cota absoluta msnm. real: 332-370, 5m margin
        'Q_inflow': (0.0,   600.0),    # m3/s, 33% above observed max (449)
        'P_rain':   (0.0,    50.0),    # mm/h, 2x observed max (23.2)
    },
    'E33_SRRA_BOYERA': {
        'H_level':  (380.0, 700.0),   # cota absoluta > 500m (935 values above old 500 limit)
        'Q_inflow': (0.0,   600.0),
        'P_rain':   (0.0,    50.0),
    },
    'E37_BEMBEZAR': {
        'H_level':  (80.0,  190.0),   # cota absoluta. real: 90-178, 10m margin each side
        'Q_inflow': (0.0,  1500.0),   # m3/s, 33% above observed max (1160)
        'P_rain':   (0.0,    70.0),   # mm/h, 2x observed max (33.5)
    },
}

# Default fallback if embalse not in config
_DEFAULT_BOUNDS = {
    'H_level':  (0.0,   1000.0),
    'Q_inflow': (0.0,  10000.0),
    'P_rain':   (0.0,    500.0),
}


def compute_s_f(df: pd.DataFrame, embalse_id: str) -> pd.Series:
    """
    Compute S_f for every row in df.

    S_f = 1.0 if all available fields pass physical checks
    S_f = 0.0 if ANY field fails (impossible value or impossible negative)

    Fields that are NaN are skipped (their absence is handled by S_t/S_h).
    A row where ALL fields are NaN gets S_f = 1.0 (no physical violation detected;
    the gap itself is penalized by S_t).

    Parameters
    ----------
    df : curated DataFrame (Data Contract v1.1)
    embalse_id : e.g. 'E32_VADOMOJON'

    Returns
    -------
    pd.Series of float (0.0 or 1.0), index aligned to df
    """
    bounds = PHYSICAL_BOUNDS.get(embalse_id, _DEFAULT_BOUNDS)
    fields = ['H_level', 'Q_inflow', 'P_rain']

    # Start with all passing
    s_f = pd.Series(1.0, index=df.index)

    for field in fields:
        if field not in df.columns:
            continue

        series = df[field]
        lo, hi = bounds.get(field, _DEFAULT_BOUNDS[field])

        # Only evaluate non-null values
        mask_valid = series.notna()

        # Out of range
        out_of_range = mask_valid & ((series < lo) | (series > hi))

        # Negative where impossible (Q_inflow, P_rain must be >= 0)
        if field in ('Q_inflow', 'P_rain'):
            negative = mask_valid & (series < 0.0)
        else:
            negative = pd.Series(False, index=df.index)

        # Any failure -> S_f = 0
        failed = out_of_range | negative
        s_f[failed] = 0.0

    return s_f


def get_s_f_flags(df: pd.DataFrame, embalse_id: str) -> pd.DataFrame:
    """
    Returns a DataFrame with individual flag columns for forensic logging.

    Columns: s_f, flag_H_range, flag_Q_range, flag_P_range, flag_negative
    """
    bounds = PHYSICAL_BOUNDS.get(embalse_id, _DEFAULT_BOUNDS)
    result = pd.DataFrame(index=df.index)

    for field in ['H_level', 'Q_inflow', 'P_rain']:
        if field not in df.columns:
            result[f'flag_{field}_range'] = False
            continue
        series = df[field]
        lo, hi = bounds.get(field, _DEFAULT_BOUNDS[field])
        mask_valid = series.notna()
        result[f'flag_{field}_range'] = mask_valid & ((series < lo) | (series > hi))

    result['flag_negative'] = (
        (df.get('Q_inflow', pd.Series(0, index=df.index)).fillna(0) < 0) |
        (df.get('P_rain',   pd.Series(0, index=df.index)).fillna(0) < 0)
    )

    result['s_f'] = compute_s_f(df, embalse_id)
    return result