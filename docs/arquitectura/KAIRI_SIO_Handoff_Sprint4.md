# KAIRI-SIO — Documento de Contexto para Nuevo Chat
## Handoff Sprint 0–3 → Sprint 4
**Fecha:** 11 de marzo de 2026 | **Próximo:** Sprint 4 — Demo Visual (notebook Jupyter)

---

## QUIÉN SOY Y QUÉ ES ESTO

Soy **Kent Valera Chirinos**, ingeniero de telecomunicaciones. Estoy construyendo KAIRI-SIO con mi colaborador **Reymar** (Dinamarca, autor de la especificación matemática).

**KAIRI-SIO** es un sistema determinista de verificación de integridad de señal hidrológica. No sustituye al SAIH — actúa como capa independiente de certificación. MVP sobre datos reales SAIH Guadalquivir (3 embalses, 2015–2024).

---

## ESTADO ACTUAL

```
✅ Sprint 0 — Inspección dato real (xlsx SAIH, bugs DST, calibración bounds)
✅ Sprint 1 — Pipeline ingestion (saih_reader, normalizer, validator, run)
✅ Sprint 2 — Pipeline scoring (S_f, S_l, S_t, S_h, scorer, run)
✅ Sprint 3 — Motor de veto + forense JSONL (decision_engine, forensic_logger, run_veto)
⏳ Sprint 4 — Demo visual (notebook Jupyter) ← LO QUE SIGUE
```

---

## ESTRUCTURA DE CARPETAS (estado actual en mi máquina)

```
C:\KAIRI-SIO\
│
├── .venv\                          ← virtualenv Python 3.12 (activar siempre primero)
│
├── src\
│   ├── __init__.py
│   ├── ingestion\
│   │   ├── __init__.py
│   │   ├── saih_reader.py          ← lee xlsx SAIH por XML interno del ZIP
│   │   ├── normalizer.py           ← pivota a Data Contract v1.1 (Parquet)
│   │   ├── validator.py            ← validación fail-fast
│   │   └── run_ingestion.py        ← entry point Sprint 1
│   ├── scoring\
│   │   ├── __init__.py
│   │   ├── s_f.py                  ← S_f integridad física (bounds por embalse)
│   │   ├── s_l.py                  ← S_l coherencia lógica (C_PH, C_QH, C_z MAD)
│   │   ├── s_t.py                  ← S_t integridad temporal (latencia piecewise)
│   │   ├── s_h.py                  ← S_h salud histórica (flatline, drift, gap24)
│   │   ├── scorer.py               ← compositor S_c + quality_flag
│   │   └── run_scoring.py          ← entry point Sprint 2
│   ├── veto\
│   │   ├── __init__.py
│   │   ├── decision_engine.py      ← motor de veto + CRITICAL_FLAG + reasons
│   │   └── run_veto.py             ← entry point Sprint 3
│   └── forensics\
│       ├── __init__.py
│       └── forensic_logger.py      ← JSONL append-only + CSV por embalse
│
├── data\
│   ├── raw\saih_guadalquivir\      ← LANDING_ZONE — NUNCA TOCAR
│   │   ├── E32_VADOMOJON\
│   │   │   ├── Nivel\              (2 xlsx: 2015-2020, 2020-2024)
│   │   │   ├── Aportacion\         (2 xlsx)
│   │   │   └── Precipitacion\      (2 xlsx)
│   │   ├── E33_SRRA_BOYERA\        (misma estructura, 6 xlsx)
│   │   └── E37_BEMBEZAR\           (misma estructura, 6 xlsx)
│   │
│   ├── curated\                    ← CURATED_ZONE — output Sprint 1
│   │   ├── E32_VADOMOJON.parquet           (4,538 KB — 86,947 rows)
│   │   ├── E33_SRRA_BOYERA.parquet         (4,399 KB — 86,947 rows)
│   │   └── E37_BEMBEZAR.parquet            (4,477 KB — 86,947 rows)
│   │
│   └── analytic\                   ← ANALYTIC_ZONE — output Sprint 2
│       ├── E32_VADOMOJON_scored.parquet    (4,641 KB)
│       ├── E33_SRRA_BOYERA_scored.parquet  (4,497 KB)
│       └── E37_BEMBEZAR_scored.parquet     (4,572 KB)
│
├── output\
│   └── forensics\                  ← output Sprint 3 (JSONL + CSV)
│       ├── E32_VADOMOJON_forensic_20260311T192907.jsonl
│       ├── E32_VADOMOJON_summary_20260311T192907.csv
│       ├── E33_SRRA_BOYERA_forensic_20260311T192907.jsonl
│       ├── E33_SRRA_BOYERA_summary_20260311T192907.csv
│       ├── E37_BEMBEZAR_forensic_20260311T192907.jsonl
│       └── E37_BEMBEZAR_summary_20260311T192907.csv
│
├── notebooks\
│   └── mvp_demo\                   ← VACÍO — aquí va Sprint 4
│
└── docs\
    ├── arquitectura\
    └── modelo_matematico\
        └── 20260301_TEC_Formulas_Sc_Veto_v1.0.txt   ← especificación matemática Reymar
```

