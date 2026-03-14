# KAIRI-SIO — Technical System Documentation
**Version:** 1.1.0  
**Date:** 2026-03-13  
**Authors:** Reymar (mathematical specification) · Kent Valera Chirinos (technical implementation)  
**Status:** Pilot production — CHG Guadalquivir + CHE Ebro

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Theoretical Foundations](#2-theoretical-foundations)
3. [System Architecture](#3-system-architecture)
4. [Composite Scoring Model S_c](#4-composite-scoring-model-sc)
5. [Processing Pipeline](#5-processing-pipeline)
6. [Multi-Confederation Configuration](#6-multi-confederation-configuration)
7. [REST API](#7-rest-api)
8. [Monitoring Dashboard](#8-monitoring-dashboard)
9. [AEMET Connector](#9-aemet-connector)
10. [Cross-Basin Validation](#10-cross-basin-validation)
11. [Command Reference](#11-command-reference)
12. [Project Structure](#12-project-structure)

---

## 1. System Overview

KAIRI-SIO (Hydrological Signal Integrity Verification System) is a deterministic real-time data quality control system for SAIH (Automatic Hydrological Information System) networks of Spanish River Basin Authorities. The system evaluates the integrity of hydrometeorological sensor signals — reservoir level, precipitation, flow — by applying a composite scoring model grounded in international metrology standards and statistical process control.

KAIRI-SIO does not model hydrological behaviour nor generate flow predictions. Its exclusive domain is the **verification of measurement signal reliability**: determining whether an observation received from a sensor can be considered intact or whether it presents evidence of instrumental degradation.

### 1.1 Problem Statement

SAIH networks transmit remote sensor data at 15-minute intervals from hundreds of control points distributed across river basins covering tens of thousands of km². The most frequent instrumental failures — frozen sensor (*flatline*), excessive transmission latency, signal drift, electromagnetic noise spikes, loss of temporal continuity — are not automatically detectable by existing SCADA systems without specific validation logic.

The operational consequence is that defective observations enter information systems as valid data, contaminating water balance calculations, flood forecasting models, and historical records used in hydrological planning.

KAIRI-SIO assigns each observation an integrity score $S_c \in [0, 1]$ and a regime classification (`CERTIFIED`, `DEGRADED`, `VETOED`) that enables operators and downstream systems to make informed decisions about the reliability of each data point.

### 1.2 Validated Operational Scope

| Confederation | Reservoirs | Period | Observations |
|---|---|---|---|
| CHG · Guadalquivir | E32 Vado Mojón, E33 Sierra Boyera, E37 Bembézar | 2015–2024 | 260,841 |
| CHE · Ebro | Itoiz, Mequinenza, Yesa | 2025–2026 | 105,017 |
| **Total** | **6 reservoirs** | | **365,858** |

---

## 2. Theoretical Foundations

### 2.1 Weight Model — Analytic Hierarchy Process (AHP)

The composite score weights are derived using the AHP method (Saaty, 1980), which mathematically formalises expert comparative judgements into a verifiably consistent weight vector. The pairwise comparison matrix reflects a hydraulic integrity hierarchy: physical sensor constraints take precedence over derived statistical metrics.

$$S_c = 0.40 \cdot S_f + 0.30 \cdot S_l + 0.20 \cdot S_t + 0.10 \cdot S_h$$

The matrix consistency ratio is $CR < 0.10$, confirming the coherence of comparative judgements per Saaty's (1980) criterion. References: *The Analytic Hierarchy Process* (Saaty, 1980); Montgomery, *Introduction to Statistical Quality Control*, 7th ed. (2012).

### 2.2 Classification Thresholds — GUM

The regime thresholds are derived from the algebraic properties of the model and from the Guide to the Expression of Uncertainty in Measurement (GUM, JCGM 100:2008).

**VETOED threshold ($S_c < 0.50$) — uncertainty dominance principle:**

In a composite score with weights summing to 1.0 and sub-scores in $[0,1]$, the value 0.50 corresponds to the equilibrium point between reliable and deficient components. When $S_c < 0.50$, the accumulated weight of deficient dimensions exceeds that of reliable ones. The GUM establishes that a measurement is unusable when its expanded uncertainty exceeds the measured value.

**CERTIFIED threshold ($S_c \geq 0.85$):**

This is the minimum value of $S_c$ such that even if the highest-weight sub-score ($S_f$, $W=0.40$) degrades to 0.625 while all others remain perfect, $S_c$ remains acceptable:

$$0.40 \cdot x + 0.30 \cdot 1.0 + 0.20 \cdot 1.0 + 0.10 \cdot 1.0 = 0.85 \implies x = 0.625$$

### 2.3 Flatline Detection — Statistical Process Control

The parameter `FLATLINE_K = 8h` is justified by Nelson's Rule 2 (1984): eight or more consecutive identical points constitute an unambiguous signal of an out-of-control process. This rule is incorporated in ISO 7870-2:2013. In a normally operating reservoir, a sequence of 8 exactly identical hourly observations is statistically improbable given the inherent instrumental noise.

The critical threshold `FLAT_CRITICAL_H = 48h` is justified by three complementary arguments:
- **Natural hydrological cycles (WMO-No.168):** 48h equals 2 complete nycthemeral cycles
- **Irreversible information loss:** significant variation events ($\Delta H > 0.05$ m/h) have a mean duration of 6–18h in the SAIH Guadalquivir dataset
- **WMO completeness:** 48h in a 10-day analysis window represents 20% invalid data, exceeding the 10% acceptance threshold established by WMO-No.168

### 2.4 Drift Detection — EWMA/CUSUM Detectors

The drift detector $F_{drift}$ is formally equivalent to a CUSUM (Page, 1954) or EWMA (Lucas & Saccucci, 1990) mean-change detector. It computes the normalised drift:

$$\text{drift} = \frac{|EMA_{6h} - EMA_{24h}|}{\sigma_{24h}}$$

The threshold `DRIFT_THRESH = 3.0` is justified as a UCL (Upper Control Limit) by the reference-percentile of the empirical distribution of the SAIH Guadalquivir dataset (n=86,947):

- Highly leptokurtic distribution: excess kurtosis = 618.2, skewness = 20.8
- Non-Gaussian: Shapiro-Wilk, D'Agostino-Pearson, Kolmogorov-Smirnov, and Anderson-Darling reject normality with $p < 10^{-62}$
- Value 3.0 coincides with the natural inflection point of the right tail of the empirical distribution

### 2.5 Gap Thresholds — WMO

Data completeness thresholds are derived directly from WMO-No.168 and WMO-No.8:

| Parameter | Value | WMO Criterion |
|---|---|---|
| `GAP_WARN` | 0.10 | Completeness ≥ 90% for daily flow calculation |
| `GAP_FAIL` | 0.30 | Completeness ≥ 70% for event analysis |

### 2.6 Critical Latency — SAIH Protocol

`LAT_CRITICAL_S = 900s` corresponds to the nominal SAIH transmission interval (15 minutes). An observation with latency exceeding 900s has arrived at the system outside its temporal validity window, equivalent to a displacement of more than one sampling period. This parameter is configurable per confederation to guarantee portability.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KAIRI-SIO v1.1                               │
│                                                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │  INGESTION   │───▶│   SCORING    │───▶│   VETO / DECISION    │   │
│  │              │    │              │    │                      │   │
│  │ saih_reader  │    │ s_f.py       │    │ decision_engine.py   │   │
│  │ ebro_reader  │    │ s_l.py       │    │ CRITICAL_FLAG        │   │
│  │ aemet_conn.  │    │ s_t.py       │    │ CERT/DEGR/VETOED     │   │
│  └──────────────┘    │ s_h.py       │    └──────────────────────┘   │
│         │            │ scorer.py    │              │                 │
│         ▼            └──────────────┘              ▼                 │
│  ┌──────────────┐              │            ┌──────────────┐         │
│  │  data/raw/   │              │            │   FORENSIC   │         │
│  │  data/curated│              │            │ forensic_log │         │
│  │  data/analytic│             │            │ .jsonl audit │         │
│  └──────────────┘              │            └──────────────┘         │
│                                ▼                                      │
│                    ┌──────────────────────┐                          │
│                    │    VALIDATION        │                          │
│                    │ ground_truth_builder │                          │
│                    │ cross_basin          │                          │
│                    └──────────────────────┘                          │
│                                │                                      │
│              ┌─────────────────┼──────────────────┐                 │
│              ▼                 ▼                  ▼                  │
│     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│     │  REST API    │  │  DASHBOARD   │  │   CONFIG     │           │
│     │  FastAPI     │  │  Streamlit   │  │  YAML/basins │           │
│     │  /score/*    │  │  dashboard   │  │  CHG/CHE/... │           │
│     └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Data Zones

| Zone | Path | Contents | Policy |
|---|---|---|---|
| **Raw** | `data/raw/` | Original SAIH CSVs, raw parquets | Immutable |
| **Curated** | `data/curated/` | Parquets normalised to Data Contract v1.1 | Regenerable |
| **Analytic** | `data/analytic/` | Scored parquets with S_c, quality_flag | Regenerable |
| **Official Sources** | `03_Datos_Fuentes_Oficiales/` | SNCZI, DTM, Caumax — official MITECO data | Untouchable |

---

## 4. Composite Scoring Model S_c

### 4.1 Physical Integrity Sub-score S_f

$S_f$ evaluates whether observed values are physically plausible for the reservoir.

$$S_f = \text{clamp}_{[0,1]}\left(1 - F_{bounds} - F_{spike} - F_{flat}\right)$$

| Component | Activation Condition | Penalty |
|---|---|---|
| $F_{bounds}$ | $H < H_{min}$ or $H > H_{max}$ | 1.0 (physical veto) |
| $F_{spike}$ | $|\Delta H / \Delta t| > \text{SPIKE\_THRESH}$ | 0.5 |
| $F_{flat}$ | $K \geq 8$ consecutive identical observations | 0.2 |

When $S_f = 0.0$, `CRITICAL_FLAG` is automatically activated regardless of other sub-scores.

### 4.2 Logical Integrity Sub-score S_l

$S_l$ evaluates the internal consistency of the time series through gap detection and continuity analysis in 24-hour rolling windows.

$$S_l = \text{clamp}_{[0,1]}\left(1 - F_{gap24} - F_{gap\_consec}\right)$$

| Component | Condition | Penalty |
|---|---|---|
| $F_{gap24}$ (warn) | Gap in 24h window $\geq$ 10% | 0.2 |
| $F_{gap24}$ (fail) | Gap in 24h window $\geq$ 30% | 0.5 |
| $F_{gap\_consec}$ | Consecutive gaps detected | Variable |

### 4.3 Temporal Integrity Sub-score S_t

$S_t$ evaluates the punctuality of transmission relative to the nominal SAIH interval.

$$S_t = f(\text{observed latency}, \text{latency breakpoints})$$

The function is piecewise linear defined by breakpoints $[60s, 300s, 900s]$ with scores $[1.0, 0.7, 0.4, 0.1]$. When $S_t < 0.1$, `CRITICAL_FLAG` is activated.

### 4.4 Historical Integrity Sub-score S_h

$S_h$ evaluates the consistency of the observed value against the historical behaviour of the sensor across multiple temporal windows.

$$S_h = \text{clamp}_{[0,1]}\left(1 - F_{drift} - F_{hist}\right)$$

$F_{drift}$ applies the EWMA/CUSUM detector to the normalised drift $|EMA_{6h} - EMA_{24h}| / \sigma_{24h}$, activating when it exceeds `DRIFT_THRESH = 3.0`.

### 4.5 CRITICAL_FLAG and Veto Regime

`CRITICAL_FLAG` is activated when any of the following conditions is met, independently of $S_c$:

| Condition | Cause |
|---|---|
| $S_f = 0.0$ | Physically impossible value |
| $S_t < 0.10$ | Severe temporal failure |
| Flatline $\geq 48h$ active | WMO-No.168 |
| $S_f = 0$ AND $C_{PH}$ active | Double physical failure evidence |

When `CRITICAL_FLAG = True`, the regime is forced to `VETOED` regardless of $S_c$.

### 4.6 Regime Classification

| Regime | Condition | Interpretation |
|---|---|---|
| `CERTIFIED` | $S_c \geq 0.85$ AND NOT `CRITICAL_FLAG` | Intact observation for operational use |
| `DEGRADED` | $0.50 \leq S_c < 0.85$ AND NOT `CRITICAL_FLAG` | Usable observation with caution |
| `VETOED` | $S_c < 0.50$ OR `CRITICAL_FLAG` | Unusable observation; log and discard |

---

## 5. Processing Pipeline

The complete KAIRI-SIO pipeline follows the sequence: **Ingestion → Scoring → Veto → Validation**.

### 5.1 Ingestion — CHG Guadalquivir

Reads SAIH Guadalquivir XLSX files, normalises to Data Contract v1.1 and generates curated parquets.

```powershell
# Ingest all CHG reservoirs
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py

# Ingest a specific reservoir
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py --embalse E32_VADOMOJON
```

**Data Contract v1.1** — required columns in `data/curated/`:

| Column | Type | Description |
|---|---|---|
| `uuid` | str | Unique observation identifier |
| `sensor_id` | str | Sensor identifier |
| `ts_station` | datetime | Station timestamp |
| `ts_ingest` | datetime | KAIRI ingestion timestamp |
| `H_level` | float | Reservoir level (m) |
| `Q_inflow` | float | Inflow (m³/s) |
| `P_rain` | float | Precipitation (mm) |

### 5.2 Ingestion — CHE Ebro

Reads SAIH Ebro CSV files (format `sep=;`, column `VALOR (msnm)`), normalises and generates parquets in `data/curated/ebro/`.

```powershell
# Ingest all Ebro reservoirs
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all

# Ingest a specific reservoir
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse ITOIZ
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse MEQUINENZA
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse YESA
```

### 5.3 Scoring — CHG

Computes $S_c$ for Guadalquivir reservoirs and saves scored parquets to `data/analytic/`.

```powershell
# Full CHG scoring (standard mode)
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py

# Scoring with detailed sub-scores (includes S_f, S_l, S_t, S_h and components)
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed

# Score a specific reservoir
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --embalse E32_VADOMOJON

# Scoring with custom paths
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --curated data/curated --analytic data/analytic
```

### 5.4 Scoring — CHE

```powershell
# Full CHE scoring with detailed sub-scores
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed

# Score a specific Ebro reservoir
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --embalse ITOIZ
```

### 5.5 Veto

Applies veto rules and generates the decision log with `CRITICAL_FLAG`.

```powershell
# Apply veto to CHG scored data
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py

# Apply veto to CHE
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE
```

### 5.6 Validation — Sprint 5 (CHG)

Builds ground truth from known errors and computes recall/precision.

```powershell
# Build ground truth
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py

# Run full validation
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py
```

Output in `output/validation/`:
- `validation_report.txt` — recall/precision summary by error type
- `validation_detail.parquet` — observation-level detail
- `ground_truth.parquet` — reference dataset

### 5.7 Cross-Basin Experiment

Validates model generalisation to the Ebro basin.

```powershell
# Run full experiment (requires scored parquets for both CHG and CHE)
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py
```

Output in `output/validation/`:
- `intercuencas_report.csv` — S_c distribution by reservoir and basin
- `intercuencas_summary.txt` — summary with KS test
- `intercuencas_sc_distribution.png` — comparative chart

---

## 6. Multi-Confederation Configuration

Confederation configuration is managed via YAML files in `src/config/confederations/`. Each file defines weights, thresholds, latency/flatline/drift parameters, and physical bounds per reservoir.

### 6.1 Confederation YAML Structure

```yaml
# src/config/confederations/CHG.yaml
confederation:
  code: CHG
  name: Confederación Hidrográfica del Guadalquivir
  status: production  # production | pilot | placeholder

weights:
  w_f: 0.40  # AHP Saaty 1980, CR < 0.10
  w_l: 0.30
  w_t: 0.20
  w_h: 0.10

thresholds:
  certificada: 0.85  # GUM JCGM 100:2008
  degradada:   0.50

latency:
  breakpoints_s: [60, 300, 900]
  scores:        [1.0, 0.7, 0.4, 0.1]
  critical_s:    900

gaps:
  warn: 0.10  # WMO-No.168: 90% completeness
  fail: 0.30  # WMO-No.168: 70% completeness

flatline:
  k_hours:        8   # Nelson 1984, ISO 7870-2:2013
  critical_hours: 48  # WMO-No.168

drift:
  threshold: 3.0  # Empirical percentile UCL, Page 1954

spike:
  h_level_m_per_h: 1.0

embalses:
  E32_VADOMOJON:
    H_min: 0.0
    H_max: 600.0
    Q_min: 0.0
    Q_max: 5000.0
    P_min: 0.0
    P_max: 300.0
```

### 6.2 Available Confederations

```powershell
# List available confederations
(.venv) PS C:\KAIRI-SIO> python -c "
from src.config.confederation_config import list_available_confederations
for c in list_available_confederations():
    print(c)
"
```

| Code | Confederation | Status |
|---|---|---|
| `CHG` | Guadalquivir River Basin Authority | `production` |
| `CHE` | Ebro River Basin Authority | `pilot` |
| `CHD` | Duero River Basin Authority | `placeholder` |
| `CHT` | Tajo River Basin Authority | `placeholder` |

---

## 7. REST API

The REST API enables integration with external systems and real-time scoring of individual observations or time series.

### 7.1 Server Startup

```powershell
# Development server (auto-reload)
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000

# Production server
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Interactive Swagger UI documentation
# → http://localhost:8000/docs
```

### 7.2 Available Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service status + available confederations |
| `GET` | `/confederations` | List all confederations |
| `GET` | `/confederations/{code}` | Details of a confederation |
| `POST` | `/score/observation` | Score a single observation |
| `POST` | `/score/batch` | Score a time series (max 10,000 obs) |

### 7.3 Usage Example

```bash
# Health check
curl http://localhost:8000/health

# Score a single observation
curl -X POST http://localhost:8000/score/observation \
  -H "Content-Type: application/json" \
  -d '{
    "embalse_id": "E32_VADOMOJON",
    "confederation": "CHG",
    "ts_station": "2026-03-13T10:00:00",
    "H_level": 285.5,
    "Q_inflow": 12.3,
    "P_rain": 0.0,
    "latency_s": 45
  }'
```

**Response:**
```json
{
  "S_f": 1.0,
  "S_l": 0.95,
  "S_t": 1.0,
  "S_h": 0.87,
  "S_c": 0.965,
  "quality_flag": "CERTIFICADA",
  "critical_flag": false,
  "confederation": "CHG"
}
```

---

## 8. Monitoring Dashboard

The dashboard provides interactive visualisation of the integrity status of monitored reservoirs.

### 8.1 Startup

```powershell
# Start dashboard (local mode)
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py

# Start on specific port
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py --server.port 8501
```

The dashboard will open automatically at `http://localhost:8501`.

### 8.2 Available Views

| View | Description |
|---|---|
| **KPIs** | Total observations, % CERT/VETOED, # CRITICAL_FLAG, mean S_c |
| **Regime distribution** | Stacked bars CERT/DEGR/VETOED per reservoir + mean S_c |
| **S_c time series** | Resampleable S_c (daily/weekly/monthly/quarterly) with thresholds |
| **Sub-score heatmap** | Mean S_f · S_l · S_t · S_h · S_c, RdYlGn scale |
| **CRITICAL_FLAG** | Filterable table of critical events with per-reservoir metrics |
| **Sprint 5 Recall** | Validation against CHG ground truth (CHG only) |
| **Cross-basin** | KDE comparison CHG vs CHE (only in "Both" mode) |
| **AEMET** | Real-time observations (sidebar toggle, TTL 5 min) |

### 8.3 Confederation Selector

The sidebar allows selecting `CHG · Guadalquivir`, `CHE · Ebro`, or `Both`. The date range adjusts automatically to the selection. In `Both` mode, the cross-basin comparison view is activated.

---

## 9. AEMET Connector

The AEMET OpenData connector integrates real-time meteorological observations from the nearest stations to each reservoir.

### 9.1 Configuration

Add the API key to `.env` (free registration at `opendata.aemet.es`):

```
AEMET_API_KEY=your_jwt_api_key
```

### 9.2 Usage

```powershell
# Get observations for all reservoirs
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs

# Get observation for a specific reservoir
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs --embalse ITOIZ

# Get active CAP alerts (meteorological warnings)
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode avisos

# Full mode (observations + alerts)
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all

# Inventory of available AEMET stations
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode inventario
```

### 9.3 Retrieved Variables

| Variable | Unit | Use in KAIRI-SIO |
|---|---|---|
| Precipitation | mm/15min | S_h enrichment, rain↔level correlation |
| Temperature | °C | Context for evaporation analysis |
| Wind | m/s | Context for pressure anomalies |
| CAP Alerts | red/orange level | Preventive pre-flag for extreme events |

**Technical note:** The AEMET OpenData API requires a two-step HTTP call (the first returns a URL, the second retrieves the actual data). The rate limit is 50 requests/minute. The connector handles both aspects automatically with a configurable delay (`RATE_LIMIT_DELAY = 2.0s`).

---

## 10. Cross-Basin Validation

### 10.1 Experiment Results (2026-03-13)

The experiment validates the model's generalisation hypothesis: parameters derived from universal physical foundations operate correctly in an unseen basin without recalibration.

**Dataset:** CHG (2015–2024, 260,841 obs) + CHE (2025–2026, 105,017 obs) = 365,858 total observations.

**Test 1 Results — S_c Distribution:**

| Basin | Reservoir | Mean S_c | CERT% | DEGR% | VETO% |
|---|---|---|---|---|---|
| CHG | E32 Vado Mojón | 0.9014 | 61.5% | 38.5% | 0.01% |
| CHG | E33 Sierra Boyera | 0.8871 | 54.2% | 45.8% | 0.01% |
| CHG | E37 Bembézar | 0.8876 | 54.2% | 45.8% | 0.01% |
| CHE | Itoiz | 0.8007 | 71.9% | 28.1% | 0.00% |
| CHE | Mequinenza | 0.8124 | 75.2% | 24.8% | 0.00% |
| CHE | **Yesa** | **0.9102** | 69.3% | 30.7% | 0.00% |

Yesa (CHE) achieves the highest mean S_c of all analysed reservoirs, demonstrating that the model is not biased towards the calibration basin.

**Test 2 Results — Flatline Detection:** $S_f = 1.000$ across all reservoirs in both basins. No flatlines detected — the expected result for curated datasets without known sensor anomalies in the analysed periods.

**Test 3 Results — Kolmogorov-Smirnov:** $KS = 0.333$, $p \approx 0$. With $n = 365,858$ the KS test has extreme statistical power. The operational difference $\Delta\mu = 0.051$ between basins is explained by the difference in historical series length (9 years CHG vs 1 year CHE), which affects the $S_h$ component.

**Conclusion:** Hypothesis confirmed. KAIRI-SIO operates correctly in CHE without recalibration, with only the physical bounds $H_{level}$ specific to each dam requiring adaptation.

---

## 11. Command Reference

### 11.1 Full Execution Sequence

```powershell
# ── 1. INGESTION CHG ─────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py

# ── 2. INGESTION CHE ─────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all

# ── 3. SCORING CHG ───────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed

# ── 4. SCORING CHE ───────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed

# ── 5. VETO ──────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE

# ── 6. VALIDATION ────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py

# ── 7. CROSS-BASIN EXPERIMENT ────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py

# ── 8. REST API ───────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000

# ── 9. DASHBOARD ─────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py

# ── 10. AEMET ────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all
```

### 11.2 Quick Reference by Module

```powershell
# ── INGESTION ─────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py --embalse E32_VADOMOJON
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse YESA
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode avisos
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode inventario
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs --embalse ITOIZ

# ── SCORING ───────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --embalse E32_VADOMOJON
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --embalse ITOIZ
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --curated data/curated --analytic data/analytic

# ── VETO ─────────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE

# ── VALIDATION ────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py

# ── API ───────────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# ── DASHBOARD ─────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py --server.port 8501

# ── UTILITIES ─────────────────────────────────────────────────────────────────
# Project tree
(.venv) PS C:\KAIRI-SIO> python kairi_tree.py

# Verify confederation configuration
(.venv) PS C:\KAIRI-SIO> python -c "
from src.config.confederation_config import load_confederation_config
cfg = load_confederation_config('CHG')
print(cfg)
"
```

### 11.3 Dependency Installation

```powershell
# Main pipeline dependencies
(.venv) PS C:\KAIRI-SIO> pip install -r requirements.txt

# Additional dependencies for API + Dashboard
(.venv) PS C:\KAIRI-SIO> pip install -r requirements_api.txt

# Additional dependency for cross-basin experiment
(.venv) PS C:\KAIRI-SIO> pip install scipy

# AEMET dependencies
(.venv) PS C:\KAIRI-SIO> pip install python-dotenv requests
```

---

## 12. Project Structure

```
C:\KAIRI-SIO\
│
├── .env                          ← Environment variables (AEMET_API_KEY)
├── dashboard.py                  ← Streamlit Dashboard v2.0
├── kairi_tree.py                 ← Project tree utility
├── requirements.txt              ← Pipeline dependencies
├── requirements_api.txt          ← API + Dashboard dependencies
│
├── 03_Datos_Fuentes_Oficiales\   ← UNTOUCHABLE — official MITECO sources
│   ├── Caumax_Nacional\          ← QGIS plugin for CEDEX maximum flows
│   ├── MDT\                      ← Digital Terrain Models
│   └── SNCZI_Cartografia\        ← Flood zones T10/T100/T500
│       ├── Ebro\                 ← SAIH Ebro data (Itoiz, Mequinenza, Yesa)
│       └── guadalquivir\         ← SAIH Guadalquivir data (E32, E33, E37)
│
├── data\
│   ├── raw\                      ← Raw data (untransformed parquets)
│   │   ├── saih_ebro\            ← Raw Ebro generated by saih_ebro_reader
│   │   ├── saih_guadalquivir\    ← Original CHG XLSX
│   │   ├── aemet\                ← AEMET observations
│   │   └── cartografia_snczi\   ← SNCZI shapefiles T10/T100/T500
│   ├── curated\                  ← Data Contract v1.1 (normalised parquets)
│   │   └── ebro\                 ← Curated CHE
│   └── analytic\                 ← Scored parquets with S_c, quality_flag
│       └── ebro\                 ← Analytic CHE
│
├── src\
│   ├── api\                      ← FastAPI REST API
│   │   ├── main.py
│   │   └── schemas.py
│   ├── config\                   ← Multi-confederation configuration
│   │   ├── confederation_config.py
│   │   ├── sensor_config.py
│   │   └── confederations\
│   │       ├── CHG.yaml          ← Production
│   │       ├── CHE.yaml          ← Pilot
│   │       ├── CHD.yaml          ← Placeholder
│   │       └── CHT.yaml          ← Placeholder
│   ├── forensics\                ← JSONL forensic log
│   │   └── forensic_logger.py
│   ├── ingestion\                ← Readers and ingestion
│   │   ├── saih_reader.py        ← CHG (XLSX)
│   │   ├── saih_ebro_reader.py   ← CHE (CSV sep=;)
│   │   ├── aemet_connector.py    ← AEMET OpenData REST
│   │   ├── normalizer.py
│   │   ├── validator.py
│   │   └── run_ingestion.py
│   ├── scoring\                  ← Scoring model
│   │   ├── s_f.py                ← Physical sub-score
│   │   ├── s_l.py                ← Logical sub-score
│   │   ├── s_t.py                ← Temporal sub-score
│   │   ├── s_h.py                ← Historical sub-score
│   │   ├── scorer.py             ← S_c orchestrator
│   │   └── run_scoring.py        ← Multi-confederation CLI
│   ├── validation\               ← Validation and metrics
│   │   ├── ground_truth_builder.py
│   │   └── run_validation.py
│   └── veto\                     ← Decision engine
│       ├── decision_engine.py
│       └── run_veto.py
│
├── notebooks\
│   ├── mvp_demo\
│   │   └── kairi_sio_demo.py
│   └── validacion\
│       └── kairi_sio_intercuencas.py  ← Cross-basin experiment
│
├── output\
│   ├── demo\                     ← MVP demo charts
│   ├── forensics\                ← Forensic JSONL logs
│   ├── reports\                  ← Generated reports
│   └── validation\               ← Validation results
│
└── docs\
    ├── arquitectura\             ← Technical documentation
    ├── modelo_matematico\        ← Mathematical foundation PDFs
    └── regulatorio\              ← Referenced WMO, GUM, ISO standards
```

---

## References

| Reference | Use in KAIRI-SIO |
|---|---|
| Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill. | AHP weights for composite score S_c |
| JCGM 100:2008. *Guide to the Expression of Uncertainty in Measurement* (GUM). | VETOED/CERTIFIED classification thresholds |
| Nelson, L.S. (1984). The Shewhart Control Chart — Tests for Special Causes. *Journal of Quality Technology*, 16(4), 237–239. | FLATLINE_K = 8h |
| ISO 7870-2:2013. *Control Charts — Part 2: Shewhart Control Charts*. | FLATLINE_K = 8h |
| WMO-No.168. *Guide to Hydrological Practices*, Vol. I, Ch. 2. | FLAT_CRITICAL_H = 48h, GAP_WARN/FAIL |
| WMO-No.8. *Guide to Meteorological Instruments and Methods of Observation*, Ch. 1. | GAP_WARN/FAIL |
| Page, E.S. (1954). Continuous Inspection Schemes. *Biometrika*, 41(1/2), 100–115. | DRIFT_THRESH (CUSUM detector) |
| Lucas, J.M. & Saccucci, M.S. (1990). Exponentially Weighted Moving Average Control Schemes. *Technometrics*, 32(1), 1–12. | DRIFT_THRESH (EWMA detector) |
| Montgomery, D.C. (2012). *Introduction to Statistical Quality Control*, 7th ed. Wiley. | General SPC framework |

---

*KAIRI-SIO v1.1.0 · Reymar (mathematical specification) · Kent Valera Chirinos (technical implementation) · 2026-03-13*
