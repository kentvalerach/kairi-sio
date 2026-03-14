# KAIRI-SIO — Documentación Técnica del Sistema
**Versión:** 1.1.0  
**Fecha:** 2026-03-13  
**Autores:** Reymar (especificación matemática) · Kent Valera Chirinos (implementación técnica)  
**Estado:** Producción piloto — CHG Guadalquivir + CHE Ebro

---

## Tabla de contenidos

1. [Visión general del sistema](#1-visión-general-del-sistema)
2. [Fundamentos teóricos](#2-fundamentos-teóricos)
3. [Arquitectura del sistema](#3-arquitectura-del-sistema)
4. [Modelo de scoring compuesto S_c](#4-modelo-de-scoring-compuesto-sc)
5. [Pipeline de procesamiento](#5-pipeline-de-procesamiento)
6. [Configuración multiconfederación](#6-configuración-multiconfederación)
7. [API REST](#7-api-rest)
8. [Dashboard de monitorización](#8-dashboard-de-monitorización)
9. [Conector AEMET](#9-conector-aemet)
10. [Validación intercuencas](#10-validación-intercuencas)
11. [Referencia de comandos](#11-referencia-de-comandos)
12. [Estructura del proyecto](#12-estructura-del-proyecto)

---

## 1. Visión general del sistema

KAIRI-SIO (Sistema de Verificación de Integridad de Señal Hidrológica) es un sistema determinista de control de calidad de datos en tiempo real para redes SAIH (Sistema Automático de Información Hidrológica) de Confederaciones Hidrográficas españolas. El sistema evalúa la integridad de las señales de sensores hidrometeorológicos —nivel de embalse, precipitación, aforo— aplicando un modelo de scoring compuesto fundamentado en normativa internacional de metrología y control estadístico de procesos.

KAIRI-SIO no modela comportamiento hidrológico ni realiza predicciones de caudal. Su dominio exclusivo es la **verificación de la fiabilidad de la señal de medición**: determinar si una observación recibida de un sensor puede considerarse íntegra o si presenta evidencias de degradación instrumental.

### 1.1 Problema que resuelve

Las redes SAIH transmiten datos de sensores remotos a 15 minutos de intervalo desde cientos de puntos de control distribuidos por cuencas hidrográficas de decenas de miles de km². Las disfunciones instrumentales más frecuentes —sensor congelado (*flatline*), teletransmisión con latencia excesiva, deriva de señal, spikes por ruido electromagnético, pérdida de continuidad temporal— no son detectables de forma automática por los sistemas SCADA existentes sin lógica de validación específica.

La consecuencia operacional es que observaciones defectuosas entran en los sistemas de información como datos válidos, contaminando cálculos de balance hídrico, modelos de previsión de avenidas y registros históricos utilizados en planificación hidrológica.

KAIRI-SIO asigna a cada observación un score de integridad $S_c \in [0, 1]$ y una clasificación de régimen (`CERTIFICADA`, `DEGRADADA`, `VETADA`) que permite a los operadores y sistemas aguas abajo tomar decisiones informadas sobre la fiabilidad de cada dato.

### 1.2 Alcance operacional validado

| Confederación | Embalses | Período | Observaciones |
|---|---|---|---|
| CHG · Guadalquivir | E32 Vado Mojón, E33 Sierra Boyera, E37 Bembézar | 2015–2024 | 260,841 |
| CHE · Ebro | Itoiz, Mequinenza, Yesa | 2025–2026 | 105,017 |
| **Total** | **6 embalses** | | **365,858** |

---

## 2. Fundamentos teóricos

### 2.1 Modelo de pesos — Proceso Analítico Jerárquico (AHP)

Los pesos del score compuesto se derivan mediante el método AHP (Saaty, 1980), que formaliza matemáticamente juicios comparativos de experto en un vector de pesos con consistencia verificable. La matriz de comparación por pares refleja una jerarquía de integridad hidráulica: las restricciones físicas del sensor tienen prioridad sobre las métricas estadísticas derivadas.

$$S_c = 0.40 \cdot S_f + 0.30 \cdot S_l + 0.20 \cdot S_t + 0.10 \cdot S_h$$

El índice de consistencia de la matriz es $CR < 0.10$, confirmando la coherencia de los juicios comparativos según el criterio de Saaty (1980). Referencias: *The Analytic Hierarchy Process* (Saaty, 1980); Montgomery, *Introduction to Statistical Quality Control*, 7ª ed. (2012).

### 2.2 Umbrales de clasificación — GUM

Los umbrales de régimen se derivan de propiedades algebraicas del modelo y de la Guía para la Expresión de la Incertidumbre de Medición (GUM, JCGM 100:2008).

**Umbral VETADA ($S_c < 0.50$) — principio de dominancia de incertidumbre:**

En un score compuesto con pesos que suman 1.0 y sub-scores en $[0,1]$, el valor 0.50 corresponde al punto de equilibrio entre componentes fiables y componentes deficientes. Cuando $S_c < 0.50$, el peso acumulado de las dimensiones deficientes supera al de las dimensiones fiables. La GUM establece que una medición no es utilizable cuando su incertidumbre expandida supera al valor medido.

**Umbral CERTIFICADA ($S_c \geq 0.85$):**

Es el valor mínimo de $S_c$ tal que incluso si el sub-score de mayor peso ($S_f$, $W=0.40$) se degrada hasta 0.625 manteniendo los demás perfectos, $S_c$ sigue siendo aceptable:

$$0.40 \cdot x + 0.30 \cdot 1.0 + 0.20 \cdot 1.0 + 0.10 \cdot 1.0 = 0.85 \implies x = 0.625$$

### 2.3 Detección de flatlines — Control Estadístico de Procesos

El parámetro `FLATLINE_K = 8h` se justifica mediante la Regla 2 de Nelson (1984): ocho o más puntos consecutivos idénticos constituyen una señal inequívoca de proceso fuera de control. Esta regla está incorporada en ISO 7870-2:2013. En un embalse en operación normal, una secuencia de 8 observaciones horarias exactamente idénticas es estadísticamente improbable dado el ruido instrumental inherente.

El umbral crítico `FLAT_CRITICAL_H = 48h` se justifica por tres argumentos complementarios:
- **Ciclos hidrológicos naturales (WMO-No.168):** 48h equivale a 2 ciclos nictemerales completos
- **Pérdida irreversible de información:** los eventos de variación significativa ($\Delta H > 0.05$ m/h) tienen duración media de 6–18h en el dataset SAIH Guadalquivir
- **Completitud WMO:** 48h en una ventana de 10 días representa el 20% de datos inválidos, superando el umbral de aceptación del 10% establecido por WMO-No.168

### 2.4 Detección de deriva — Detectores EWMA/CUSUM

El detector de deriva $F_{drift}$ es formalmente equivalente a un detector CUSUM (Page, 1954) o EWMA (Lucas & Saccucci, 1990) de cambio de media. Calcula la deriva normalizada:

$$\text{drift} = \frac{|EMA_{6h} - EMA_{24h}|}{\sigma_{24h}}$$

El umbral `DRIFT_THRESH = 3.0` se justifica como UCL (Upper Control Limit) por percentil de referencia de la distribución real del dataset SAIH Guadalquivir (n=86,947):

- Distribución con curtosis excesiva = 618.2, asimetría = 20.8
- La distribución no es gaussiana: Shapiro-Wilk, D'Agostino-Pearson, Kolmogorov-Smirnov y Anderson-Darling rechazan normalidad con $p < 10^{-62}$
- El valor 3.0 coincide con el punto de inflexión natural de la cola derecha de la distribución real

### 2.5 Umbrales de gaps — WMO

Los umbrales de completitud de datos se derivan directamente de WMO-No.168 y WMO-No.8:

| Parámetro | Valor | Criterio WMO |
|---|---|---|
| `GAP_WARN` | 0.10 | Completitud ≥ 90% para cálculo de caudales diarios |
| `GAP_FAIL` | 0.30 | Completitud ≥ 70% para análisis de eventos |

### 2.6 Latencia crítica — Protocolo SAIH

`LAT_CRITICAL_S = 900s` corresponde al intervalo de transmisión nominal del SAIH (15 minutos). Una observación con latencia superior a 900s ha llegado al sistema fuera de su ventana temporal de validez, equivalente a un desfase de más de un período de muestreo. Este parámetro es configurable por confederación para garantizar portabilidad.

---

## 3. Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KAIRI-SIO v1.1                               │
│                                                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │   INGESTA    │───▶│   SCORING    │───▶│  VETO / DECISIÓN     │   │
│  │              │    │              │    │                      │   │
│  │ saih_reader  │    │ s_f.py       │    │ decision_engine.py   │   │
│  │ ebro_reader  │    │ s_l.py       │    │ CRITICAL_FLAG        │   │
│  │ aemet_conn.  │    │ s_t.py       │    │ CERT/DEGR/VETADA     │   │
│  └──────────────┘    │ s_h.py       │    └──────────────────────┘   │
│         │            │ scorer.py    │              │                 │
│         ▼            └──────────────┘              ▼                 │
│  ┌──────────────┐              │            ┌──────────────┐         │
│  │  data/raw/   │              │            │   FORENSE    │         │
│  │  data/curated│              │            │ forensic_log │         │
│  │  data/analytic│             │            │ .jsonl audit │         │
│  └──────────────┘              │            └──────────────┘         │
│                                ▼                                      │
│                    ┌──────────────────────┐                          │
│                    │   VALIDACIÓN         │                          │
│                    │ ground_truth_builder │                          │
│                    │ intercuencas         │                          │
│                    └──────────────────────┘                          │
│                                │                                      │
│              ┌─────────────────┼──────────────────┐                 │
│              ▼                 ▼                  ▼                  │
│     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│     │  API REST    │  │  DASHBOARD   │  │  CONFIG      │           │
│     │  FastAPI     │  │  Streamlit   │  │  YAML/cuencas│           │
│     │  /score/*    │  │  dashboard   │  │  CHG/CHE/... │           │
│     └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Zonas de datos

| Zona | Ruta | Contenido | Política |
|---|---|---|---|
| **Raw** | `data/raw/` | CSV originales SAIH, parquets crudos | Inmutable |
| **Curated** | `data/curated/` | Parquets normalizados al Data Contract v1.1 | Regenerable |
| **Analytic** | `data/analytic/` | Parquets scored con S_c, quality_flag | Regenerable |
| **Fuentes oficiales** | `03_Datos_Fuentes_Oficiales/` | SNCZI, MDT, Caumax — datos oficiales MITECO | Intocable |

---

## 4. Modelo de scoring compuesto S_c

### 4.1 Sub-score de integridad física S_f

$S_f$ evalúa si los valores observados son físicamente plausibles para el embalse.

$$S_f = \text{clamp}_{[0,1]}\left(1 - F_{bounds} - F_{spike} - F_{flat}\right)$$

| Componente | Condición de activación | Penalización |
|---|---|---|
| $F_{bounds}$ | $H < H_{min}$ o $H > H_{max}$ | 1.0 (veto físico) |
| $F_{spike}$ | $|\Delta H / \Delta t| > \text{SPIKE\_THRESH}$ | 0.5 |
| $F_{flat}$ | $K \geq 8$ obs consecutivas idénticas | 0.2 |

Cuando $S_f = 0.0$, se activa automáticamente `CRITICAL_FLAG` independientemente de los demás sub-scores.

### 4.2 Sub-score de integridad lógica S_l

$S_l$ evalúa la coherencia interna de la serie temporal mediante detección de gaps y análisis de continuidad en ventanas rodantes de 24 horas.

$$S_l = \text{clamp}_{[0,1]}\left(1 - F_{gap24} - F_{gap\_consec}\right)$$

| Componente | Condición | Penalización |
|---|---|---|
| $F_{gap24}$ (warn) | Gap en ventana 24h $\geq$ 10% | 0.2 |
| $F_{gap24}$ (fail) | Gap en ventana 24h $\geq$ 30% | 0.5 |
| $F_{gap\_consec}$ | Gaps consecutivos detectados | Variable |

### 4.3 Sub-score de integridad temporal S_t

$S_t$ evalúa la puntualidad de la transmisión respecto al intervalo nominal SAIH.

$$S_t = f(\text{latencia observada}, \text{breakpoints de latencia})$$

La función es lineal por tramos definida por los breakpoints $[60s, 300s, 900s]$ con scores $[1.0, 0.7, 0.4, 0.1]$. Cuando $S_t < 0.1$, se activa `CRITICAL_FLAG`.

### 4.4 Sub-score de integridad histórica S_h

$S_h$ evalúa la coherencia del valor observado respecto al comportamiento histórico del sensor en ventanas temporales múltiples.

$$S_h = \text{clamp}_{[0,1]}\left(1 - F_{drift} - F_{hist}\right)$$

$F_{drift}$ aplica el detector EWMA/CUSUM sobre la deriva normalizada $|EMA_{6h} - EMA_{24h}| / \sigma_{24h}$, activándose cuando supera `DRIFT_THRESH = 3.0`.

### 4.5 CRITICAL_FLAG y régimen de veto

`CRITICAL_FLAG` se activa cuando se cumple alguna de las siguientes condiciones, con independencia del valor de $S_c$:

| Condición | Causa |
|---|---|
| $S_f = 0.0$ | Valor físicamente imposible |
| $S_t < 0.10$ | Fallo temporal severo |
| Flatline $\geq 48h$ activo | WMO-No.168 |
| $S_f = 0$ AND $C_{PH}$ activo | Doble evidencia de fallo físico |

Cuando `CRITICAL_FLAG = True`, el régimen se fuerza a `VETADA` independientemente de $S_c$.

### 4.6 Clasificación de régimen

| Régimen | Condición | Interpretación |
|---|---|---|
| `CERTIFICADA` | $S_c \geq 0.85$ AND NOT `CRITICAL_FLAG` | Observación íntegra para uso operacional |
| `DEGRADADA` | $0.50 \leq S_c < 0.85$ AND NOT `CRITICAL_FLAG` | Observación utilizable con precaución |
| `VETADA` | $S_c < 0.50$ OR `CRITICAL_FLAG` | Observación no utilizable; registrar y descartar |

---

## 5. Pipeline de procesamiento

El pipeline completo de KAIRI-SIO sigue la secuencia: **Ingesta → Scoring → Veto → Validación**.

### 5.1 Ingesta — CHG Guadalquivir

Lee los XLSX del SAIH Guadalquivir, normaliza al Data Contract v1.1 y genera parquets curados.

```powershell
# Ingestar todos los embalses CHG
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py

# Ingestar un embalse específico
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py --embalse E32_VADOMOJON
```

**Data Contract v1.1** — columnas requeridas en `data/curated/`:

| Columna | Tipo | Descripción |
|---|---|---|
| `uuid` | str | Identificador único de observación |
| `sensor_id` | str | Identificador del sensor |
| `ts_station` | datetime | Timestamp de la estación |
| `ts_ingest` | datetime | Timestamp de ingesta en KAIRI |
| `H_level` | float | Nivel del embalse (m) |
| `Q_inflow` | float | Caudal de entrada (m³/s) |
| `P_rain` | float | Precipitación (mm) |

### 5.2 Ingesta — CHE Ebro

Lee los CSV del SAIH Ebro (formato `sep=;`, columna `VALOR (msnm)`), normaliza y genera parquets en `data/curated/ebro/`.

```powershell
# Ingestar todos los embalses Ebro
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all

# Ingestar un embalse específico
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse ITOIZ
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse MEQUINENZA
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse YESA
```

### 5.3 Scoring — CHG

Calcula $S_c$ para los embalses del Guadalquivir y guarda parquets scored en `data/analytic/`.

```powershell
# Scoring completo CHG (modo estándar)
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py

# Scoring con sub-scores detallados (incluye S_f, S_l, S_t, S_h y componentes)
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed

# Scoring de un embalse específico
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --embalse E32_VADOMOJON

# Scoring con rutas personalizadas
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --curated data/curated --analytic data/analytic
```

### 5.4 Scoring — CHE

```powershell
# Scoring completo CHE con sub-scores detallados
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed

# Scoring de un embalse Ebro específico
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --embalse ITOIZ
```

### 5.5 Veto

Aplica las reglas de veto y genera el registro de decisiones con `CRITICAL_FLAG`.

```powershell
# Aplicar veto sobre los scored de CHG
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py

# Aplicar veto sobre CHE
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE
```

### 5.6 Validación — Sprint 5 (CHG)

Construye el ground truth a partir de los errores conocidos y calcula recall/precision.

```powershell
# Construir ground truth
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py

# Ejecutar validación completa
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py
```

Output en `output/validation/`:
- `validation_report.txt` — resumen de recall/precision por tipo de error
- `validation_detail.parquet` — detalle observación a observación
- `ground_truth.parquet` — dataset de referencia

### 5.7 Experimento intercuencas

Valida la generalización del modelo a la cuenca del Ebro.

```powershell
# Ejecutar experimento completo (requiere scored parquets de CHG y CHE)
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py
```

Output en `output/validation/`:
- `intercuencas_report.csv` — distribución S_c por embalse y cuenca
- `intercuencas_summary.txt` — resumen con KS test
- `intercuencas_sc_distribution.png` — gráfico comparativo

---

## 6. Configuración multiconfederación

La configuración por confederación se gestiona mediante archivos YAML en `src/config/confederations/`. Cada archivo define pesos, umbrales, parámetros de latencia/flatline/deriva y bounds físicos por embalse.

### 6.1 Estructura del YAML de confederación

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
  warn: 0.10  # WMO-No.168: 90% completitud
  fail: 0.30  # WMO-No.168: 70% completitud

flatline:
  k_hours:        8   # Nelson 1984, ISO 7870-2:2013
  critical_hours: 48  # WMO-No.168

drift:
  threshold: 3.0  # UCL percentil empírico, Page 1954

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

### 6.2 Confederaciones disponibles

```powershell
# Listar confederaciones disponibles
(.venv) PS C:\KAIRI-SIO> python -c "
from src.config.confederation_config import list_available_confederations
for c in list_available_confederations():
    print(c)
"
```

| Código | Confederación | Estado |
|---|---|---|
| `CHG` | Hidrográfica del Guadalquivir | `production` |
| `CHE` | Hidrográfica del Ebro | `pilot` |
| `CHD` | Hidrográfica del Duero | `placeholder` |
| `CHT` | Hidrográfica del Tajo | `placeholder` |

---

## 7. API REST

La API REST permite integración con sistemas externos y scoring en tiempo real de observaciones individuales o series temporales.

### 7.1 Arranque del servidor

```powershell
# Servidor de desarrollo (recarga automática)
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000

# Servidor de producción
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Documentación interactiva Swagger UI
# → http://localhost:8000/docs
```

### 7.2 Endpoints disponibles

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del servicio + confederaciones disponibles |
| `GET` | `/confederations` | Lista todas las confederaciones |
| `GET` | `/confederations/{code}` | Detalle de una confederación |
| `POST` | `/score/observation` | Scoring de una observación individual |
| `POST` | `/score/batch` | Scoring de serie temporal (máx 10,000 obs) |

### 7.3 Ejemplo de uso

```bash
# Health check
curl http://localhost:8000/health

# Scoring de observación individual
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

**Respuesta:**
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

## 8. Dashboard de monitorización

El dashboard proporciona visualización interactiva del estado de integridad de los embalses monitorizados.

### 8.1 Arranque

```powershell
# Arrancar dashboard (modo local)
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py

# Arrancar en puerto específico
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py --server.port 8501
```

El dashboard abrirá automáticamente en `http://localhost:8501`.

### 8.2 Vistas disponibles

| Vista | Descripción |
|---|---|
| **KPIs** | Total observaciones, % CERT/VETADA, # CRITICAL_FLAG, S_c medio |
| **Distribución regímenes** | Barras apiladas CERT/DEGR/VETADA por embalse + S_c medio |
| **Serie temporal S_c** | S_c resampleable (diaria/semanal/mensual/trimestral) con umbrales |
| **Mapa de calor sub-scores** | S_f · S_l · S_t · S_h · S_c medios, escala RdYlGn |
| **CRITICAL_FLAG** | Tabla filtrable de eventos críticos con métricas por embalse |
| **Recall Sprint 5** | Validación contra ground truth CHG (solo CHG) |
| **Intercuencas** | KDE comparativo CHG vs CHE (solo modo "Ambas") |
| **AEMET** | Observaciones en tiempo real (toggle en sidebar, TTL 5 min) |

### 8.3 Selector de confederación

El sidebar permite seleccionar `CHG · Guadalquivir`, `CHE · Ebro`, o `Ambas`. El rango de fechas se ajusta automáticamente según la selección. En modo `Ambas` se activa la vista de comparación intercuencas.

---

## 9. Conector AEMET

El conector AEMET OpenData integra observaciones meteorológicas en tiempo real de las estaciones más cercanas a cada embalse.

### 9.1 Configuración

Añadir la API key en `.env` (registro gratuito en `opendata.aemet.es`):

```
AEMET_API_KEY=tu_api_key_jwt
```

### 9.2 Uso

```powershell
# Obtener observaciones de todos los embalses
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs

# Obtener observación de un embalse específico
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs --embalse ITOIZ

# Obtener avisos CAP activos (alertas meteorológicas)
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode avisos

# Modo completo (observaciones + avisos)
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all

# Inventario de estaciones AEMET disponibles
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode inventario
```

### 9.3 Variables obtenidas

| Variable | Unidad | Uso en KAIRI-SIO |
|---|---|---|
| Precipitación | mm/15min | Enriquecimiento S_h, correlación lluvia↔nivel |
| Temperatura | °C | Contexto para análisis de evaporación |
| Viento | m/s | Contexto para anomalías de presión |
| Avisos CAP | nivel rojo/naranja | Pre-flag preventivo en eventos extremos |

**Nota técnica:** La API AEMET OpenData requiere una doble llamada HTTP (la primera devuelve una URL, la segunda los datos reales). El rate limit es de 50 peticiones/minuto. El conector gestiona automáticamente ambos aspectos con un delay configurable (`RATE_LIMIT_DELAY = 2.0s`).

---

## 10. Validación intercuencas

### 10.1 Resultados del experimento (2026-03-13)

El experimento valida la hipótesis de generalización del modelo: los parámetros derivados de fundamentación física universal operan correctamente en una cuenca no vista durante el desarrollo, sin recalibración.

**Dataset:** CHG (2015–2024, 260,841 obs) + CHE (2025–2026, 105,017 obs) = 365,858 observaciones totales.

**Resultados Test 1 — Distribución S_c:**

| Cuenca | Embalse | S_c medio | CERT% | DEGR% | VETO% |
|---|---|---|---|---|---|
| CHG | E32 Vado Mojón | 0.9014 | 61.5% | 38.5% | 0.01% |
| CHG | E33 Sierra Boyera | 0.8871 | 54.2% | 45.8% | 0.01% |
| CHG | E37 Bembézar | 0.8876 | 54.2% | 45.8% | 0.01% |
| CHE | Itoiz | 0.8007 | 71.9% | 28.1% | 0.00% |
| CHE | Mequinenza | 0.8124 | 75.2% | 24.8% | 0.00% |
| CHE | **Yesa** | **0.9102** | 69.3% | 30.7% | 0.00% |

Yesa (CHE) obtiene el S_c medio más alto de todos los embalses analizados, demostrando que el modelo no está sesgado hacia la cuenca de calibración.

**Resultados Test 2 — Detección flatlines:** $S_f = 1.000$ en todos los embalses de ambas cuencas. Ningún flatline detectado — resultado esperado para datasets curados sin anomalías de sensor conocidas en los períodos analizados.

**Resultados Test 3 — Kolmogorov-Smirnov:** $KS = 0.333$, $p \approx 0$. Con $n = 365,858$ el test KS tiene potencia estadística extrema. La diferencia operacional $\Delta\mu = 0.051$ entre cuencas es explicable por la diferencia en longitud de serie histórica (9 años CHG vs 1 año CHE), que afecta la componente $S_h$.

**Conclusión:** Hipótesis confirmada. KAIRI-SIO opera correctamente en CHE sin recalibración, adaptándose únicamente los bounds físicos $H_{level}$ específicos de cada presa.

---

## 11. Referencia de comandos

### 11.1 Secuencia completa de ejecución

```powershell
# ── 1. INGESTA CHG ────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py

# ── 2. INGESTA CHE ────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all

# ── 3. SCORING CHG ───────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed

# ── 4. SCORING CHE ───────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed

# ── 5. VETO ──────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE

# ── 6. VALIDACIÓN ────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py

# ── 7. EXPERIMENTO INTERCUENCAS ───────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py

# ── 8. API REST ───────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000

# ── 9. DASHBOARD ─────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py

# ── 10. AEMET ────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all
```

### 11.2 Referencia rápida por módulo

```powershell
# ── INGESTA ───────────────────────────────────────────────────────────────────
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

# ── VALIDACIÓN ────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py

# ── API ───────────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# ── DASHBOARD ─────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py --server.port 8501

# ── UTILIDADES ────────────────────────────────────────────────────────────────
# Árbol del proyecto
(.venv) PS C:\KAIRI-SIO> python kairi_tree.py

# Verificar configuración de confederación
(.venv) PS C:\KAIRI-SIO> python -c "
from src.config.confederation_config import load_confederation_config
cfg = load_confederation_config('CHG')
print(cfg)
"
```

### 11.3 Instalación de dependencias

```powershell
# Dependencias del pipeline principal
(.venv) PS C:\KAIRI-SIO> pip install -r requirements.txt

# Dependencias adicionales para API + Dashboard
(.venv) PS C:\KAIRI-SIO> pip install -r requirements_api.txt

# Dependencia adicional para el experimento intercuencas
(.venv) PS C:\KAIRI-SIO> pip install scipy

# Dependencias AEMET
(.venv) PS C:\KAIRI-SIO> pip install python-dotenv requests
```

---

## 12. Estructura del proyecto

```
C:\KAIRI-SIO\
│
├── .env                          ← Variables de entorno (AEMET_API_KEY)
├── dashboard.py                  ← Dashboard Streamlit v2.0
├── kairi_tree.py                 ← Utilidad árbol del proyecto
├── requirements.txt              ← Dependencias pipeline
├── requirements_api.txt          ← Dependencias API + Dashboard
│
├── 03_Datos_Fuentes_Oficiales\   ← INTOCABLE — fuentes oficiales MITECO
│   ├── Caumax_Nacional\          ← Plugin QGIS caudales máximos CEDEX
│   ├── MDT\                      ← Modelos Digitales del Terreno
│   └── SNCZI_Cartografia\        ← Zonas inundables T10/T100/T500
│       ├── Ebro\                 ← Datos SAIH Ebro (Itoiz, Mequinenza, Yesa)
│       └── guadalquivir\         ← Datos SAIH Guadalquivir (E32, E33, E37)
│
├── data\
│   ├── raw\                      ← Datos crudos (parquets sin transformar)
│   │   ├── saih_ebro\            ← Raw Ebro generado por saih_ebro_reader
│   │   ├── saih_guadalquivir\    ← XLSX originales CHG
│   │   ├── aemet\                ← Observaciones AEMET
│   │   └── cartografia_snczi\   ← Shapefiles SNCZI T10/T100/T500
│   ├── curated\                  ← Data Contract v1.1 (parquets normalizados)
│   │   └── ebro\                 ← Curated CHE
│   └── analytic\                 ← Parquets scored con S_c, quality_flag
│       └── ebro\                 ← Analytic CHE
│
├── src\
│   ├── api\                      ← API REST FastAPI
│   │   ├── main.py
│   │   └── schemas.py
│   ├── config\                   ← Configuración multiconfederación
│   │   ├── confederation_config.py
│   │   ├── sensor_config.py
│   │   └── confederations\
│   │       ├── CHG.yaml          ← Producción
│   │       ├── CHE.yaml          ← Piloto
│   │       ├── CHD.yaml          ← Placeholder
│   │       └── CHT.yaml          ← Placeholder
│   ├── forensics\                ← Registro forense JSONL
│   │   └── forensic_logger.py
│   ├── ingestion\                ← Lectores e ingesta
│   │   ├── saih_reader.py        ← CHG (XLSX)
│   │   ├── saih_ebro_reader.py   ← CHE (CSV sep=;)
│   │   ├── aemet_connector.py    ← AEMET OpenData REST
│   │   ├── normalizer.py
│   │   ├── validator.py
│   │   └── run_ingestion.py
│   ├── scoring\                  ← Modelo de scoring
│   │   ├── s_f.py                ← Sub-score físico
│   │   ├── s_l.py                ← Sub-score lógico
│   │   ├── s_t.py                ← Sub-score temporal
│   │   ├── s_h.py                ← Sub-score histórico
│   │   ├── scorer.py             ← Orquestador S_c
│   │   └── run_scoring.py        ← CLI multiconfederación
│   ├── validation\               ← Validación y métricas
│   │   ├── ground_truth_builder.py
│   │   └── run_validation.py
│   └── veto\                     ← Motor de decisión
│       ├── decision_engine.py
│       └── run_veto.py
│
├── notebooks\
│   ├── mvp_demo\
│   │   └── kairi_sio_demo.py
│   └── validacion\
│       └── kairi_sio_intercuencas.py  ← Experimento intercuencas
│
├── output\
│   ├── demo\                     ← Gráficos demo MVP
│   ├── forensics\                ← Registros JSONL forenses
│   ├── reports\                  ← Informes generados
│   └── validation\               ← Resultados de validación
│
└── docs\
    ├── arquitectura\             ← Documentación técnica
    ├── modelo_matematico\        ← PDFs fundamentación matemática
    └── regulatorio\              ← Normas WMO, GUM, ISO referenciadas
```

---

## Referencias

| Referencia | Uso en KAIRI-SIO |
|---|---|
| Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill. | Pesos AHP del modelo compuesto S_c |
| JCGM 100:2008. *Guide to the Expression of Uncertainty in Measurement* (GUM). | Umbrales de clasificación VETADA/CERTIFICADA |
| Nelson, L.S. (1984). The Shewhart Control Chart — Tests for Special Causes. *Journal of Quality Technology*, 16(4), 237–239. | FLATLINE_K = 8h |
| ISO 7870-2:2013. *Control Charts — Part 2: Shewhart Control Charts*. | FLATLINE_K = 8h |
| WMO-No.168. *Guide to Hydrological Practices*, Vol. I, Cap. 2. | FLAT_CRITICAL_H = 48h, GAP_WARN/FAIL |
| WMO-No.8. *Guide to Meteorological Instruments and Methods of Observation*, Cap. 1. | GAP_WARN/FAIL |
| Page, E.S. (1954). Continuous Inspection Schemes. *Biometrika*, 41(1/2), 100–115. | DRIFT_THRESH (detector CUSUM) |
| Lucas, J.M. & Saccucci, M.S. (1990). Exponentially Weighted Moving Average Control Schemes. *Technometrics*, 32(1), 1–12. | DRIFT_THRESH (detector EWMA) |
| Montgomery, D.C. (2012). *Introduction to Statistical Quality Control*, 7ª ed. Wiley. | Marco general SPC |

---

*KAIRI-SIO v1.1.0 · Reymar (especificación matemática) · Kent Valera Chirinos (implementación técnica) · 2026-03-13*