---

## DATOS CLAVE — COLUMNAS EN LOS PARQUET

### `data/curated/*.parquet` (Data Contract v1.1)
```
uuid         → UUIDv4 string      (identificador forense único por fila)
sensor_id    → str                (E32_VADOMOJON / E33_SRRA_BOYERA / E37_BEMBEZAR)
ts_station   → datetime64[us]     (hora local SAIH — resolución 1h)
ts_ingest    → datetime64[us,UTC] (timestamp procesamiento KAIRI)
H_level      → float64 | NaN      (metros, cota absoluta)
Q_inflow     → float64 | NaN      (m³/s)
P_rain       → float64 | NaN      (mm/h)
source_files → str                (nombre del xlsx origen)
```

### `data/analytic/*_scored.parquet` (columnas adicionales)
```
S_f          → float64 [0,1]
S_l          → float64 [0,1]
S_t          → float64 [0,1]
S_h          → float64 [0,1]
S_c          → float64 [0,1]      ← score global de confianza
quality_flag → str                (CERTIFICADA / DEGRADADA / VETADA)

# Si se generó con --detailed, también hay:
sl_C_PH      → float64            (coherencia lluvia/nivel)
sl_C_QH      → float64            (coherencia caudal/nivel)
sl_C_z       → float64            (z-score robusto MAD rolling 24h)
st_lat_s     → float64            (latencia en segundos)
st_gap_W1    → float64            (gap rate ventana 1h)
sh_F_flat    → float64            (penalización flatline K=8)
sh_F_drift   → float64            (penalización drift EMA)
sh_F_gap24   → float64            (penalización gap rate 24h)
```

### `output/forensics/*_summary_*.csv`
```
ts_station, sensor_id, S_c, S_f, S_l, S_t, S_h,
quality_flag, veto_level, critical_flag, primary_reason
```

---

## MODELO MATEMÁTICO (resumen ejecutivo)

```python
# Score global
S_c = clamp01(0.40*S_f + 0.30*S_l + 0.20*S_t + 0.10*S_h)

# Motor de veto
CERTIFICADA : S_c >= 0.85
DEGRADADA   : 0.50 <= S_c < 0.85
VETADA      : S_c < 0.50  OR  CRITICAL_FLAG

# CRITICAL_FLAG = True si:
#   S_f == 0.0
#   OR  lat_s > 900
#   OR  (C_PH == 0.4 AND C_z == 0.3)

# S_l = min(C_PH, C_QH, C_z)
#   C_PH: 1.0/0.4/0.7  (coherencia lluvia→nivel)
#   C_QH: 1.0/0.5      (coherencia caudal→nivel, umbral p90 Q no-cero)
#   C_z:  1.0/0.7/0.3  (z-score robusto MAD rolling 24h, umbrales 3/6)

# S_t = L(lat) * (1 - gap_rate_W1)
#   L: 1.0/0.7/0.4/0.1  (piecewise: <=60s / <=300s / <=900s / >900s)

# S_h = min(F_flat, F_drift, F_gap24)
#   F_flat  = 0.2 si >=8 idénticos consecutivos
#   F_drift = 0.3 si |EMA_6h - EMA_24h| / (std_24h + 1e-6) > 3.0
#   F_gap24 = 0.2/0.6/1.0  (gap_rate >=30% / >=10% / <10%)
```

### Bounds físicos calibrados (s_f.py)
```python
PHYSICAL_BOUNDS = {
    'E32_VADOMOJON':   {'H_level': (325.0, 375.0), 'Q_inflow': (0.0,  600.0), 'P_rain': (0.0,  50.0)},
    'E33_SRRA_BOYERA': {'H_level': (380.0, 700.0), 'Q_inflow': (0.0,  600.0), 'P_rain': (0.0,  50.0)},
    'E37_BEMBEZAR':    {'H_level': (80.0,  190.0), 'Q_inflow': (0.0, 1500.0), 'P_rain': (0.0,  70.0)},
}
# NOTA: E37 fue corregido de (300,450) a (80,190) — bug crítico Sprint 2
```

---

## RESULTADOS FINALES SPRINT 3 (números reales)

