# STATEMENT OF WORK
## KAIRI-SIO — Sistema de Integridad Operativa para Datos Hidrológicos
### MVP Sprint 0–3 | 9 – 11 de marzo de 2026

---

| Campo | Detalle |
|---|---|
| **Proyecto** | KAIRI-SIO |
| **Versión SOW** | v1.0 |
| **Período de ejecución** | 9 – 11 de marzo de 2026 |
| **Ingeniería** | Kent Valera Chirinos |
| **Concepto y especificación matemática** | Reymar (Dinamarca) |
| **Estado al cierre** | MVP funcionalmente completo — Sprint 0–3 ejecutados |
| **Repositorio local** | `C:\KAIRI-SIO\` |
| **Entorno** | Python 3.12 — virtualenv `.venv` |

---

## 1. ORIGEN Y CONTEXTO DEL PROYECTO

El proyecto KAIRI-SIO fue propuesto por Reymar, un colaborador externo basado en Dinamarca, a través del documento `20260301_REQ_Definicion_Nuclear_v1.0.pdf`. La propuesta identificó correctamente un problema real: los sistemas actuales de monitorización hidrológica (SAIH, SCADA) generan grandes volúmenes de datos en tiempo real, pero sin una capa independiente que verifique sistemáticamente la coherencia física y temporal de esas señales.

Kent evaluó la propuesta y estableció los términos de colaboración: bajo compromiso inicial, exploración técnica, sin agenda comercial prematura. La decisión fue construir un MVP honesto antes de cualquier conversación institucional.

**Principio fundamental: KAIRI-SIO no sustituye al SAIH. Actúa como una capa adicional de verificación determinista e independiente.**

### Aporte de Reymar

- `20260301_REQ_Definicion_Nuclear_v1.0.pdf` — propuesta conceptual del proyecto
- `20260301_TEC_Formulas_Sc_Veto_v1.0.txt` — especificación matemática completa e implementable
- 18 ficheros xlsx SAIH Guadalquivir (datos reales 2015–2024) de 3 embalses
- Data Contract v1.1, arquitectura 3 zonas, protocolo forense (sección 8)

---

## 2. ESPECIFICACIÓN MATEMÁTICA

### 2.1 Score Global de Confianza

```
S_c(s,t) = clamp01( 0.40·S_f + 0.30·S_l + 0.20·S_t + 0.10·S_h )
```

| Componente | Peso | Descripción |
|---|---|---|
| **S_f** | 0.40 | Integridad física — rangos absolutos por embalse, no-negatividad |
| **S_l** | 0.30 | Coherencia lógica multivariante — lluvia↔nivel↔caudal + z-score robusto MAD |
| **S_t** | 0.20 | Integridad temporal — latencia piecewise + gap rate W1 (1h) |
| **S_h** | 0.10 | Salud histórica del sensor — flatline, drift EMA, gap rate W24 (24h) |

### 2.2 Motor de Veto

| Nivel | Flag | Condición |
|---|---|---|
| 0 | **CERTIFICADA** | S_c ≥ 0.85 |
| 1 | **DEGRADADA** | 0.50 ≤ S_c < 0.85 |
| 2 | **VETADA** | S_c < 0.50 **ó** CRITICAL_FLAG activo |

**CRITICAL_FLAG** se activa si: `S_f == 0.0` | `lat > 900s` | `C_PH == 0.4 AND C_z == 0.3`

### 2.3 Fórmulas completas de sub-scores

```python
# S_l = min(C_PH, C_QH, C_z)
# C_PH: 1.0 si lluvia>=P_min ó |ΔH|<=eps_H | 0.4 sin lluvia y nivel sube | 0.7 nivel baja
# C_QH: 1.0 normal | 0.5 si Q>p90 y ΔH~0 | 0.5 si Q=0 y |ΔH|>p99
# C_z : 1.0 z<=3 | 0.7 z<=6 | 0.3 z>6   (rolling 24h, MAD)

# S_t = L(lat) * G(gap_rate_W1)
# L: 1.0 lat<=60s | 0.7 lat<=300s | 0.4 lat<=900s | 0.1 lat>900s

