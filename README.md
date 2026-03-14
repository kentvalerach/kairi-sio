# KAIRI-SIO 💧

**Hydrological Signal Integrity Verification System**  
Sistema de Verificación de Integridad de Señal Hidrológica

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.41-red)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

KAIRI-SIO is a deterministic real-time data quality control system for SAIH (Automatic Hydrological Information System) networks of Spanish River Basin Authorities. It evaluates the integrity of hydrometeorological sensor signals — reservoir level, precipitation, flow — using a composite scoring model grounded in international metrology standards and statistical process control.

**Validated on 365,858 observations across 6 reservoirs in 2 river basins (Guadalquivir + Ebro) without recalibration.**

---

## How it works

Each sensor observation receives a composite integrity score $S_c \in [0, 1]$:

$$S_c = 0.40 \cdot S_f + 0.30 \cdot S_l + 0.20 \cdot S_t + 0.10 \cdot S_h$$

| Sub-score | Dimension | Method |
|---|---|---|
| $S_f$ | Physical integrity | Bounds check + spike detection + flatline (Nelson 1984) |
| $S_l$ | Logical integrity | Gap analysis in 24h rolling windows (WMO-No.168) |
| $S_t$ | Temporal integrity | Transmission latency vs. SAIH protocol (900s nominal) |
| $S_h$ | Historical integrity | EWMA/CUSUM drift detection (Page 1954, Lucas & Saccucci 1990) |

Observations are classified as `CERTIFICADA` (≥0.85), `DEGRADADA` (≥0.50), or `VETADA` (<0.50 or `CRITICAL_FLAG`).

Weights derived via AHP (Saaty, 1980, CR<0.10). Thresholds grounded in GUM (JCGM 100:2008).

---

## Quickstart

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/kairi-sio.git
cd kairi-sio

# Install
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements_api.txt

# Configure (optional — for AEMET real-time connector)
cp .env.template .env
# Edit .env and add your AEMET_API_KEY (free at opendata.aemet.es)

# Run scoring (Guadalquivir)
python src/scoring/run_scoring.py --detailed

# Run scoring (Ebro)
python src/scoring/run_scoring.py --confederation CHE --detailed

# Launch dashboard
streamlit run dashboard.py

# Launch API
uvicorn src.api.main:app --reload --port 8000
# → Swagger UI: http://localhost:8000/docs
```

---

## Results

### Cross-basin validation (CHG Guadalquivir + CHE Ebro)

| Basin | Reservoir | Mean S_c | CERT% | DEGR% | VETO% |
|---|---|---|---|---|---|
| CHG | E32 Vado Mojón | 0.9014 | 61.5% | 38.5% | 0.01% |
| CHG | E33 Sierra Boyera | 0.8871 | 54.2% | 45.8% | 0.01% |
| CHG | E37 Bembézar | 0.8876 | 54.2% | 45.8% | 0.01% |
| CHE | Itoiz | 0.8007 | 71.9% | 28.1% | 0.00% |
| CHE | Mequinenza | 0.8124 | 75.2% | 24.8% | 0.00% |
| CHE | **Yesa** | **0.9102** | 69.3% | 30.7% | 0.00% |

Yesa (CHE) achieves the highest mean S_c of all analysed reservoirs — the model is not biased towards the calibration basin. KS test (n=365,858): Δμ=0.051 between basins, operationally negligible, explained by historical series length difference (9yr CHG vs 1yr CHE).

---

## Architecture

```
INGESTION → SCORING → VETO → VALIDATION
    │            │        │
    ▼            ▼        ▼
  data/       data/    output/
  curated    analytic  forensics/
                │
         ┌──────┴──────┐
         ▼             ▼
      REST API     DASHBOARD
      FastAPI      Streamlit
```

---

## Command reference

```powershell
# Ingestion
python src/ingestion/run_ingestion.py                          # CHG
python src/ingestion/saih_ebro_reader.py --all                 # CHE
python src/ingestion/aemet_connector.py --mode all             # AEMET real-time

# Scoring
python src/scoring/run_scoring.py --detailed                   # CHG
python src/scoring/run_scoring.py --confederation CHE --detailed  # CHE

# Validation
python src/validation/run_validation.py
python notebooks/validacion/kairi_sio_intercuencas.py          # Cross-basin

# API
uvicorn src.api.main:app --reload --port 8000

# Dashboard
streamlit run dashboard.py
```

---

## Theoretical foundations

| Parameter | Value | Reference |
|---|---|---|
| Weights (W_F/L/T/H) | 0.40/0.30/0.20/0.10 | AHP — Saaty (1980), CR<0.10 |
| CERTIFIED threshold | ≥0.85 | Algebraic property + GUM JCGM 100:2008 |
| VETOED threshold | <0.50 | Uncertainty dominance — GUM JCGM 100:2008 |
| FLATLINE_K | 8h | Nelson Rule 2 (1984) — ISO 7870-2:2013 |
| FLAT_CRITICAL_H | 48h | 2 nycthemeral cycles — WMO-No.168 |
| DRIFT_THRESH | 3.0 | Empirical percentile UCL — Page (1954) / Lucas & Saccucci (1990) |
| LAT_CRITICAL_S | 900s | SAIH nominal interval — WMO-No.168 |
| GAP_WARN / GAP_FAIL | 0.10 / 0.30 | WMO completeness: 90% / 70% |

---

## Project structure

```
kairi-sio/
├── dashboard.py              # Streamlit dashboard (multibasin)
├── src/
│   ├── api/                  # FastAPI REST API
│   ├── config/               # Multi-confederation YAML config
│   │   └── confederations/   # CHG.yaml, CHE.yaml, CHD.yaml, CHT.yaml
│   ├── ingestion/            # SAIH readers + AEMET connector
│   ├── scoring/              # S_f, S_l, S_t, S_h, scorer, CLI
│   ├── validation/           # Ground truth + metrics
│   └── veto/                 # Decision engine
├── data/
│   ├── curated/              # Normalised parquets (Data Contract v1.1)
│   └── analytic/             # Scored parquets with S_c, quality_flag
├── notebooks/
│   └── validacion/           # Cross-basin experiment
├── docs/                     # Technical documentation (ES/EN/DE)
└── output/
    └── validation/           # Validation reports + charts
```

---

## Documentation

Full technical documentation available in three languages:

- 🇪🇸 [Documentación Técnica](docs/arquitectura/KAIRI_SIO_Documentacion_Tecnica_v1.1.md)
- 🇬🇧 [Technical Documentation](docs/arquitectura/KAIRI_SIO_Technical_Documentation_v1.1_EN.md)
- 🇩🇪 [Technische Dokumentation](docs/arquitectura/KAIRI_SIO_Technische_Dokumentation_v1.1_DE.md)

---

## Authors

**Reymar** — mathematical specification · hydrological domain expertise  
**Kent Valera Chirinos** — technical implementation · systems engineering  

---

## License

MIT License — see [LICENSE](LICENSE) for details.

Data sources: SAIH Guadalquivir (CHG) · SAIH Ebro (CHE) · SNCZI/MITECO · AEMET OpenData