# KAIRI-SIO — Statement of Work
**Sistema de Verificación de Integridad de Señal Hidrológica**
**Versión 1.1 — 12 de marzo de 2026**

---

## 1. Identificación del proyecto

| Campo | Detalle |
|---|---|
| Nombre del sistema | KAIRI-SIO |
| Tipo | Sistema determinista de verificación de integridad de señal hidrológica |
| Dominio | Monitorización operacional de embalses · SAIH Guadalquivir |
| Repositorio | `C:\KAIRI-SIO\` |
| Versión actual | v1.1 (Sprint 5 completado) |
| Fecha de corte | 12 de marzo de 2026 |

### Equipo

| Rol | Persona | Ubicación |
|---|---|---|
| Especificación matemática · estrategia institucional | Reymar | Dinamarca |
| Implementación técnica completa | Kent Valera Chirinos | Heidenau, Saxonia, Alemania |

---

## 2. Objetivo del sistema

KAIRI-SIO produce, para cada observación horaria de un sistema hidrológico, un **score de coherencia compuesto S_c ∈ [0,1]** que cuantifica la confiabilidad del dato y lo clasifica automáticamente en tres regímenes operacionales:

| Régimen | Condición | Significado |
|---|---|---|
| **CERTIFICADA** | S_c ≥ 0.85 | Dato utilizable sin reservas |
| **DEGRADADA** | 0.50 ≤ S_c < 0.85 | Utilizable con cautela y contexto adicional |
| **VETADA** | S_c < 0.50 | No utilizable · incertidumbre dominante |

El sistema es **100% determinista**: mismo input → mismo output. No hay modelos estadísticos probabilísticos ni black boxes. Cada decisión queda registrada en JSONL append-only con UUID v4 y SHA-256 del dato de entrada.

---

## 3. Dataset de referencia (MVP)

| Campo | Valor |
|---|---|
| Fuente | SAIH Guadalquivir (datos abiertos) |
| Formato landing zone | XLSX (formato confirmado Sprint 0) |
| Periodo | 2015–2024 |
| Total observaciones brutas | 260,841 |
| Observaciones curadas (parquet) | 86,947 filas × 3 embalses |
| Variables principales | H_level (cota embalse), Q_inflow (caudal entrada), P_rain (precipitación) |

### Embalses del MVP

| ID | Nombre | Observaciones |
|---|---|---|
| E32 | Vado Mojón | 86,947 |
| E33 | Sierra Boyera | 86,947 |
| E37 | Bembézar | 86,947 |

---

## 4. Arquitectura del sistema

### 4.1 Estructura de directorios

```
C:\KAIRI-SIO\
├── .venv\                          Python 3.12
├── src\
│   ├── ingestion\                  Lector, normalizador, validador, orquestador
│   ├── scoring\
│   │   ├── scorer.py               Score compuesto S_c
│   │   └── s_h.py                  Sub-score salud histórica (incluye flat_duration_h)
│   ├── veto\
│   │   └── decision_engine.py      Motor de veto y CRITICAL_FLAG
│   ├── forensics\                  Registro forense JSONL
│   └── validation\
│       ├── ground_truth_builder.py  Constructor de verdad de campo
│       └── run_validation.py        Validación precision/recall/F1
├── data\
│   ├── raw\saih_guadalquivir\      LANDING ZONE — nunca modificar
│   ├── curated\*.parquet           86,947 filas × 3 embalses
│   └── analytic\*_scored.parquet  28 columnas (con --detailed)
└── output\
    ├── forensics\*_summary_*.csv
    ├── validation\
    │   ├── ground_truth.parquet
    │   ├── validation_detail.parquet
    │   ├── validation_report.csv / .txt
    │   └── kairi_sio_justificacion_formal.docx
    └── demo\                        Outputs Sprint 4
```

### 4.2 Pipeline de procesamiento

```
XLSX (landing zone)
    → reader.py          Lectura bruta, sin modificar
    → normalizer.py      Normalización de timestamps y unidades
    → validator.py       Validación estructural
    → orchestrator.py    Coordinación del pipeline
    → scorer.py          Cálculo S_f, S_l, S_t, S_h → S_c
    → decision_engine.py Clasificación CERT/DEGR/VETO/CRITICAL
    → forensics/         Registro JSONL determinista
