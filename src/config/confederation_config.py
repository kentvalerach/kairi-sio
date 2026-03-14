"""
KAIRI-SIO — confederation_config.py
Loader de configuración por confederación hidrográfica.

Lee el YAML correspondiente de src/config/confederations/<CODE>.yaml
y expone un objeto ConfederationConfig con acceso tipado a todos los parámetros.

Uso:
    from src.config.confederation_config import load_confederation_config
    cfg = load_confederation_config('CHG')

    cfg.weights           # {'w_f': 0.40, ...}
    cfg.lat_critical_s    # 900  (derivado de lat_breakpoints_s[-1])
    cfg.flat_critical_h   # 48   (alias de flatline_critical_hours)
    cfg.get_embalse_bounds('E32_VADOMOJON')
    cfg.latency_config    # dict compatible con s_t.compute_s_t()
"""

from __future__ import annotations

import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONF_DIR = Path(__file__).parent / "confederations"
DEFAULT_CONFEDERATION = "CHG"


class ConfederationConfig:
    """Configuración completa de una confederación hidrográfica."""

    def __init__(self, code, name, status, weights,
                 thresh_certificada, thresh_degradada,
                 lat_breakpoints_s, lat_scores,
                 gap_warn, gap_fail,
                 flatline_k_hours, flatline_critical_hours,
                 drift_threshold, spike_h_level_m_per_h,
                 embalses=None):
        self.code   = code
        self.name   = name
        self.status = status
        self.weights = weights
        self.thresh_certificada = thresh_certificada
        self.thresh_degradada   = thresh_degradada
        self.lat_breakpoints_s  = lat_breakpoints_s
        self.lat_scores         = lat_scores
        self.gap_warn = gap_warn
        self.gap_fail = gap_fail
        self.flatline_k_hours        = flatline_k_hours
        self.flatline_critical_hours = flatline_critical_hours
        self.drift_threshold         = drift_threshold
        self.spike_h_level_m_per_h   = spike_h_level_m_per_h
        self.embalses = embalses or {}

    @property
    def lat_critical_s(self):
        """LAT_CRITICAL_S — ultimo breakpoint de latencia."""
        return self.lat_breakpoints_s[-1]

    @property
    def flat_critical_h(self):
        """Alias legible para flatline_critical_hours."""
        return self.flatline_critical_hours

    @property
    def latency_config(self):
        """Dict compatible con s_t.compute_s_t(latency_config=...)."""
        return {
            "lat_breakpoints_s": self.lat_breakpoints_s,
            "lat_scores":        self.lat_scores,
            "lat_critical_s":    self.lat_critical_s,
            "confederation":     self.code,
        }

    def get_embalse_bounds(self, embalse_id):
        """Return physical bounds dict or None if not configured."""
        return self.embalses.get(embalse_id)

    def log_summary(self):
        logger.info(f"ConfederationConfig: [{self.code}] {self.name} ({self.status})")
        logger.info(f"  Weights    : w_f={self.weights['w_f']} w_l={self.weights['w_l']} "
                    f"w_t={self.weights['w_t']} w_h={self.weights['w_h']}")
        logger.info(f"  Thresholds : CERTIFICADA>={self.thresh_certificada} "
                    f"DEGRADADA>={self.thresh_degradada}")
        logger.info(f"  Latency    : breakpoints={self.lat_breakpoints_s}s "
                    f"critical={self.lat_critical_s}s")
        logger.info(f"  Flatline   : K={self.flatline_k_hours}h "
                    f"CRITICAL={self.flatline_critical_hours}h")
        logger.info(f"  Embalses   : {list(self.embalses.keys()) or '(none configured)'}")

    def __repr__(self):
        return (f"ConfederationConfig(code={self.code!r}, status={self.status!r}, "
                f"lat_critical_s={self.lat_critical_s}, "
                f"flat_critical_h={self.flat_critical_h}, "
                f"embalses={list(self.embalses.keys())})")


def load_confederation_config(confederation=None, config_dir=None):
    """
    Load confederation config from YAML file.

    Parameters
    ----------
    confederation : str or None — e.g. 'CHG', 'CHE'. Defaults to 'CHG'.
    config_dir    : Path or None — override YAML directory.

    Raises
    ------
    FileNotFoundError, ValueError
    """
    code      = (confederation or DEFAULT_CONFEDERATION).upper()
    conf_dir  = Path(config_dir) if config_dir else _CONF_DIR
    yaml_path = conf_dir / f"{code}.yaml"

    if not yaml_path.exists():
        available = [p.stem for p in sorted(conf_dir.glob("*.yaml"))]
        raise FileNotFoundError(
            f"No configuration found for '{code}'. "
            f"Available: {available}. Path: {yaml_path}"
        )

    with open(yaml_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    try:
        cb  = raw["confederation"]
        w   = raw["weights"]
        th  = raw["thresholds"]
        lat = raw["latency"]
        g   = raw["gaps"]
        fl  = raw["flatline"]
        dr  = raw["drift"]
        sp  = raw["spike"]
        emb = raw.get("embalses") or {}

        cfg = ConfederationConfig(
            code   = cb["code"],
            name   = cb["name"],
            status = cb.get("status", "placeholder"),
            weights = {k: float(w[k]) for k in ("w_f", "w_l", "w_t", "w_h")},
            thresh_certificada = float(th["certificada"]),
            thresh_degradada   = float(th["degradada"]),
            lat_breakpoints_s  = [int(x) for x in lat["breakpoints_s"]],
            lat_scores         = [float(x) for x in lat["scores"]],
            gap_warn           = float(g["warn"]),
            gap_fail           = float(g["fail"]),
            flatline_k_hours        = int(fl["k_hours"]),
            flatline_critical_hours = int(fl["critical_hours"]),
            drift_threshold         = float(dr["threshold"]),
            spike_h_level_m_per_h   = float(sp["h_level_m_per_h"]),
            embalses = emb,
        )
    except KeyError as e:
        raise ValueError(f"Invalid YAML in {yaml_path}: missing key {e}") from e

    cfg.log_summary()
    return cfg


def list_available_confederations(config_dir=None):
    """List all confederation YAMLs. Returns list of dicts with code/name/status."""
    conf_dir = Path(config_dir) if config_dir else _CONF_DIR
    result = []
    for yaml_path in sorted(conf_dir.glob("*.yaml")):
        try:
            with open(yaml_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            block = raw.get("confederation", {})
            result.append({
                "code":   block.get("code", yaml_path.stem),
                "name":   block.get("name", ""),
                "status": block.get("status", "unknown"),
            })
        except Exception:
            result.append({"code": yaml_path.stem, "name": "", "status": "error"})
    return result