# S_h = min(F_flat, F_drift, F_gap24)
# F_flat:  0.2 si >=8 valores idénticos consecutivos
# F_drift: 0.3 si |EMA_6h - EMA_24h| / (std_24h + 1e-6) > 3.0
# F_gap24: 0.2 gap_rate>=30% | 0.6 gap_rate>=10%
```

### 2.4 Formato JSONL forense (spec Reymar sección 8)

```json
{
  "uuid":          "6580fd40-9f6c-453d-acce-c233a107a8cb",
  "ts_ingest":     "2026-03-11T19:29:07Z",
  "ts_station":    "2015-03-29T04:00:00",
  "sensor_id":     "E32_VADOMOJON",
  "window":        {"W1": "1h", "W24": "24h"},
  "scores":        {"S_c": 0.74, "S_f": 1.0, "S_l": 1.0, "S_t": 0.1, "S_h": 0.2},
  "components":    {"C_PH": 1.0, "C_QH": 1.0, "C_z": 1.0,
                    "lat_s": 3600.0, "gap_rate_W1": 0.0, "gap_rate_W24": 1.0,
                    "F_flat": 0.2, "F_drift": 1.0},
  "decision":      "VETADA",
  "veto_level":    2,
  "critical_flag": true,
  "reasons":       ["CRITICAL_FLAG triggered",
                    "Critical latency: 3600s > 900s threshold",
                    "F_flat=0.2: flatline >= 8 consecutive identical values"],
  "model_version": "kairi-sio-sc-v1.0.0",
  "code_hash":     "NO_GIT",
  "data_hash":     "065d354b66b9fe2d"
}
```

---

## 3. ARQUITECTURA DE DATOS

```
C:\KAIRI-SIO\
├── data\
│   ├── raw\saih_guadalquivir\     ← LANDING_ZONE (inmutable, solo lectura)
│   │   ├── E32_VADOMOJON\{Nivel, Aportacion, Precipitacion}\
│   │   ├── E33_SRRA_BOYERA\
│   │   └── E37_BEMBEZAR\
│   ├── curated\                   ← CURATED_ZONE — Data Contract v1.1 (Parquet)
│   │   ├── E32_VADOMOJON.parquet
│   │   ├── E33_SRRA_BOYERA.parquet
│   │   └── E37_BEMBEZAR.parquet
│   └── analytic\                  ← ANALYTIC_ZONE — scored (Parquet)
│       ├── E32_VADOMOJON_scored.parquet
│       ├── E33_SRRA_BOYERA_scored.parquet
│       └── E37_BEMBEZAR_scored.parquet
└── output\forensics\              ← OUTPUT — JSONL append-only + CSV
    ├── E32_VADOMOJON_forensic_20260311T192907.jsonl
    ├── E32_VADOMOJON_summary_20260311T192907.csv
    ├── E33_SRRA_BOYERA_forensic_20260311T192907.jsonl
    └── E37_BEMBEZAR_forensic_20260311T192907.jsonl
```

**Data Contract v1.1:** `uuid` | `sensor_id` | `ts_station` | `ts_ingest` | `H_level` | `Q_inflow` | `P_rain` | `source_files`

**Invariante cardinal: `None ≠ 0.0` — dato faltante siempre `None`, nunca imputado a cero.**

---

## 4. DATOS FUENTE

| Embalse | Código | Variables | Período | Ficheros |
|---|---|---|---|---|
| Vado Mojón | E32_VADOMOJON | Nivel, Aportación, Precipitación | 2015–2024 | 6 xlsx |
| Sierra Boyera | E33_SRRA_BOYERA | Nivel, Aportación, Precipitación | 2015–2024 | 6 xlsx |
| Bembézar | E37_BEMBEZAR | Nivel, Aportación, Precipitación | 2015–2024 | 6 xlsx |
| **TOTAL** | | | | **18 xlsx — 260,841 observaciones horarias** |

---

## 5. SPRINT 0 — INSPECCIÓN DEL DATO REAL (9 marzo 2026)

**Objetivo:** Inspeccionar el formato interno de los xlsx del SAIH antes de escribir una sola línea de parser. El archivo inspeccionado fue `E32_VAD_aport_2015_2020.xlsx`.

### Hallazgos críticos

| Hallazgo | Detalle |
|---|---|
| Formato xlsx | Nativo (no HTML encapsulado). Lectura por XML directo sobre el ZIP. |
| Columna A | Serial flotante Excel → `datetime(1899,12,30) + timedelta(days=valor)` |
| Columna B | Float directo: m³/s, m, mm/h según variable |
| Columna C | Siempre `None` — flag de calidad no rellenado por el SAIH |
| Footer | Bloque estadísticas al final (Mínimo, Máximo, Media...) — eliminar |
| Resolución | Exactamente 1h entre filas |
| Calidad | ~0.01% de nulos — datos excepcionalmente limpios |
| Gaps DST | 10 gaps de exactamente 2h — cambios de hora verano (último domingo de marzo) |

### Bug crítico detectado y corregido: microsegundos erróneos

Primera ejecución real reveló:
```
Fila 2: serial 42005.0833333333 → 2015-01-01 01:59:59.999997  ← mal
```

El serial flotante de Excel acumula error de precisión. Corrección implementada:

```python
def _excel_serial_to_datetime(serial: float) -> datetime:
    """
    Convierte serial Excel a datetime. Redondea al minuto más cercano
    para eliminar drift de microsegundos por precisión flotante.
    """
    raw = datetime(1899, 12, 30) + timedelta(days=float(serial))
    rounded = raw.replace(second=0, microsecond=0)
    if raw.second >= 30 or raw.microsecond >= 500000:
        rounded += timedelta(minutes=1)
    return rounded
