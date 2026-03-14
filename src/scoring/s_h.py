"""
KAIRI-SIO — s_h.py
S_h: Historical Health Score

Detects long-term sensor degradation patterns invisible to S_f and S_l.
Based on TEC_Formulas_Sc_Veto_v1.0.txt section 6.

Three components:
  F_flat  : flatline detection (K=8 consecutive identical values)
  F_drift : EMA drift (6h vs 24h divergence, normalized by rolling std)
  F_gap24 : gap rate in 24h rolling window

S_h = min(F_flat, F_drift, F_gap24)

Calibration from E32_VADOMOJON real data:
  - 939 flatline runs >= 8h detected (many are real plateau periods at embalse max/min)
  - drift p90=1.42, p99=42.12 -> threshold 3.0 is conservative
  - gap rate W24 is low (<0.01%) -> threshold 0.10 is generous
"""

import pandas as pd
import numpy as np


# Calibrated from real data
FLATLINE_K   = 8      # consecutive identical values -> suspicious
DRIFT_W_FAST = 6      # hours for fast EMA
DRIFT_W_SLOW = 24     # hours for slow EMA
DRIFT_THRESH = 3.0    # normalized drift threshold for penalty
GAP_W24      = 24     # rolling window for gap rate
GAP_WARN     = 0.10   # 10% gaps in 24h -> penalty
GAP_FAIL     = 0.30   # 30% gaps in 24h -> severe penalty


def _f_flat(series: pd.Series, k: int = FLATLINE_K) -> pd.Series:
    """
    F_flat: penalize if last K values are all identical (flatline).

    F_flat = 0.2 if K or more consecutive identical values
    F_flat = 1.0 otherwise

    Note: at embalse, level can legitimately plateau (spillway open = constant level).
    We only flag if H_level is involved AND Q_inflow > 0 simultaneously,
    OR if P_rain is flatlined (rain sensors fail more often).
    For simplicity: flag any field with K-run, let forensics decide.
    """
    F = pd.Series(1.0, index=series.index)

    if series.isna().all():
        return F

    # Rolling: check if all K last values equal current
    # Use shift comparison chain
    is_same = pd.Series(True, index=series.index)
    for lag in range(1, k):
        is_same = is_same & (series == series.shift(lag)) & series.notna()

    F[is_same] = 0.2
    return F


def _flat_duration(series: pd.Series, k: int = FLATLINE_K) -> pd.Series:
    """
    Calcula cuántas horas consecutivas lleva el flatline activo en cada fila.

    Si la fila NO está en flatline (F_flat=1.0) → duration = 0.
    Si la fila SÍ está en flatline → duration = número de horas consecutivas
    idénticas hasta esa fila (inclusive), mínimo k.

    Usado por decision_engine para CRITICAL_FLAG en flatlines >= 48h.
    """
    duration = pd.Series(0, index=series.index, dtype=float)

    if series.isna().all():
        return duration

    # Detectar inicio de cada run de valores idénticos
    changed = (series != series.shift(1)) | series.isna() | series.shift(1).isna()
    run_id  = changed.cumsum()

    # Longitud de cada run
    run_lengths = run_id.map(run_id.value_counts())

    # Solo filas en flatline real (run_length >= k y valor no NaN)
    in_flat = (run_lengths >= k) & series.notna()

    # Posición dentro del run (1-indexed)
    run_pos = run_id.groupby(run_id).cumcount() + 1

    duration[in_flat] = run_pos[in_flat].astype(float)
    return duration


def _f_drift(series: pd.Series) -> pd.Series:
    """
    F_drift: EMA(6h) vs EMA(24h) divergence normalized by rolling std.

    drift = |EMA_fast - EMA_slow| / (std_24h + 1e-6)

    F_drift = 0.3 if drift > DRIFT_THRESH
    F_drift = 1.0 otherwise

    Note: calibrated from real data where p99 drift = 42, max = 4062.
    Threshold 3.0 sits around p90 (1.42) of normal operation — catches
    real anomalies while allowing normal seasonal variation.
    """
    ema_fast = series.ewm(span=DRIFT_W_FAST, min_periods=3).mean()
    ema_slow = series.ewm(span=DRIFT_W_SLOW, min_periods=6).mean()
    std_slow = series.rolling(DRIFT_W_SLOW, min_periods=6).std()

    drift = (ema_fast - ema_slow).abs() / (std_slow + 1e-6)
    drift = drift.fillna(0.0)

    F = pd.Series(1.0, index=series.index)
    F[drift > DRIFT_THRESH] = 0.3
    return F


def _f_gap24(df: pd.DataFrame) -> pd.Series:
    """
    F_gap24: fraction of NaN values in 24h rolling window across all fields.

    gap_rate_W24 = mean null fraction over last 24 rows

    F_gap24 = 0.2  if gap_rate >= GAP_FAIL
    F_gap24 = 0.6  if GAP_WARN <= gap_rate < GAP_FAIL
    F_gap24 = 1.0  otherwise
    """
    fields = [c for c in ['H_level', 'Q_inflow', 'P_rain'] if c in df.columns]
    if not fields:
        return pd.Series(1.0, index=df.index)

    # Null fraction per row (0 = all present, 1 = all missing)
    null_frac = df[fields].isna().mean(axis=1)

    # Rolling mean of null fraction over 24h window
    gap_rate_W24 = null_frac.rolling(GAP_W24, min_periods=1).mean()

    F = pd.Series(1.0, index=df.index)
    F[gap_rate_W24 >= GAP_FAIL]                              = 0.2
    F[(gap_rate_W24 >= GAP_WARN) & (gap_rate_W24 < GAP_FAIL)] = 0.6

    return F


def compute_s_h(df: pd.DataFrame) -> pd.Series:
    """
    Compute S_h = min(F_flat, F_drift, F_gap24) for every row.

    Uses H_level as primary field for flatline and drift
    (most reliable signal for embalse health).

    Parameters
    ----------
    df : curated DataFrame sorted by ts_station

    Returns
    -------
    pd.Series of float [0.0, 1.0]
    """
    primary = df['H_level'] if 'H_level' in df.columns else df.iloc[:, 4]

    # Forward-fill for EMA/drift only (gap filled just for computation, not stored)
    primary_ff = primary.ffill().bfill()

    F_flat  = _f_flat(primary_ff)
    F_drift = _f_drift(primary_ff)
    F_gap24 = _f_gap24(df)

    s_h = pd.concat([F_flat, F_drift, F_gap24], axis=1).min(axis=1)
    return s_h.clip(0.0, 1.0)


def get_s_h_components(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns DataFrame with S_h and components for forensic logging.
    Columns: s_h, F_flat, F_drift, F_gap24
    """
    primary    = df['H_level'] if 'H_level' in df.columns else df.iloc[:, 4]
    primary_ff = primary.ffill().bfill()

    F_flat  = _f_flat(primary_ff)
    F_drift = _f_drift(primary_ff)
    F_gap24 = _f_gap24(df)

    s_h = pd.concat([F_flat, F_drift, F_gap24], axis=1).min(axis=1).clip(0.0, 1.0)

    flat_duration = _flat_duration(primary_ff)

    return pd.DataFrame({
        's_h':             s_h,
        'F_flat':          F_flat,
        'F_drift':         F_drift,
        'F_gap24':         F_gap24,
        'flat_duration_h': flat_duration,  # horas consecutivas de flatline activo
    }, index=df.index)