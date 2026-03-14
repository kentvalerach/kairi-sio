"""
KAIRI-SIO — src/api/main.py
API REST de scoring hidrológico en tiempo real.

Versión: v1.0 · 2026-03-12
Framework: FastAPI

Endpoints:
  GET  /health                    — estado del sistema
  GET  /confederations            — confederaciones disponibles
  GET  /confederations/{code}     — detalle de una confederación
  POST /score/observation         — scoring de observación individual
  POST /score/batch               — scoring batch (múltiples observaciones)

Despliegue:
  Local:   uvicorn src.api.main:app --reload --port 8000
  Railway: Procfile -> web: uvicorn src.api.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import sys
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.api.schemas import (
    ObservationRequest,
    BatchRequest,
    ScoreResponse,
    BatchResponse,
    BatchObservationResult,
    ScoreComponents,
    ForensicComponents,
    ConfederationInfo,
    HealthResponse,
)
from src.config.confederation_config import (
    load_confederation_config,
    list_available_confederations,
    ConfederationConfig,
)
from src.scoring.scorer import score_embalse
from src.veto.decision_engine import apply_veto
from src.forensics.forensic_logger import _compute_data_hash

logger = logging.getLogger("kairi.api")

# ── App setup ──────────────────────────────────────────────────────────────────

MODEL_VERSION = "kairi-sio-sc-v1.0.0"

app = FastAPI(
    title="KAIRI-SIO · API de Integridad de Señal Hidrológica",
    description=(
        "Sistema determinista de verificación de integridad de señal hidrológica. "
        "Produce un score de coherencia S_c ∈ [0,1] por observación horaria y "
        "clasifica la señal en tres regímenes: CERTIFICADA · DEGRADADA · VETADA.\n\n"
        "**Dominio:** Monitorización operacional de embalses — SAIH Guadalquivir\n"
        "**Autoría:** Reymar (especificación) · Kent Valera Chirinos (implementación)"
    ),
    version="1.0.0",
    contact={
        "name": "Equipo KAIRI",
    },
    license_info={
        "name": "Propietario — KAIRI-SIO",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config cache — evita recargar YAML en cada request ────────────────────────
_cfg_cache: dict[str, ConfederationConfig] = {}


def _get_cfg(confederation: str) -> ConfederationConfig:
    code = confederation.upper()
    if code not in _cfg_cache:
        try:
            _cfg_cache[code] = load_confederation_config(code)
        except FileNotFoundError:
            available = [c["code"] for c in list_available_confederations()]
            raise HTTPException(
                status_code=404,
                detail=f"Confederation '{code}' not found. Available: {available}"
            )
    return _cfg_cache[code]


# ── Helper: construir DataFrame de una sola observación ──────────────────────

def _obs_to_df(obs: ObservationRequest) -> pd.DataFrame:
    """
    Convierte una ObservationRequest en un DataFrame de 1 fila
    compatible con el Data Contract v1.1.

    Para scoring de observación individual, necesitamos al menos 2 filas
    para que las ventanas temporales (diff, rolling) funcionen correctamente.
    Duplicamos la fila con ts-1h como fila anterior.
    """
    ts = pd.Timestamp(obs.ts_station)
    ts_prev = ts - pd.Timedelta(hours=1)
    ts_ingest = pd.Timestamp.now(tz="UTC")

    row = {
        "uuid":       str(uuid.uuid4()),
        "sensor_id":  obs.sensor_id,
        "ts_station": ts,
        "ts_ingest":  ts_ingest,
        "H_level":    obs.H_level,
        "Q_inflow":   obs.Q_inflow,
        "P_rain":     obs.P_rain,
    }
    # Fila anterior sintética (mismos valores) para estabilizar ventanas
    row_prev = {**row, "ts_station": ts_prev, "uuid": str(uuid.uuid4())}

    df = pd.DataFrame([row_prev, row])
    df["ts_station"] = pd.to_datetime(df["ts_station"])
    df["ts_ingest"]  = pd.to_datetime(df["ts_ingest"])
    return df


def _obs_list_to_df(obs_list: list[ObservationRequest], sensor_id: str) -> pd.DataFrame:
    """Convierte lista de ObservationRequest en DataFrame multi-fila."""
    ts_ingest = pd.Timestamp.now(tz="UTC")
    rows = []
    for obs in obs_list:
        rows.append({
            "uuid":       str(uuid.uuid4()),
            "sensor_id":  sensor_id,
            "ts_station": pd.Timestamp(obs.ts_station),
            "ts_ingest":  ts_ingest,
            "H_level":    obs.H_level,
            "Q_inflow":   obs.Q_inflow,
            "P_rain":     obs.P_rain,
        })
    df = pd.DataFrame(rows)
    df["ts_station"] = pd.to_datetime(df["ts_station"])
    df["ts_ingest"]  = pd.to_datetime(df["ts_ingest"])
    return df.sort_values("ts_station").reset_index(drop=True)


def _safe_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return None
    return round(float(val), 4)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Estado del sistema",
    tags=["Sistema"],
)
def health():
    """Verifica que la API está operativa y lista para recibir requests."""
    available = [c["code"] for c in list_available_confederations()]
    return HealthResponse(
        status="ok",
        version=MODEL_VERSION,
        confederation_default="CHG",
        confederations_available=available,
    )


@app.get(
    "/confederations",
    response_model=list[ConfederationInfo],
    summary="Lista de confederaciones disponibles",
    tags=["Confederaciones"],
)
def get_confederations():
    """Devuelve todas las confederaciones configuradas con sus parámetros clave."""
    result = []
    for c in list_available_confederations():
        try:
            cfg = _get_cfg(c["code"])
            result.append(ConfederationInfo(
                code=cfg.code,
                name=cfg.name,
                status=cfg.status,
                lat_critical_s=cfg.lat_critical_s,
                flat_critical_h=cfg.flat_critical_h,
                thresh_certificada=cfg.thresh_certificada,
                thresh_degradada=cfg.thresh_degradada,
                embalses=list(cfg.embalses.keys()),
            ))
        except Exception:
            pass
    return result


@app.get(
    "/confederations/{code}",
    response_model=ConfederationInfo,
    summary="Detalle de una confederación",
    tags=["Confederaciones"],
)
def get_confederation(code: str):
    """Devuelve los parámetros completos de una confederación específica."""
    cfg = _get_cfg(code)
    return ConfederationInfo(
        code=cfg.code,
        name=cfg.name,
        status=cfg.status,
        lat_critical_s=cfg.lat_critical_s,
        flat_critical_h=cfg.flat_critical_h,
        thresh_certificada=cfg.thresh_certificada,
        thresh_degradada=cfg.thresh_degradada,
        embalses=list(cfg.embalses.keys()),
    )


@app.post(
    "/score/observation",
    response_model=ScoreResponse,
    summary="Scoring de observación individual (tiempo real)",
    tags=["Scoring"],
)
def score_observation(request: ObservationRequest):
    """
    Calcula el score de integridad S_c para una observación horaria individual.

    Útil para integración con sistemas SAIH en tiempo real:
    cada nueva lectura del sensor se evalúa de forma inmediata.

    **Regímenes de decisión:**
    - `CERTIFICADA` (S_c ≥ 0.85): dato utilizable sin reservas
    - `DEGRADADA` (0.50 ≤ S_c < 0.85): utilizable con cautela
    - `VETADA` (S_c < 0.50 o CRITICAL_FLAG): no utilizable

    **Nota:** Para una observación aislada, las ventanas históricas (W24, drift)
    no tienen contexto previo — el score S_h puede ser conservador.
    Para mayor precisión use `/score/batch` con serie temporal completa.
    """
    cfg = _get_cfg(request.confederation)

    try:
        df = _obs_to_df(request)
        scored = score_embalse(df, request.sensor_id, detailed=True,
                               confederation_config=cfg)
        veto_df = apply_veto(scored, confederation_config=cfg)
    except Exception as e:
        logger.exception("Scoring failed")
        raise HTTPException(status_code=500, detail=f"Scoring error: {e}")

    # Tomar la última fila (la observación real, no la sintética anterior)
    row = veto_df.iloc[-1]

    return ScoreResponse(
        uuid=str(row.get("uuid", uuid.uuid4())),
        ts_station=pd.Timestamp(row["ts_station"]).isoformat(),
        sensor_id=str(row["sensor_id"]),
        confederation=cfg.code,
        scores=ScoreComponents(
            S_c=_safe_float(row["S_c"]),
            S_f=_safe_float(row["S_f"]),
            S_l=_safe_float(row["S_l"]),
            S_t=_safe_float(row["S_t"]),
            S_h=_safe_float(row["S_h"]),
        ),
        decision=str(row["veto_flag"]),
        veto_level=int(row["veto_level"]),
        critical_flag=bool(row["critical_flag"]),
        reasons=list(row["reasons"]),
        components=ForensicComponents(
            C_PH=_safe_float(row.get("sl_C_PH")),
            C_QH=_safe_float(row.get("sl_C_QH")),
            C_z=_safe_float(row.get("sl_C_z")),
            lat_s=_safe_float(row.get("st_lat_seconds")),
            gap_rate_W1=_safe_float(row.get("st_gap_rate_W1")),
            gap_rate_W24=_safe_float(row.get("sh_F_gap24")),
            F_flat=_safe_float(row.get("sh_F_flat")),
            F_drift=_safe_float(row.get("sh_F_drift")),
        ),
        model_version=MODEL_VERSION,
        data_hash=_compute_data_hash(row),
    )


@app.post(
    "/score/batch",
    response_model=BatchResponse,
    summary="Scoring batch (serie temporal histórica)",
    tags=["Scoring"],
)
def score_batch(request: BatchRequest):
    """
    Calcula el score de integridad para una serie temporal de observaciones.

    Ideal para:
    - Validación de datos históricos SAIH (2015-2024)
    - Auditoría de períodos específicos
    - Demo institucional con datos reales

    Las observaciones deben estar ordenadas por `ts_station` (ascendente).
    El sistema calcula ventanas temporales completas (W1, W24) sobre la serie.

    **Límite:** máximo 10,000 observaciones por request.
    """
    cfg = _get_cfg(request.confederation)

    try:
        df = _obs_list_to_df(request.observations, request.sensor_id)
        scored = score_embalse(df, request.sensor_id, detailed=True,
                               confederation_config=cfg)
        veto_df = apply_veto(scored, confederation_config=cfg)
    except Exception as e:
        logger.exception("Batch scoring failed")
        raise HTTPException(status_code=500, detail=f"Scoring error: {e}")

    n = len(veto_df)
    n_cert = int((veto_df["veto_flag"] == "CERTIFICADA").sum())
    n_deg  = int((veto_df["veto_flag"] == "DEGRADADA").sum())
    n_vet  = int((veto_df["veto_flag"] == "VETADA").sum())
    n_crit = int(veto_df["critical_flag"].sum())
    s_c_mean = float(veto_df["S_c"].mean())

    obs_results = []
    for _, row in veto_df.iterrows():
        reasons = list(row["reasons"])
        obs_results.append(BatchObservationResult(
            ts_station=pd.Timestamp(row["ts_station"]).isoformat(),
            scores=ScoreComponents(
                S_c=_safe_float(row["S_c"]),
                S_f=_safe_float(row["S_f"]),
                S_l=_safe_float(row["S_l"]),
                S_t=_safe_float(row["S_t"]),
                S_h=_safe_float(row["S_h"]),
            ),
            decision=str(row["veto_flag"]),
            veto_level=int(row["veto_level"]),
            critical_flag=bool(row["critical_flag"]),
            primary_reason=reasons[0] if reasons else "",
        ))

    return BatchResponse(
        sensor_id=request.sensor_id,
        confederation=cfg.code,
        n_total=n,
        n_certificada=n_cert,
        n_degradada=n_deg,
        n_vetada=n_vet,
        n_critical=n_crit,
        s_c_mean=round(s_c_mean, 4),
        observations=obs_results,
    )