```

Verificación ejecutada en tiempo real:
```
42005.0            → 2015-01-01 00:00:00           → 2015-01-01 00:00:00 ✓
42005.0416666667   → 2015-01-01 01:00:00.000003    → 2015-01-01 01:00:00 ✓
42005.0833333333   → 2015-01-01 01:59:59.999997    → 2015-01-01 02:00:00 ✓
```

### Bounds físicos calibrados por embalse (con datos reales)

| Embalse | H_level (m cota) | Q_inflow (m³/s) | P_rain (mm/h) |
|---|---|---|---|
| E32_VADOMOJON | 325 – 375 | 0 – 600 | 0 – 50 |
| E33_SRRA_BOYERA | 380 – 700 | 0 – 600 | 0 – 50 |
| E37_BEMBEZAR | 80 – 190 | 0 – 1,500 | 0 – 70 |

### Calibración parámetros S_l

- `eps_H = 0.02m` (p99 de |ΔH_1h| real = 0.0137m)
- `P_min = 1.0 mm/h`
- Umbral C_QH: p90 de Q no-cero (el p75 inicial generaba falsos positivos)

---

## 6. SPRINT 1 — PIPELINE DE INGESTION (9 marzo 2026)

### `src/ingestion/saih_reader.py`

```python
def read_saih_xlsx(xlsx_path, embalse_id, variable) -> pd.DataFrame:
    """Lee xlsx SAIH desde XML interno. Elimina footer. Redondea timestamps.
    Retorna: ts_station, sensor_id, field_name, value_raw, source_file"""

def read_embalse_all_variables(raw_dir, embalse_id) -> dict[str, pd.DataFrame]:
    """Lee y fusiona 2015-2020 + 2020-2024 por variable."""
```

### `src/ingestion/normalizer.py`

```python
def normalize_embalse(variable_dfs, embalse_id, ts_ingest=None) -> pd.DataFrame:
    """Pivota a tabla ancha (Data Contract v1.1). Outer join.
    Asigna UUID v4 por fila y ts_ingest UTC."""

def save_curated(df, embalse_id, curated_dir) -> Path:
    """Persiste a CURATED_ZONE como Parquet (pyarrow)."""
```

### `src/ingestion/validator.py`

```python
def validate_contract(df, embalse_id, raise_on_failure=True) -> ValidationReport:
    """Checks: columnas requeridas, UUIDs únicos, timestamps monotónicos,
    sin duplicados, gap rates, bounds físicos, sensor_id consistente."""
```

### Output de ejecución real

```
19:31:16  Saved → data\curated\E32_VADOMOJON.parquet    (4,538 KB)
19:31:19  Saved → data\curated\E33_SRRA_BOYERA.parquet  (4,399 KB)
19:31:22  Saved → data\curated\E37_BEMBEZAR.parquet     (4,477 KB)