| Embalse | Rows | CERTIFICADA | DEGRADADA | VETADA (críticos) | S_c medio |
|---|---|---|---|---|---|
| E32_VADOMOJON | 86,947 | 61.5% (53,460) | 38.3% (33,292) | 0.2% (195) | 0.9014 |
| E33_SRRA_BOYERA | 86,947 | 54.2% (47,122) | 45.7% (39,711) | 0.1% (114) | 0.8871 |
| E37_BEMBEZAR | 86,947 | 54.2% (47,129) | 45.6% (39,659) | 0.2% (159) | 0.8876 |
| **TOTAL** | **260,841** | | | | |

**Todos los VETADA son CRITICAL_FLAG** — los 10 cambios de hora DST anuales (lat=3600s > 900s) más coincidencias de flatline. El SAIH no registra la hora omitida por DST.

---

## CÓMO CORRER CADA SPRINT

```powershell
# Activar entorno
cd C:\KAIRI-SIO
.venv\Scripts\activate

# Sprint 1 — Ingestion
python src/ingestion/run_ingestion.py

# Sprint 2 — Scoring
python src/scoring/run_scoring.py
python src/scoring/run_scoring.py --detailed    # con sub-columnas

# Sprint 3 — Veto + Forense
python src/veto/run_veto.py                     # todos los eventos
python src/veto/run_veto.py --level 1           # DEGRADADA + VETADA
python src/veto/run_veto.py --level 2           # solo VETADA
```

---

## LO QUE FALTA — SPRINT 4

### Objetivo
Crear `notebooks/mvp_demo/kairi_sio_demo.ipynb` — notebook Jupyter de demostración visual del MVP.

### Contenido mínimo del notebook

**Bloque 1 — Carga de datos**
```python
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Cargar los 3 Parquet analytic
embalses = ['E32_VADOMOJON', 'E33_SRRA_BOYERA', 'E37_BEMBEZAR']
dfs = {e: pd.read_parquet(f'data/analytic/{e}_scored.parquet') for e in embalses}
```

**Bloque 2 — Distribución de quality_flag** (gráfica de barras apiladas por embalse)

**Bloque 3 — Serie temporal de S_c** para cada embalse, con eventos VETADA marcados en rojo

**Bloque 4 — Zoom en eventos VETADA** — mostrar los DST (29 marzo cada año) con H_level + S_t

**Bloque 5 — Comparativa de sub-scores** S_f / S_l / S_t / S_h por embalse (boxplot o violin)

**Bloque 6 — Tabla resumen** con todas las métricas finales

### Dependencias para Sprint 4
```bash
pip install jupyter matplotlib seaborn --break-system-packages
# o con el .venv:
.venv\Scripts\activate
pip install jupyter matplotlib seaborn
```

### Pendientes técnicos antes de Sprint 4
1. `git init` en `C:\KAIRI-SIO\` → activa `code_hash` real en JSONL (actualmente = "NO_GIT")
2. Refinar bounds `E33_SRRA_BOYERA` H_level máximo real (actualmente 700m conservador)
3. Opcional: regenerar los Parquet scored con `--detailed` para tener sub-columnas disponibles en el notebook

---

## INVARIANTES DE DISEÑO (no negociables)

| Principio | Descripción |
|---|---|
| `None ≠ 0.0` | Dato faltante SIEMPRE es None/NaN, nunca imputado a cero |
| Inmutabilidad raw | `data/raw/` nunca se modifica bajo ninguna circunstancia |
| Determinismo | Mismo input = mismo output. Sin random, sin state oculto |
| Auditabilidad | UUID v4 + SHA-256 data_hash en cada decisión forense |
| Append-only | El JSONL forense nunca se reescribe, solo se añade |
| Calibración empírica | Umbrales SIEMPRE de percentiles reales, nunca de estimaciones |

---

## DEPENDENCIAS (`requirements.txt`)

```
pandas>=2.0
openpyxl>=3.1
numpy>=1.24
scipy>=1.11
pyarrow>=13.0
python-dotenv>=1.0
jupyter>=1.0
matplotlib>=3.7
seaborn>=0.12
pytest>=7.4
```

---

## CONTEXTO PERSONAL

- Proyecto paralelo a mi trabajo en Silicon Saxony (Heidenau, Saxony)
- KAIRI-SIO es proyecto de Reymar — yo soy el ingeniero de implementación
- El MVP demuestra que la certificación de señal hidrológica es técnicamente factible con datos reales
- No hay compromiso comercial ni agenda institucional en este momento
- La metodología: datos reales → calibración empírica → cero supuestos teóricos no verificados

---

*Generado: 11 de marzo de 2026 | Kent Valera Chirinos*
*Usar este documento como contexto inicial en el nuevo chat para Sprint 4*