```

---

## 5. Modelo de scoring

### 5.1 Score compuesto

```
S_c = 0.40·S_f + 0.30·S_l + 0.20·S_t + 0.10·S_h
```

### 5.2 Sub-scores

| Sub-score | Peso | Descripción |
|---|---|---|
| **S_f** — Física | 0.40 | Consistencia con restricciones físicas del embalse (bounds H_level, Q, P) |
| **S_l** — Lógica | 0.30 | Coherencia entre variables hidrológicas dependientes (H, Q, P) |
| **S_t** — Temporal | 0.20 | Estabilidad temporal: deriva EMA, flatline, gaps |
| **S_h** — Histórica | 0.10 | Salud histórica del sensor: drift acumulado, degradación lenta |

### 5.3 Parámetros y justificación formal

| Parámetro | Valor | Justificación | Estado |
|---|---|---|---|
| W_F / W_L / W_T / W_H | 0.40 / 0.30 / 0.20 / 0.10 | AHP (Saaty 1980) — jerarquía de integridad hidráulica | ✓ FUNDAMENTADO |
| Umbral VETADA | S_c < 0.50 | Principio de dominancia de incertidumbre (GUM JCGM 100:2008) + propiedad algebraica del modelo | ✓ FUNDAMENTADO |
| Umbral CERTIFICADA | S_c ≥ 0.85 | Propiedad algebraica: deficiencia ponderada ≤ 0.15 (GUM) | ✓ FUNDAMENTADO |
| FLATLINE_K | 8 horas | Nelson (1984) Regla 2 · ISO 7870-2:2013 | ✓ FUNDAMENTADO |
| FLAT_CRITICAL_H | 48 horas | 2 ciclos nictemerales · WMO-No.168 Cap. 2 | ✓ FUNDAMENTADO |
| DRIFT_THRESH | 3.0 | UCL por percentil de referencia empírico (distribución leptocúrtica confirmada). Marco CUSUM/EWMA (Page 1954, Lucas & Saccucci 1990) | ✓ FUNDAMENTADO |
| LAT_CRITICAL_S | 900 s | Intervalo nominal de transmisión SAIH Guadalquivir | ✓ FUNDAMENTADO |
| GAP_WARN / GAP_FAIL | 0.10 / 0.30 | Criterios de completitud WMO-No.168 Cap. 2 / WMO-No.8 | ✓ FUNDAMENTADO |
| Bounds físicos H_level | por embalse | Fichas técnicas oficiales CHG (pendiente) | ⚠ PROVISIONAL |

### 5.4 CRITICAL_FLAG — condiciones de activación

Un registro recibe CRITICAL_FLAG (nivel máximo de alerta) cuando se cumple cualquiera de:

- `flat_duration_h ≥ 48.0` — sensor congelado ≥ 2 ciclos nictemerales
- Transición DST detectada (cambio de hora ±1h)
- `C_PH > 0 AND C_z > 0` — fallo físico + anomalía estadística simultáneos
- `S_f = 0.0` — fallo físico total (bounds violados)

---

## 6. Resultados por sprint

### Sprint 0 — Exploración de datos
- Confirmación formato XLSX del SAIH Guadalquivir
- Identificación de estructura de columnas y encoding

### Sprint 1 — Pipeline de ingesta
- `reader.py`, `normalizer.py`, `validator.py`, `orchestrator.py`
- Validados contra datos reales
- 86,947 filas × 3 embalses curados en parquet

### Sprint 2 — Scoring engine
- Implementación S_f, S_l, S_t, S_h y score compuesto S_c
- Primera versión de `scorer.py` y `decision_engine.py`

### Sprint 3 — Forensics y control de calidad
- Sistema JSONL append-only con UUID v4 + SHA-256
- Registro determinista de cada decisión
- Outputs: `*_summary_*.csv`

### Sprint 4 — Demo institucional
- `notebooks/mvp_demo/kairi_sio_demo.py`
- Outputs en `output/demo/`
- Presentación del sistema funcional end-to-end

### Sprint 5 — Ground truth y validación formal (ACTUAL)

**Extensión CRITICAL_FLAG por flatline:**
- Añadida función `_flat_duration()` en `s_h.py`
- Nueva columna `flat_duration_h` en scored parquets (modo --detailed)
- Condición `flat_duration_h ≥ 48h` → CRITICAL_FLAG en `decision_engine.py`

**Ground truth builder:**
- `ground_truth_builder.py` — detecta 3 tipos de error conocido:
  - SPIKE_SENSOR: |ΔH| > 1.0m en 1 hora
  - FLATLINE: H_level idéntico ≥ 24 horas consecutivas
  - GAP_COMM: NaN simultáneo H+Q+P ≥ 3 horas
- Total errores identificados: 14,614 timestamps

**Resultados de validación (post-extensión flatline):**

| Embalse | N_CERT | N_DEGR | N_VETO | N_CRIT | S_c μ |
|---|---|---|---|---|---|
| E32 Vado Mojón | 52,913 | 32,875 | 1,159 | 1,159 | 0.9014 |
| E33 Sierra Boyera | 46,778 | 38,656 | 1,513 | 1,513 | 0.8871 |
| E37 Bembézar | 46,923 | 39,418 | 606 | 606 | 0.8876 |

**Recall de flatline antes/después de extensión CRITICAL_FLAG:**

| Embalse | Recall antes | Recall después | Δ |
|---|---|---|---|
| E32 | 0.674 | 0.762 | +0.088 |
| E33 | 0.844 | 0.880 | +0.036 |
| E37 | 0.568 | 0.608 | +0.040 |

- SPIKE recall: **1.000** (sin cambio — detección perfecta)
- GAP recall modo normal: **1.000**
- GAP recall modo strict: **0.000** (los gaps activan CRITICAL_FLAG, no VETADA directa — comportamiento correcto por diseño)

**Análisis distribucional DRIFT_THRESH:**
- Distribución de deriva EMA normalizada: **no gaussiana** (kurtosis = 618, skewness = 20.8)
- Rechazada por Shapiro-Wilk, D'Agostino-Pearson, KS y Anderson-Darling (p < 10⁻⁶²)
- DRIFT_THRESH = 3.0 validado como UCL en el punto de inflexión natural de la cola derecha de la distribución real

**Justificación formal de parámetros:**
- Completada derivación AHP para pesos
- Completada derivación algebraica de umbrales S_c (0.50 y 0.85)
- Todos los parámetros salvo bounds físicos H_level están formalmente fundamentados

---

## 7. Invariantes de diseño (no negociables)

1. **`None ≠ 0.0`** — dato faltante siempre NaN, nunca imputado
2. **`data/raw/` inmutable** — landing zone nunca se toca
3. **Determinismo estricto** — mismo input = mismo output, siempre
4. **UUID v4 + SHA-256** en cada decisión forense
5. **JSONL append-only** — el registro forense nunca se sobreescribe
6. **Umbrales de percentiles reales** — nunca estimaciones teóricas

---

## 8. Pendientes y trabajo futuro

### 8.1 Pendientes técnicos

| ID | Tarea | Responsable | Prioridad |
|---|---|---|---|
| T-01 | `git init` en `C:\KAIRI-SIO\` → activa `code_hash` real en JSONL (actualmente "NO_GIT") | Kent | Alta |
| T-02 | Calibrar bounds físicos H_level con fichas técnicas oficiales CHG para E32, E33, E37 | Kent + Reymar/CHG | Alta |
| T-03 | Refinar H_max E33 Sierra Boyera (actualmente 700m conservador) | Kent + CHG | Media |
| T-04 | Convertir LAT_CRITICAL_S en parámetro configurable por confederación (`conf_latency_threshold`) | Kent | Media |
| T-05 | Actualizar `TEC_Formulas_Sc_Veto_v1.0.txt` → v1.1 con sección de justificación formal | Kent | Media |

### 8.2 Pendientes de fundamentación

| ID | Parámetro | Pendiente | Fuente requerida |
|---|---|---|---|
| F-01 | Bounds físicos H_level | Cruzar con Catálogo Nacional de Presas + fichas técnicas CHG | CHG / Ministerio Transición Ecológica |
| F-02 | SPIKE_THRESH = 1.0m | Calibración por embalse con curvas de capacidad hidráulica oficial | CHG — fichas E32, E33, E37 |

### 8.3 Expansión institucional (siguientes sprints)

| ID | Tarea | Descripción |
|---|---|---|
| E-01 | Multiconfederación | Portabilidad a CHE (Ebro), CHT (Tajo), CHD (Duero) |
| E-02 | Configuración por confederación | Fichero de parámetros YAML por cuenca |
| E-03 | API REST | Endpoint de scoring en tiempo real para integración con sistemas SAIH |
| E-04 | Dashboard de monitorización | Visualización de regímenes y alertas en tiempo real |
| E-05 | Informe institucional final | Documento técnico de presentación a confederaciones |

---

## 9. Referencias bibliográficas y normativas

### Normativa

| Referencia | Uso en el sistema | PDF descargable |
|---|---|---|
| **WMO-No.168 Vol. I** — Guide to Hydrological Practices, 6ª ed. | GAP_WARN, GAP_FAIL, FLAT_CRITICAL_H | [hydrology.nl](https://www.hydrology.nl/images/docs/hwrp/WMO_Guide_168_Vol_I_en.pdf) |
| **WMO-No.8** — Guide to Instruments and Methods of Observation (2018) | GAP_WARN, GAP_FAIL | [WMO Library](https://library.wmo.int/viewer/41650/download?file=8-V-2018_en_1.pdf&type=pdf) |
| **JCGM 100:2008 (GUM)** — Guide to Expression of Uncertainty in Measurement | Umbrales VETADA/CERTIFICADA | [BIPM oficial](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf) |
| **ISO 7870-2:2013** — Shewhart Control Charts | FLATLINE_K | [africanfoodsafetynetwork.org](https://www.africanfoodsafetynetwork.org/wp-content/uploads/2021/09/ISO-7870-2-ver-2013_Control-Charts-2.pdf) |

### Bibliografía científica

| Referencia | Uso en el sistema | Acceso |
|---|---|---|
| Nelson, L.S. (1984). The Shewhart Control Chart — Tests for Special Causes. *Journal of Quality Technology*, 16(4), 237-239. | FLATLINE_K = 8 | [Lean Six Sigma Definition PDF](https://www.leansixsigmadefinition.com/wp-content/uploads/2023/07/The-Shewhart-Control-Chart-Tests-for-Special-Causes-Lloyd-Nelson-Journal-of-Quality-Technology.pdf) |
| Page, E.S. (1954). Continuous Inspection Schemes. *Biometrika*, 41(1-2), 100-115. | Marco CUSUM — DRIFT_THRESH | DOI: 10.1093/biomet/41.1-2.100 |
| Lucas, J.M. & Saccucci, M.S. (1990). Exponentially Weighted Moving Average Control Schemes. *Technometrics*, 32(1), 1-12. | Marco EWMA — DRIFT_THRESH | DOI: 10.1080/00401706.1990.10484678 |
| Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill. | Pesos AHP | Referencia bibliográfica |
| Montgomery, D.C. (2012). *Introduction to Statistical Quality Control*, 7ª ed. Wiley. | Marco SPC general | Referencia bibliográfica |

---

## 10. Documentos del proyecto

| Documento | Descripción | Ubicación |
|---|---|---|
| `kairi_sio_nota_tecnica.docx` | Nota técnica Sprint 5 para Reymar | `output/validation/` |
| `kairi_sio_cuestionario_reymar.docx` | Cuestionario de fundamentación (9 preguntas) | `output/validation/` |
| `kairi_sio_justificacion_formal.docx` | Justificación formal de todos los parámetros | `output/validation/` |
| `kairi_sio_SOW.pdf` | Este documento (Statement of Work) | `output/validation/` |
| `kairi_sio_SOW.md` | Versión Markdown de este SOW | `output/validation/` |
| `TEC_Formulas_Sc_Veto_v1.0.txt` | Fórmulas técnicas del modelo (pendiente v1.1) | `C:\KAIRI-SIO\` |

---

*KAIRI-SIO v1.1 · Reymar (especificación) · Kent Valera Chirinos (implementación) · 12 de marzo de 2026*