INGESTION COMPLETE
  E32_VADOMOJON    →  86,947 rows   Validation PASSED — 0 errores
  E33_SRRA_BOYERA  →  86,947 rows   Validation PASSED — 0 errores
  E37_BEMBEZAR     →  86,947 rows   Validation PASSED — 0 errores
  TOTAL            → 260,841 rows   en 9 segundos
```

---

## 7. SPRINT 2 — PIPELINE DE SCORING (11 marzo 2026)

### `src/scoring/s_f.py` — Integridad Física

```python
PHYSICAL_BOUNDS = {
    'E32_VADOMOJON':  {'H_level': (325.0, 375.0), 'Q_inflow': (0.0, 600.0),  'P_rain': (0.0,  50.0)},
    'E33_SRRA_BOYERA':{'H_level': (380.0, 700.0), 'Q_inflow': (0.0, 600.0),  'P_rain': (0.0,  50.0)},
    'E37_BEMBEZAR':   {'H_level': (80.0,  190.0), 'Q_inflow': (0.0, 1500.0), 'P_rain': (0.0,  70.0)},
    # E37 corregido de (300,450) tras incidencia de 100% VETADA
}
def compute_s_f(df, embalse_id) -> pd.Series:
    """S_f ∈ {0,1}. 0 si viola bounds o negativo. NaN omitido."""
```

### `src/scoring/s_t.py` — Integridad Temporal

```python
def compute_s_t(df, expected_resolution_hours=1.0) -> pd.Series:
    """S_t = L(lat) * (1 - gap_rate_W1)
    L piecewise: 1.0/0.7/0.4/0.1 según lat<=60/300/900/más"""
```

### `src/scoring/s_l.py` — Coherencia Lógica

```python
def compute_s_l(df, eps_H=0.02, p_min=1.0) -> pd.Series:
    """S_l = min(C_PH, C_QH, C_z). Rolling 24h MAD z-score."""
```

### `src/scoring/s_h.py` — Salud Histórica

```python
def compute_s_h(df) -> pd.Series:
    """S_h = min(F_flat K=8, F_drift EMA 6h/24h, F_gap24 rolling)"""
```

### `src/scoring/scorer.py` — Compositor

```python
def score_embalse(df, embalse_id, detailed=False) -> pd.DataFrame:
    """S_c = clamp01(0.40*S_f + 0.30*S_l + 0.20*S_t + 0.10*S_h)
    Si detailed=True: incluye todas las sub-columnas para auditoría."""
```

### Output de ejecución real (terminal Windows)

```
20:16:28  KAIRI-SIO Scoring Pipeline

Processing: E32_VADOMOJON
  S_c mean=0.9014  std=0.1042  min=0.5900  max=1.0000
  CERTIFICADA: 53,460 (61.5%)
  DEGRADADA  : 33,482 (38.5%)
  VETADA     :      5 (0.0%)
  Saved → data\analytic\E32_VADOMOJON_scored.parquet (4641.9 KB)

Processing: E33_SRRA_BOYERA
  S_c mean=0.8871  std=0.1015  min=0.5300  max=1.0000
  CERTIFICADA: 47,122 (54.2%)
  DEGRADADA  : 39,820 (45.8%)
  VETADA     :      5 (0.0%)

Processing: E37_BEMBEZAR
  S_c mean=0.8876  std=0.1015  min=0.6100  max=1.0000
  CERTIFICADA: 47,129 (54.2%)
  DEGRADADA  : 39,813 (45.8%)
  VETADA     :      5 (0.0%)

SCORING COMPLETE
Embalse                 Rows     CERT%    DEG%    VET%  S_c mean
─────────────────────── ──────── ──────── ─────── ───── ────────
E32_VADOMOJON           86,947   61.5%    38.5%   0.0%  0.9014
E33_SRRA_BOYERA         86,947   54.2%    45.8%   0.0%  0.8871
E37_BEMBEZAR            86,947   54.2%    45.8%   0.0%  0.8876
```

---

## 8. SPRINT 3 — MOTOR DE VETO + FORENSE JSONL (11 marzo 2026)

### `src/veto/decision_engine.py`

```python
@dataclass
class VetoDecision:
    level: int; flag: str; critical: bool; reasons: list[str]

def decide_row(row) -> VetoDecision:
    """Aplica 3 condiciones CRITICAL_FLAG. Genera reasons auditables."""

