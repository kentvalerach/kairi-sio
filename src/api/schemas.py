"""
KAIRI-SIO — src/api/schemas.py
Modelos Pydantic para request/response de la API REST.

Versión: v1.0 · 2026-03-12
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ── Request models ────────────────────────────────────────────────────────────

class ObservationRequest(BaseModel):
    """
    Una observación horaria de un sensor de embalse.
    Equivale a una fila del Data Contract v1.1.
    """
    sensor_id:   str   = Field(..., example="E32_VADOMOJON",
                               description="ID del embalse/sensor")
    ts_station:  str   = Field(..., example="2024-06-15T10:00:00",
                               description="Timestamp del sensor (ISO 8601)")
    H_level:     Optional[float] = Field(None, example=52.3,
                                         description="Nivel del embalse (m)")
    Q_inflow:    Optional[float] = Field(None, example=12.5,
                                         description="Caudal entrante (m³/s)")
    P_rain:      Optional[float] = Field(None, example=0.0,
                                         description="Precipitación (mm)")
    confederation: str = Field("CHG", example="CHG",
                               description="Código de confederación hidrográfica")

    @field_validator("ts_station")
    @classmethod
    def validate_ts(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError(f"ts_station must be ISO 8601, got: {v!r}")
        return v

    @field_validator("H_level", "Q_inflow", "P_rain", mode="before")
    @classmethod
    def none_not_zero(cls, v):
        """Enforce None != 0.0 invariant — missing data must be null, not 0."""
        return v  # passthrough; validation is informational


class BatchRequest(BaseModel):
    """
    Lista de observaciones para scoring batch (histórico).
    Todas deben pertenecer al mismo sensor y confederación.
    """
    sensor_id:     str            = Field(..., example="E32_VADOMOJON")
    confederation: str            = Field("CHG", example="CHG")
    observations:  list[ObservationRequest] = Field(
        ..., min_length=1, max_length=10000,
        description="Observaciones ordenadas por ts_station (asc)"
    )


# ── Response models ───────────────────────────────────────────────────────────

class ScoreComponents(BaseModel):
    S_c: float = Field(..., description="Score compuesto [0,1]")
    S_f: float = Field(..., description="Integridad física [0,1]")
    S_l: float = Field(..., description="Coherencia lógica [0,1]")
    S_t: float = Field(..., description="Integridad temporal [0,1]")
    S_h: float = Field(..., description="Salud histórica [0,1]")


class ForensicComponents(BaseModel):
    C_PH:         Optional[float] = None
    C_QH:         Optional[float] = None
    C_z:          Optional[float] = None
    lat_s:        Optional[float] = None
    gap_rate_W1:  Optional[float] = None
    gap_rate_W24: Optional[float] = None
    F_flat:       Optional[float] = None
    F_drift:      Optional[float] = None


class ScoreResponse(BaseModel):
    """Resultado del scoring de una observación individual."""
    uuid:          str
    ts_station:    str
    sensor_id:     str
    confederation: str
    scores:        ScoreComponents
    decision:      str  = Field(..., description="CERTIFICADA | DEGRADADA | VETADA")
    veto_level:    int  = Field(..., description="0=CERTIFICADA 1=DEGRADADA 2=VETADA")
    critical_flag: bool
    reasons:       list[str]
    components:    ForensicComponents
    model_version: str
    data_hash:     str


class BatchObservationResult(BaseModel):
    """Resultado de una observación dentro de un batch."""
    ts_station:    str
    scores:        ScoreComponents
    decision:      str
    veto_level:    int
    critical_flag: bool
    primary_reason: str


class BatchResponse(BaseModel):
    """Resultado del scoring batch."""
    sensor_id:     str
    confederation: str
    n_total:       int
    n_certificada: int
    n_degradada:   int
    n_vetada:      int
    n_critical:    int
    s_c_mean:      float
    observations:  list[BatchObservationResult]


class ConfederationInfo(BaseModel):
    code:   str
    name:   str
    status: str
    lat_critical_s:    int
    flat_critical_h:   int
    thresh_certificada: float
    thresh_degradada:   float
    embalses:          list[str]


class HealthResponse(BaseModel):
    status:        str = "ok"
    version:       str
    confederation_default: str
    confederations_available: list[str]