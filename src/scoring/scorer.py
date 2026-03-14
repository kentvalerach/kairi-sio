"""
KAIRI-SIO — scorer.py
Main scoring pipeline: computes S_c for a curated DataFrame.

S_c = clamp01(0.40*S_f + 0.30*S_l + 0.20*S_t + 0.10*S_h)

Quality flags:
  CERTIFICADA : S_c >= 0.85
  DEGRADADA   : 0.50 <= S_c < 0.85
  VETADA      : S_c < 0.50 or CRITICAL_FLAG

CRITICAL_FLAG conditions (auto-VETADA regardless of S_c):
  - S_f == 0.0 (physically impossible value)
  - S_t < 0.1 (severe temporal failure)
"""

import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import logging
from datetime import datetime, timezone
from typing import Optional

from src.scoring.s_f import compute_s_f, get_s_f_flags
from src.scoring.s_t import compute_s_t, get_s_t_components
from src.scoring.s_l import compute_s_l, get_s_l_components
from src.scoring.s_h import compute_s_h, get_s_h_components
from src.config.confederation_config import ConfederationConfig, load_confederation_config

logger = logging.getLogger(__name__)

# Invariantes fisicos — no dependen de confederacion
_CRITICAL_SF_THRESHOLD = 0.0   # S_f == 0 -> physically impossible
_CRITICAL_ST_THRESHOLD = 0.1   # S_t < 0.1 -> severe temporal gap


def _quality_flag(
    s_c: pd.Series,
    critical: pd.Series,
    thresh_certificada: float,
    thresh_degradada: float,
) -> pd.Series:
    """Map S_c + critical bool to quality flag string."""
    flags = pd.Series('DEGRADADA', index=s_c.index)
    flags[s_c >= thresh_certificada] = 'CERTIFICADA'
    flags[s_c <  thresh_degradada]   = 'VETADA'
    flags[critical]                  = 'VETADA'
    return flags


def score_embalse(
    df: pd.DataFrame,
    embalse_id: str,
    detailed: bool = False,
    confederation_config: Optional[ConfederationConfig] = None,
) -> pd.DataFrame:
    """
    Compute full scoring for one embalse.

    Parameters
    ----------
    df                   : curated DataFrame (Data Contract v1.1)
    embalse_id           : e.g. 'E32_VADOMOJON'
    detailed             : if True, include all sub-component columns
    confederation_config : ConfederationConfig from load_confederation_config().
                           If None, loads CHG defaults.

    Returns
    -------
    pd.DataFrame with columns:
        uuid, sensor_id, ts_station, ts_ingest,
        H_level, Q_inflow, P_rain,
        S_f, S_l, S_t, S_h, S_c,
        quality_flag, confederation,
        [if detailed: s_f flags, S_l components, S_t components, S_h components]
    """
    cfg = confederation_config or load_confederation_config()
    w   = cfg.weights
    W_F = w['w_f']; W_L = w['w_l']; W_T = w['w_t']; W_H = w['w_h']
    thresh_certificada = cfg.thresh_certificada
    thresh_degradada   = cfg.thresh_degradada
    lat_cfg            = cfg.latency_config

    logger.info(f"Scoring {embalse_id} ({len(df)} rows) [confederation={cfg.code}]...")
    df = df.sort_values('ts_station').reset_index(drop=True)

    # ── Compute sub-scores ────────────────────────────────────────────────
    if detailed:
        sf_detail = get_s_f_flags(df, embalse_id)
        sl_detail = get_s_l_components(df)
        st_detail = get_s_t_components(df, latency_config=lat_cfg)
        sh_detail = get_s_h_components(df)
        S_f = sf_detail['s_f']
        S_l = sl_detail['s_l']
        S_t = st_detail['s_t']
        S_h = sh_detail['s_h']
    else:
        S_f = compute_s_f(df, embalse_id)
        S_l = compute_s_l(df)
        S_t = compute_s_t(df, latency_config=lat_cfg)
        S_h = compute_s_h(df)

    # ── S_c composite ────────────────────────────────────────────────────
    S_c = (W_F * S_f + W_L * S_l + W_T * S_t + W_H * S_h).clip(0.0, 1.0)

    # ── CRITICAL_FLAG ────────────────────────────────────────────────────
    critical = (S_f <= _CRITICAL_SF_THRESHOLD) | (S_t < _CRITICAL_ST_THRESHOLD)

    # ── Quality flag ─────────────────────────────────────────────────────
    quality_flag = _quality_flag(S_c, critical, thresh_certificada, thresh_degradada)

    # ── Assemble result ───────────────────────────────────────────────────
    base_cols = ['uuid', 'sensor_id', 'ts_station', 'ts_ingest',
                 'H_level', 'Q_inflow', 'P_rain']
    result = df[base_cols].copy()
    result['S_f'] = S_f.values
    result['S_l'] = S_l.values
    result['S_t'] = S_t.values
    result['S_h'] = S_h.values
    result['S_c'] = S_c.values
    result['quality_flag'] = quality_flag.values
    result['confederation'] = cfg.code

    if detailed:
        for col in sf_detail.columns:
            if col != 's_f':
                result[f'sf_{col}'] = sf_detail[col].values
        for col in sl_detail.columns:
            if col != 's_l':
                result[f'sl_{col}'] = sl_detail[col].values
        for col in st_detail.columns:
            if col != 's_t':
                result[f'st_{col}'] = st_detail[col].values
        for col in sh_detail.columns:
            if col != 's_h':
                result[f'sh_{col}'] = sh_detail[col].values

    # ── Log summary ───────────────────────────────────────────────────────
    n = len(result)
    n_cert = (quality_flag == 'CERTIFICADA').sum()
    n_deg  = (quality_flag == 'DEGRADADA').sum()
    n_vet  = (quality_flag == 'VETADA').sum()
    logger.info(f"  S_c mean={S_c.mean():.4f}  std={S_c.std():.4f}  "
                f"min={S_c.min():.4f}  max={S_c.max():.4f}")
    logger.info(f"  Confederation: {cfg.code}")
    logger.info(f"  CERTIFICADA: {n_cert:6,} ({n_cert/n*100:.1f}%)")
    logger.info(f"  DEGRADADA  : {n_deg:6,} ({n_deg/n*100:.1f}%)")
    logger.info(f"  VETADA     : {n_vet:6,} ({n_vet/n*100:.1f}%)")

    return result


def save_analytic(
    df: pd.DataFrame,
    embalse_id: str,
    analytic_dir: Path | str,
) -> Path:
    """Save scored DataFrame to ANALYTIC_ZONE as Parquet."""
    analytic_dir = Path(analytic_dir)
    analytic_dir.mkdir(parents=True, exist_ok=True)
    out_path = analytic_dir / f"{embalse_id}_scored.parquet"
    df.to_parquet(out_path, index=False, engine='pyarrow')
    size_kb = out_path.stat().st_size / 1024
    logger.info(f"Saved {embalse_id} -> {out_path} ({size_kb:.1f} KB)")
    return out_path