def apply_veto(scored_df) -> pd.DataFrame:
    """Vectorizado. Añade: veto_level, veto_flag, critical_flag, reasons."""
```

### `src/forensics/forensic_logger.py`

```python
def write_forensic_jsonl(veto_df, output_path, mode='append',
                          filter_level=None) -> int:
    """JSONL append-only. code_hash=git|NO_GIT. data_hash=SHA-256(16chars).
    filter_level: None=todos | 1=DEG+VET | 2=solo VET"""

def write_forensic_summary_csv(veto_df, output_path) -> Path:
    """CSV legible con primary_reason por decisión."""
```

### Output de ejecución real (terminal Windows)

```
20:29:07  KAIRI-SIO Veto + Forensic Pipeline

Processing: E32_VADOMOJON
  CERTIFICADA      53,460 (61.5%)
  DEGRADADA        33,292 (38.3%)
  VETADA              195 (0.2%)  [195 critical]
  → E32_VADOMOJON_forensic_20260311T192907.jsonl
  → E32_VADOMOJON_summary_20260311T192907.csv

Processing: E33_SRRA_BOYERA
  CERTIFICADA      47,122 (54.2%)
  DEGRADADA        39,711 (45.7%)
  VETADA              114 (0.1%)  [114 critical]

Processing: E37_BEMBEZAR
  CERTIFICADA      47,129 (54.2%)
  DEGRADADA        39,659 (45.6%)
  VETADA              159 (0.2%)  [159 critical]

VETO + FORENSIC COMPLETE
  E32_VADOMOJON    86,947 eventos → JSONL + CSV
  E33_SRRA_BOYERA  86,947 eventos → JSONL + CSV
  E37_BEMBEZAR     86,947 eventos → JSONL + CSV
```

### Muestra real de evento VETADA (DST 2015, E32_VADOMOJON)

```json
{
  "uuid":          "6580fd40-9f6c-453d-acce-c233a107a8cb",
  "ts_station":    "2015-03-29T04:00:00",
  "sensor_id":     "E32_VADOMOJON",
  "scores":        {"S_c": 0.74, "S_t": 0.1, "S_h": 0.2},
  "decision":      "VETADA",
  "critical_flag": true,
  "reasons": [
    "CRITICAL_FLAG triggered",
    "Critical latency: 3600s > 900s threshold",
    "F_flat=0.2: flatline >= 8 consecutive identical values"
  ],
  "data_hash": "065d354b66b9fe2d"
}
```

> Cambio de hora DST 29 marzo 2015 (02:00→04:00). El SAIH no registra la hora omitida. Gap 2h = 3600s latencia → CRITICAL_FLAG activado correctamente.

---

## 9. ESTRUCTURA DE FICHEROS ENTREGADA

```
C:\KAIRI-SIO\src\
├── __init__.py
├── ingestion\
│   ├── __init__.py
│   ├── saih_reader.py        Sprint 1 — Lector xlsx SAIH (XML directo)
│   ├── normalizer.py         Sprint 1 — Pivota a Data Contract v1.1
│   ├── validator.py          Sprint 1 — Validación fail-fast
│   └── run_ingestion.py      Sprint 1 — Entry point
├── scoring\
│   ├── __init__.py
│   ├── s_f.py                Sprint 2 — S_f Integridad Física
│   ├── s_l.py                Sprint 2 — S_l Coherencia Lógica
│   ├── s_t.py                Sprint 2 — S_t Integridad Temporal
│   ├── s_h.py                Sprint 2 — S_h Salud Histórica
│   ├── scorer.py             Sprint 2 — Compositor S_c
│   └── run_scoring.py        Sprint 2 — Entry point
├── veto\
│   ├── __init__.py
│   ├── decision_engine.py    Sprint 3 — Motor de veto
│   └── run_veto.py           Sprint 3 — Entry point
└── forensics\
    ├── __init__.py
    └── forensic_logger.py    Sprint 3 — Logger JSONL + CSV
