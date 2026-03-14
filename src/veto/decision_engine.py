"""
KAIRI-SIO — decision_engine.py
Motor de Veto Operativo — Sección 7 de TEC_Formulas_Sc_Veto_v1.0.txt

Reglas exactas de la especificación de Reymar:

CRITICAL_FLAG si:
  * S_f = 0  (imposible físico o None)
  * latencia extrema > 900s
  * incoherencia lógica severa: C_PH = 0.4 Y C_z (worst_z > 6) simultáneo

Decisión:
  CRITICAL_FLAG = True  -> Nivel 2 VETADA
  S_c >= 0.85           -> Nivel 0 CERTIFICADA
  0.50 <= S_c < 0.85    -> Nivel 1 DEGRADADA
  S_c < 0.50            -> Nivel 2 VETADA
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from src.config.confederation_config import ConfederationConfig, load_confederation_config

MODEL_VERSION = "kairi-sio-sc-v1.0.0"

# Valores por defecto — solo usados si no se pasa ConfederationConfig
_DEFAULT_THRESH_CERTIFICADA = 0.85
_DEFAULT_THRESH_DEGRADADA   = 0.50
_DEFAULT_LAT_CRITICAL_S     = 900.0
_DEFAULT_FLAT_CRITICAL_H    = 48.0


@dataclass
class VetoDecision:
    level: int          # 0=CERTIFICADA, 1=DEGRADADA, 2=VETADA
    flag: str           # 'CERTIFICADA' | 'DEGRADADA' | 'VETADA'
    critical: bool
    reasons: list[str]


def _build_reasons(row: pd.Series, cfg: Optional[ConfederationConfig] = None) -> list[str]:
    """
    Build human-readable audit reasons list from scored row.
    These go directly into the forensic JSONL.
    """
    reasons = []
    _lat_crit  = cfg.lat_critical_s  if cfg else _DEFAULT_LAT_CRITICAL_S
    _flat_crit = cfg.flat_critical_h if cfg else _DEFAULT_FLAT_CRITICAL_H

    S_f = row.get('S_f', 1.0)
    S_c = row.get('S_c', 1.0)
    S_t = row.get('S_t', 1.0)

    # Physical
    if S_f == 0.0:
        reasons.append("S_f=0: physically impossible value or missing critical field")
    if row.get('sf_flag_H_level_range', False):
        reasons.append("H_level out of physical range")
    if row.get('sf_flag_Q_inflow_range', False):
        reasons.append("Q_inflow out of physical range")
    if row.get('sf_flag_P_rain_range', False):
        reasons.append("P_rain out of physical range")
    if row.get('sf_flag_negative', False):
        reasons.append("Negative value in non-negative field")

    # Temporal
    lat = row.get('st_lat_seconds', 0.0)
    if lat > _lat_crit:
        reasons.append(f"Critical latency: {lat:.0f}s > {_lat_crit:.0f}s threshold")
    elif lat > 300:
        reasons.append(f"High latency: {lat:.0f}s")
    gap_W1 = row.get('st_gap_rate_W1', 0.0)
    if gap_W1 > 0:
        reasons.append(f"Gap rate W1: {gap_W1:.2%} of expected observations missing")

    # Logical
    C_PH = row.get('sl_C_PH', 1.0)
    C_QH = row.get('sl_C_QH', 1.0)
    C_z  = row.get('sl_C_z',  1.0)
    if C_PH == 0.4:
        reasons.append("C_PH=0.4: level rising with no rain — incoherence probable")
    elif C_PH == 0.7:
        reasons.append("C_PH=0.7: level falling with no rain — possible release")
    if C_QH == 0.5:
        reasons.append("C_QH=0.5: inflow/level relationship incoherent")
    if C_z == 0.3:
        reasons.append("C_z=0.3: robust z-score > 6 — statistical outlier")
    elif C_z == 0.7:
        reasons.append("C_z=0.7: robust z-score 3–6 — moderate anomaly")

    # Historical health
    F_flat       = row.get('sh_F_flat',          1.0)
    F_drift      = row.get('sh_F_drift',         1.0)
    F_gap24      = row.get('sh_F_gap24',         1.0)
    flat_dur_h   = row.get('sh_flat_duration_h', 0.0)
    if F_flat == 0.2:
        if flat_dur_h >= _flat_crit:
            reasons.append(f"F_flat=0.2: flatline {flat_dur_h:.0f}h >= {_flat_crit:.0f}h threshold -> CRITICAL")
        else:
            reasons.append("F_flat=0.2: flatline >= 8 consecutive identical values")
    if F_drift == 0.3:
        reasons.append("F_drift=0.3: EMA drift anomaly — slow sensor degradation signal")
    if F_gap24 == 0.2:
        reasons.append("F_gap24=0.2: gap rate W24 >= 30%")
    elif F_gap24 == 0.6:
        reasons.append("F_gap24=0.6: gap rate W24 >= 10%")

    # S_c level reason
    _thresh_c = cfg.thresh_certificada if cfg else _DEFAULT_THRESH_CERTIFICADA
    _thresh_d = cfg.thresh_degradada   if cfg else _DEFAULT_THRESH_DEGRADADA
    if S_c < _thresh_d:
        reasons.append(f"S_c={S_c:.4f} < {_thresh_d} threshold -> VETADA")
    elif S_c < _thresh_c:
        reasons.append(f"S_c={S_c:.4f} in [{_thresh_d}, {_thresh_c}) -> DEGRADADA")

    if not reasons:
        reasons.append(f"S_c={S_c:.4f} >= {_thresh_c} -> CERTIFICADA")

    return reasons


def decide_row(
    row: pd.Series,
    cfg: Optional[ConfederationConfig] = None,
) -> VetoDecision:
    """
    Apply veto logic to a single scored row.
    Expects detailed scored DataFrame row (with sf_, sl_, st_, sh_ sub-columns).

    Parameters
    ----------
    row : scored DataFrame row
    cfg : ConfederationConfig — if None uses defaults (CHG)
    """
    lat_critical_s  = cfg.lat_critical_s  if cfg else _DEFAULT_LAT_CRITICAL_S
    flat_critical_h = cfg.flat_critical_h if cfg else _DEFAULT_FLAT_CRITICAL_H
    thresh_c        = cfg.thresh_certificada if cfg else _DEFAULT_THRESH_CERTIFICADA
    thresh_d        = cfg.thresh_degradada   if cfg else _DEFAULT_THRESH_DEGRADADA

    S_f        = row.get('S_f',               1.0)
    S_c        = row.get('S_c',               1.0)
    lat        = row.get('st_lat_seconds',    0.0)
    C_PH       = row.get('sl_C_PH',          1.0)
    C_z        = row.get('sl_C_z',           1.0)
    F_flat     = row.get('sh_F_flat',         1.0)
    flat_dur_h = row.get('sh_flat_duration_h', 0.0)

    # CRITICAL_FLAG conditions (TEC_Formulas v1.1 §7.2)
    critical = (
        (S_f == 0.0) or
        (lat > lat_critical_s) or
        (C_PH == 0.4 and C_z == 0.3) or
        (F_flat == 0.2 and flat_dur_h >= flat_critical_h)
    )

    reasons = _build_reasons(row, cfg)

    if critical:
        if "CRITICAL_FLAG" not in reasons[0]:
            reasons.insert(0, "CRITICAL_FLAG triggered")
        return VetoDecision(level=2, flag='VETADA', critical=True, reasons=reasons)

    if S_c >= thresh_c:
        return VetoDecision(level=0, flag='CERTIFICADA', critical=False, reasons=reasons)
    elif S_c >= thresh_d:
        return VetoDecision(level=1, flag='DEGRADADA', critical=False, reasons=reasons)
    else:
        return VetoDecision(level=2, flag='VETADA', critical=False, reasons=reasons)


def apply_veto(
    scored_df: pd.DataFrame,
    confederation_config: Optional[ConfederationConfig] = None,
) -> pd.DataFrame:
    """
    Apply veto engine to full scored DataFrame.
    Adds columns: veto_level (int), veto_flag (str), critical_flag (bool), reasons (list).

    Parameters
    ----------
    scored_df            : detailed scored DataFrame (scorer.score_embalse with detailed=True)
    confederation_config : ConfederationConfig — if None uses CHG defaults

    Returns
    -------
    Same DataFrame with veto columns added
    """
    cfg = confederation_config or load_confederation_config()
    results = []
    for _, row in scored_df.iterrows():
        d = decide_row(row, cfg)
        results.append({
            'veto_level':    d.level,
            'veto_flag':     d.flag,
            'critical_flag': d.critical,
            'reasons':       d.reasons,
        })

    veto_df = pd.DataFrame(results, index=scored_df.index)
    return pd.concat([scored_df, veto_df], axis=1)