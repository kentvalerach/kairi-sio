"""
KAIRI-SIO — forensic_logger.py
Registro Forense JSONL — Sección 8 de TEC_Formulas_Sc_Veto_v1.0.txt

Formato exacto de la especificación de Reymar:
{
  "uuid":          UUIDv4,
  "ts_ingest":     ISO8601,
  "ts_station":    ISO8601,
  "sensor_id":     "...",
  "window":        {"W1": "1h", "W24": "24h"},
  "scores":        {"S_c":..., "S_f":..., "S_l":..., "S_t":..., "S_h":...},
  "components":    {"C_PH":..., "C_QH":..., "C_z":..., "lat_s":...,
                    "gap_rate_W1":..., "gap_rate_W24":...},
  "decision":      "CERTIFICADA|DEGRADADA|VETADA",
  "veto_level":    0|1|2,
  "critical_flag": bool,
  "reasons":       ["...", "..."],
  "model_version": "kairi-sio-sc-v1.0.0",
  "code_hash":     "<git_commit_hash or NO_GIT>",
  "data_hash":     "<sha256 de la ventana de datos>"
}

Principio: APPEND-ONLY. Nunca se modifica un registro existente.
"""

import json
import hashlib
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

MODEL_VERSION = "kairi-sio-sc-v1.0.0"


def _get_code_hash() -> str:
    """Get current git commit hash. Returns 'NO_GIT' if not in a repo."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]   # short hash, 12 chars
    except Exception:
        pass
    return 'NO_GIT'


def _compute_data_hash(row: pd.Series) -> str:
    """
    SHA-256 of the data window used for this decision.
    Uses stable CSV serialization of the observation values.
    """
    fields = ['ts_station', 'H_level', 'Q_inflow', 'P_rain']
    parts = []
    for f in fields:
        val = row.get(f)
        if pd.isna(val) if not isinstance(val, str) else False:
            parts.append(f"{f}=None")
        elif isinstance(val, (pd.Timestamp, datetime)):
            parts.append(f"{f}={val.isoformat()}")
        else:
            parts.append(f"{f}={val}")
    stable_str = ','.join(parts)
    return hashlib.sha256(stable_str.encode('utf-8')).hexdigest()[:16]


def _row_to_event(row: pd.Series, code_hash: str) -> dict:
    """Convert a single veto-applied row to a forensic event dict."""

    def _safe_float(val, decimals=4):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        return round(float(val), decimals)

    def _safe_ts(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        if isinstance(val, (pd.Timestamp, datetime)):
            return val.isoformat()
        return str(val)

    event = {
        "uuid":         str(row.get('uuid', uuid.uuid4())),
        "ts_ingest":    _safe_ts(row.get('ts_ingest')),
        "ts_station":   _safe_ts(row.get('ts_station')),
        "sensor_id":    str(row.get('sensor_id', '')),
        "window":       {"W1": "1h", "W24": "24h"},
        "scores": {
            "S_c": _safe_float(row.get('S_c')),
            "S_f": _safe_float(row.get('S_f')),
            "S_l": _safe_float(row.get('S_l')),
            "S_t": _safe_float(row.get('S_t')),
            "S_h": _safe_float(row.get('S_h')),
        },
        "components": {
            "C_PH":         _safe_float(row.get('sl_C_PH')),
            "C_QH":         _safe_float(row.get('sl_C_QH')),
            "C_z":          _safe_float(row.get('sl_C_z')),
            "lat_s":        _safe_float(row.get('st_lat_seconds'), 1),
            "gap_rate_W1":  _safe_float(row.get('st_gap_rate_W1')),
            "gap_rate_W24": _safe_float(row.get('sh_F_gap24')),
            "F_flat":       _safe_float(row.get('sh_F_flat')),
            "F_drift":      _safe_float(row.get('sh_F_drift')),
        },
        "decision":      str(row.get('veto_flag',  row.get('quality_flag', 'UNKNOWN'))),
        "veto_level":    int(row.get('veto_level', -1)),
        "critical_flag": bool(row.get('critical_flag', False)),
        "reasons":       list(row.get('reasons', [])),
        "model_version": MODEL_VERSION,
        "code_hash":     code_hash,
        "data_hash":     _compute_data_hash(row),
    }
    return event


def write_forensic_jsonl(
    veto_df: pd.DataFrame,
    output_path: Path | str,
    mode: str = 'append',
    filter_level: int | None = None,
) -> int:
    """
    Write forensic JSONL file. APPEND-ONLY by default.

    Parameters
    ----------
    veto_df      : DataFrame with veto columns applied (output of decision_engine.apply_veto)
    output_path  : path to .jsonl file (created if not exists)
    mode         : 'append' (default, immutable) or 'overwrite' (only for testing)
    filter_level : if set, only write rows with veto_level >= filter_level
                   e.g. filter_level=1 writes DEGRADADA + VETADA only
                   filter_level=None writes ALL rows

    Returns
    -------
    int: number of events written
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    code_hash = _get_code_hash()
    file_mode = 'a' if mode == 'append' else 'w'

    n_written = 0
    with open(output_path, file_mode, encoding='utf-8') as f:
        for _, row in veto_df.iterrows():
            # Apply level filter
            if filter_level is not None:
                level = row.get('veto_level', 0)
                if isinstance(level, (int, float)) and level < filter_level:
                    continue

            event = _row_to_event(row, code_hash)
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
            n_written += 1

    logger.info(f"Forensic JSONL: {n_written} events -> {output_path} (mode={mode})")
    return n_written


def write_forensic_summary_csv(
    veto_df: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """
    Write a lightweight CSV summary of all decisions.
    This is the human-readable complement to the JSONL.

    Columns: ts_station, sensor_id, S_c, S_f, S_l, S_t, S_h,
             veto_level, veto_flag, critical_flag, primary_reason
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ['ts_station', 'sensor_id',
            'S_c', 'S_f', 'S_l', 'S_t', 'S_h',
            'veto_level', 'veto_flag', 'critical_flag']

    summary = veto_df[cols].copy()
    summary['primary_reason'] = veto_df['reasons'].apply(
        lambda r: r[0] if isinstance(r, list) and len(r) > 0 else ''
    )
    summary.to_csv(output_path, index=False)
    logger.info(f"Summary CSV: {len(summary)} rows -> {output_path}")
    return output_path