```

---

## 10. INCIDENCIAS Y RESOLUCIONES

| # | Incidencia | Causa Raíz | Resolución | Sprint |
|---|---|---|---|---|
| 1 | `openpyxl` no lee xlsx | Atributo `defaultColWidthPt` no soportado | Parser XML nativo sobre ZIP | 0 |
| 2 | Timestamps `01:59:59.999997` | Error flotante serial Excel | Redondeo al minuto más cercano | 1 |
| 3 | E37 100% VETADA (S_c=0.49) | Bounds H_level `(300,450)` para embalse en cota real `90–178m` | Calibración con datos reales del Parquet | 2 |
| 4 | `ModuleNotFoundError: src.scoring` | Ausencia de `__init__.py` en carpetas | Creación de `__init__.py` vacíos | 2–3 |
| 5 | `pandas fillna(method=)` deprecado | API pandas ≥ 2.0 | Reemplazo por `.ffill()` / `.bfill()` | 2 |
| 6 | C_QH falsos positivos | Umbral p75 demasiado bajo para caudales en régimen bajo | Cambio a p90 de Q no-cero | 2 |

---

## 11. MÉTRICAS FINALES

| Métrica | Valor |
|---|---|
| Ficheros fuente | 18 xlsx (SAIH Guadalquivir) |
| Filas totales procesadas | 260,841 |
| Período cubierto | 2015–2024 (9 años) |
| Resolución temporal | Horaria (1h) |
| Embalses | 3 (E32, E33, E37) |
| Errores de pipeline | 0 |
| Módulos Python | 12 |
| Líneas de código | ~1,800 |
| Tiempo ejecución (3 embalses) | ~90 segundos |

### Resultados scoring + veto (ejecución final)

| Embalse | CERTIFICADA | DEGRADADA | VETADA (críticos) | S_c medio |
|---|---|---|---|---|
| E32_VADOMOJON | 61.5% (53,460) | 38.3% (33,292) | 0.2% (195) | 0.9014 |
| E33_SRRA_BOYERA | 54.2% (47,122) | 45.7% (39,711) | 0.1% (114) | 0.8871 |
| E37_BEMBEZAR | 54.2% (47,129) | 45.6% (39,659) | 0.2% (159) | 0.8876 |

> Todos los VETADA son CRITICAL_FLAG por gaps DST anuales (lat=3600s > 900s). Detectados y clasificados correctamente.

---

## 12. ESTADO DE SPRINTS

| Sprint | Descripción | Estado |
|---|---|---|
| Sprint 0 | Inspección dato real — formato xlsx SAIH, calibración bounds | ✅ Completado |
| Sprint 1 | Pipeline ingestion — reader, normalizer, validator, run | ✅ Completado |
| Sprint 2 | Pipeline scoring — S_f, S_l, S_t, S_h, compositor S_c | ✅ Completado |
| Sprint 3 | Motor de veto + registro forense JSONL append-only | ✅ Completado |
| Sprint 4 | Demo visual — notebook Jupyter | ⏳ Pendiente |

### Pendientes técnicos
- `git init` en `C:\KAIRI-SIO\` → activa `code_hash` real en JSONL
- Refinar bounds E33_SRRA_BOYERA H_level máximo real

---

## 13. PRINCIPIOS DE IMPLEMENTACIÓN

| Principio | Descripción |
|---|---|
| **Determinismo** | Mismo input = mismo output siempre. Sin aleatoriedad ni estado oculto. |
| **None ≠ 0.0** | Dato faltante es NaN/None, nunca imputado a cero. |
| **Inmutabilidad raw** | `data/raw/` nunca se modifica. LANDING_ZONE solo lectura. |
| **Auditabilidad** | UUID v4 + SHA-256 por cada decisión forense. Reproducible. |
| **Fail-fast** | Error explícito con logging. Sin fallos silenciosos. |
| **Append-only** | JSONL forense nunca se modifica, solo se añade. |
| **Calibración empírica** | Umbrales de percentiles reales, no supuestos teóricos. |

---

## 14. DEPENDENCIAS TÉCNICAS

```
pandas>=2.0  openpyxl>=3.1  numpy>=1.24  scipy>=1.11
pyarrow>=13.0  python-dotenv>=1.0
matplotlib>=3.7  seaborn>=0.12  pytest>=7.4   (Sprint 4+)
```

Entorno: Python 3.12 — `.venv` — `C:\KAIRI-SIO\`

---

*Documento generado el 11 de marzo de 2026.*
*KAIRI-SIO | Ingeniería: Kent Valera Chirinos | Concepto: Reymar*
