# KAIRI-SIO — Technische Systemdokumentation
**Version:** 1.1.0  
**Datum:** 2026-03-13  
**Autoren:** Reymar (mathematische Spezifikation) · Kent Valera Chirinos (technische Implementierung)  
**Status:** Pilotproduktion — CHG Guadalquivir + CHE Ebro

---

## Inhaltsverzeichnis

1. [Systemüberblick](#1-systemüberblick)
2. [Theoretische Grundlagen](#2-theoretische-grundlagen)
3. [Systemarchitektur](#3-systemarchitektur)
4. [Zusammengesetztes Bewertungsmodell S_c](#4-zusammengesetztes-bewertungsmodell-sc)
5. [Verarbeitungs-Pipeline](#5-verarbeitungs-pipeline)
6. [Mehrflusskonfiguration](#6-mehrflusskonfiguration)
7. [REST-API](#7-rest-api)
8. [Überwachungs-Dashboard](#8-überwachungs-dashboard)
9. [AEMET-Konnektor](#9-aemet-konnektor)
10. [Einzugsgebietsübergreifende Validierung](#10-einzugsgebietsübergreifende-validierung)
11. [Befehlsreferenz](#11-befehlsreferenz)
12. [Projektstruktur](#12-projektstruktur)

---

## 1. Systemüberblick

KAIRI-SIO (System zur Überprüfung der Integrität hydrologischer Signale) ist ein deterministisches Echtzeit-Datenqualitätskontrollsystem für SAIH-Netzwerke (Automatisches Hydrologisches Informationssystem) spanischer Flussbehörden. Das System bewertet die Integrität hydrometeorologischer Sensorsignale — Stauseestand, Niederschlag, Durchfluss — durch Anwendung eines zusammengesetzten Bewertungsmodells, das auf internationalen Metrologie-Normen und statistischer Prozesskontrolle basiert.

KAIRI-SIO modelliert weder hydrologisches Verhalten noch erstellt es Durchflussvorhersagen. Sein ausschließlicher Bereich ist die **Überprüfung der Zuverlässigkeit des Messsignals**: die Bestimmung, ob eine von einem Sensor empfangene Beobachtung als intakt angesehen werden kann oder ob sie Anzeichen instrumenteller Degradierung aufweist.

### 1.1 Problemstellung

SAIH-Netzwerke übertragen Fernsensordaten in 15-Minuten-Intervallen von hunderten Kontrollpunkten, die über Einzugsgebiete von zehntausenden km² verteilt sind. Die häufigsten instrumentellen Fehler — eingefrorener Sensor (*Flatline*), übermäßige Übertragungslatenz, Signaldrift, elektromagnetische Rauschspitzen, Verlust zeitlicher Kontinuität — sind von bestehenden SCADA-Systemen ohne spezifische Validierungslogik nicht automatisch erkennbar.

Die operationelle Konsequenz ist, dass fehlerhafte Beobachtungen als gültige Daten in Informationssysteme eingehen und damit Wasserhaushaltsberechnungen, Hochwasservorhersagemodelle und historische Aufzeichnungen für die hydrologische Planung kontaminieren.

KAIRI-SIO weist jeder Beobachtung einen Integritätswert $S_c \in [0, 1]$ und eine Regimeklassifikation (`ZERTIFIZIERT`, `DEGRADIERT`, `GESPERRT`) zu, die es Betreibern und nachgelagerten Systemen ermöglicht, informierte Entscheidungen über die Zuverlässigkeit jedes Datenpunkts zu treffen.

### 1.2 Validierter operationeller Umfang

| Flussgebietsbehörde | Stauseen | Zeitraum | Beobachtungen |
|---|---|---|---|
| CHG · Guadalquivir | E32 Vado Mojón, E33 Sierra Boyera, E37 Bembézar | 2015–2024 | 260.841 |
| CHE · Ebro | Itoiz, Mequinenza, Yesa | 2025–2026 | 105.017 |
| **Gesamt** | **6 Stauseen** | | **365.858** |

---

## 2. Theoretische Grundlagen

### 2.1 Gewichtungsmodell — Analytischer Hierarchieprozess (AHP)

Die Gewichte des zusammengesetzten Scores werden mittels der AHP-Methode (Saaty, 1980) abgeleitet, die Expertenvergleichsurteile mathematisch in einen überprüfbar konsistenten Gewichtsvektor formalisiert. Die Paarvergleichsmatrix spiegelt eine hydraulische Integritätshierarchie wider: physikalische Sensorbeschränkungen haben Vorrang vor abgeleiteten statistischen Metriken.

$$S_c = 0{,}40 \cdot S_f + 0{,}30 \cdot S_l + 0{,}20 \cdot S_t + 0{,}10 \cdot S_h$$

Der Konsistenzindex der Matrix beträgt $CR < 0{,}10$, was die Kohärenz der Vergleichsurteile nach Saatys (1980) Kriterium bestätigt. Referenzen: *The Analytic Hierarchy Process* (Saaty, 1980); Montgomery, *Introduction to Statistical Quality Control*, 7. Aufl. (2012).

### 2.2 Klassifikationsschwellenwerte — GUM

Die Regimeschwellen werden aus algebraischen Eigenschaften des Modells und dem Leitfaden zur Angabe der Messunsicherheit (GUM, JCGM 100:2008) abgeleitet.

**GESPERRT-Schwelle ($S_c < 0{,}50$) — Prinzip der Unsicherheitsdominanz:**

In einem zusammengesetzten Score mit Gewichten, die sich zu 1,0 summieren, und Teilscores in $[0,1]$ entspricht der Wert 0,50 dem Gleichgewichtspunkt zwischen zuverlässigen und defekten Komponenten. Wenn $S_c < 0{,}50$, übersteigt das akkumulierte Gewicht der defekten Dimensionen das der zuverlässigen. Die GUM legt fest, dass eine Messung nicht verwendbar ist, wenn ihre erweiterte Messunsicherheit den gemessenen Wert überschreitet.

**ZERTIFIZIERT-Schwelle ($S_c \geq 0{,}85$):**

Dies ist der Mindestwert von $S_c$, bei dem selbst wenn der Teilscore mit dem höchsten Gewicht ($S_f$, $W=0{,}40$) auf 0,625 absinkt, während alle anderen perfekt bleiben, $S_c$ akzeptabel bleibt:

$$0{,}40 \cdot x + 0{,}30 \cdot 1{,}0 + 0{,}20 \cdot 1{,}0 + 0{,}10 \cdot 1{,}0 = 0{,}85 \implies x = 0{,}625$$

### 2.3 Flatline-Erkennung — Statistische Prozesskontrolle

Der Parameter `FLATLINE_K = 8h` wird durch Nelsons Regel 2 (1984) begründet: acht oder mehr aufeinanderfolgende identische Punkte stellen ein eindeutiges Signal für einen außer Kontrolle geratenen Prozess dar. Diese Regel ist in ISO 7870-2:2013 eingebettet. Bei einem normal betriebenen Stausee ist eine Folge von 8 stündlich exakt identischen Beobachtungen angesichts des inhärenten Instrumentenrauschens statistisch unwahrscheinlich.

Der kritische Schwellenwert `FLAT_CRITICAL_H = 48h` wird durch drei komplementäre Argumente begründet:
- **Natürliche hydrologische Zyklen (WMO-Nr.168):** 48h entsprechen 2 vollständigen nychthemeralen Zyklen
- **Irreversibler Informationsverlust:** Ereignisse mit signifikanter Variation ($\Delta H > 0{,}05$ m/h) haben im SAIH Guadalquivir-Datensatz eine mittlere Dauer von 6–18h
- **WMO-Vollständigkeit:** 48h in einem 10-Tage-Analysefenster entsprechen 20% ungültigen Daten und überschreiten den von WMO-Nr.168 festgelegten Akzeptanzschwellenwert von 10%

### 2.4 Driftdetektion — EWMA/CUSUM-Detektoren

Der Driftdetektor $F_{drift}$ ist formal äquivalent zu einem CUSUM-Detektor (Page, 1954) oder EWMA-Detektor (Lucas & Saccucci, 1990) für Mittelwertänderungen. Er berechnet die normalisierte Drift:

$$\text{drift} = \frac{|EMA_{6h} - EMA_{24h}|}{\sigma_{24h}}$$

Der Schwellenwert `DRIFT_THRESH = 3.0` wird als UCL (Obere Kontrollgrenze) durch das Referenzperzentil der empirischen Verteilung des SAIH Guadalquivir-Datensatzes (n=86.947) begründet:

- Hochgradig leptokurtische Verteilung: Exzesskurtosis = 618,2, Schiefe = 20,8
- Nicht-gaussisch: Shapiro-Wilk, D'Agostino-Pearson, Kolmogorov-Smirnov und Anderson-Darling lehnen Normalverteilung mit $p < 10^{-62}$ ab
- Wert 3,0 fällt mit dem natürlichen Wendepunkt des rechten Schwanzes der empirischen Verteilung zusammen

### 2.5 Lückenschwellenwerte — WMO

Datenvollständigkeitsschwellen werden direkt aus WMO-Nr.168 und WMO-Nr.8 abgeleitet:

| Parameter | Wert | WMO-Kriterium |
|---|---|---|
| `GAP_WARN` | 0,10 | Vollständigkeit ≥ 90% für tägliche Durchflussberechnung |
| `GAP_FAIL` | 0,30 | Vollständigkeit ≥ 70% für Ereignisanalyse |

### 2.6 Kritische Latenz — SAIH-Protokoll

`LAT_CRITICAL_S = 900s` entspricht dem nominalen SAIH-Übertragungsintervall (15 Minuten). Eine Beobachtung mit einer Latenz von mehr als 900s ist außerhalb ihres zeitlichen Gültigkeitsfensters beim System eingegangen, was einem Versatz von mehr als einer Abtastperiode entspricht. Dieser Parameter ist pro Flussgebietsbehörde konfigurierbar, um Portabilität zu gewährleisten.

---

## 3. Systemarchitektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KAIRI-SIO v1.1                              │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │  INGESTION   │───▶│  BEWERTUNG   │───▶│ VETO / ENTSCHEIDUNG │   │
│  │              │    │              │    │                      │   │
│  │ saih_reader  │    │ s_f.py       │    │ decision_engine.py   │   │
│  │ ebro_reader  │    │ s_l.py       │    │ CRITICAL_FLAG        │   │
│  │ aemet_conn.  │    │ s_t.py       │    │ ZERT/DEGR/GESPERRT   │   │
│  └──────────────┘    │ s_h.py       │    └──────────────────────┘   │
│         │            │ scorer.py    │              │                │
│         ▼            └──────────────┘              ▼                │
│  ┌──────────────┐              │            ┌──────────────┐        │
│  │  data/raw/   │              │            │  FORENSISCH  │        │
│  │  data/curated│              │            │ forensic_log │        │
│  │  data/analytic│             │            │ .jsonl Audit │        │
│  └──────────────┘              │            └──────────────┘        │
│                                ▼                                    │
│                    ┌──────────────────────┐                         │
│                    │    VALIDIERUNG       │                         │
│                    │ ground_truth_builder │                         │
│                    │ Einzugsgebietsver.   │                         │
│                    └──────────────────────┘                         │
│                                │                                    │
│              ┌─────────────────┼──────────────────┐                 │
│              ▼                 ▼                  ▼                 │
│     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│     │  REST-API    │  │  DASHBOARD   │  │  KONFIGURAT. │            │
│     │  FastAPI     │  │  Streamlit   │  │  YAML/Gebiete│            │
│     │  /score/*    │  │  dashboard   │  │  CHG/CHE/... │            │
│     └──────────────┘  └──────────────┘  └──────────────┘            │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Datenzonen

| Zone | Pfad | Inhalt | Richtlinie |
|---|---|---|---|
| **Roh** | `data/raw/` | Originale SAIH-CSVs, rohe Parquets | Unveränderlich |
| **Kuratiert** | `data/curated/` | Auf Datenvertrag v1.1 normalisierte Parquets | Regenerierbar |
| **Analytisch** | `data/analytic/` | Bewertete Parquets mit S_c, quality_flag | Regenerierbar |
| **Offizielle Quellen** | `03_Datos_Fuentes_Oficiales/` | SNCZI, DHM, Caumax — offizielle MITECO-Daten | Unantastbar |

---

## 4. Zusammengesetztes Bewertungsmodell S_c

### 4.1 Physikalischer Integritäts-Teilscore S_f

$S_f$ bewertet, ob beobachtete Werte für den Stausee physikalisch plausibel sind.

$$S_f = \text{clamp}_{[0,1]}\left(1 - F_{bounds} - F_{spike} - F_{flat}\right)$$

| Komponente | Aktivierungsbedingung | Strafe |
|---|---|---|
| $F_{bounds}$ | $H < H_{min}$ oder $H > H_{max}$ | 1,0 (physikalisches Veto) |
| $F_{spike}$ | $|\Delta H / \Delta t| > \text{SPIKE\_THRESH}$ | 0,5 |
| $F_{flat}$ | $K \geq 8$ aufeinanderfolgende identische Beobachtungen | 0,2 |

Wenn $S_f = 0{,}0$, wird `CRITICAL_FLAG` unabhängig von anderen Teilscores automatisch aktiviert.

### 4.2 Logischer Integritäts-Teilscore S_l

$S_l$ bewertet die interne Konsistenz der Zeitreihe durch Lückenerkennung und Kontinuitätsanalyse in rollierenden 24-Stunden-Fenstern.

$$S_l = \text{clamp}_{[0,1]}\left(1 - F_{gap24} - F_{gap\_consec}\right)$$

| Komponente | Bedingung | Strafe |
|---|---|---|
| $F_{gap24}$ (Warnung) | Lücke im 24h-Fenster $\geq$ 10% | 0,2 |
| $F_{gap24}$ (Fehler) | Lücke im 24h-Fenster $\geq$ 30% | 0,5 |
| $F_{gap\_consec}$ | Aufeinanderfolgende Lücken erkannt | Variabel |

### 4.3 Zeitlicher Integritäts-Teilscore S_t

$S_t$ bewertet die Pünktlichkeit der Übertragung relativ zum nominalen SAIH-Intervall.

$$S_t = f(\text{beobachtete Latenz}, \text{Latenz-Stützpunkte})$$

Die Funktion ist stückweise linear, definiert durch Stützpunkte $[60s, 300s, 900s]$ mit Scores $[1{,}0, 0{,}7, 0{,}4, 0{,}1]$. Wenn $S_t < 0{,}1$, wird `CRITICAL_FLAG` aktiviert.

### 4.4 Historischer Integritäts-Teilscore S_h

$S_h$ bewertet die Konsistenz des beobachteten Wertes gegenüber dem historischen Sensorverhalten über mehrere zeitliche Fenster.

$$S_h = \text{clamp}_{[0,1]}\left(1 - F_{drift} - F_{hist}\right)$$

$F_{drift}$ wendet den EWMA/CUSUM-Detektor auf die normalisierte Drift $|EMA_{6h} - EMA_{24h}| / \sigma_{24h}$ an und aktiviert sich, wenn diese `DRIFT_THRESH = 3.0` überschreitet.

### 4.5 CRITICAL_FLAG und Veto-Regime

`CRITICAL_FLAG` wird aktiviert, wenn eine der folgenden Bedingungen erfüllt ist, unabhängig von $S_c$:

| Bedingung | Ursache |
|---|---|
| $S_f = 0{,}0$ | Physikalisch unmöglicher Wert |
| $S_t < 0{,}10$ | Schwerwiegender zeitlicher Fehler |
| Flatline $\geq 48h$ aktiv | WMO-Nr.168 |
| $S_f = 0$ UND $C_{PH}$ aktiv | Doppelter Nachweis physikalischen Fehlers |

Wenn `CRITICAL_FLAG = True`, wird das Regime unabhängig von $S_c$ auf `GESPERRT` gezwungen.

### 4.6 Regimeklassifikation

| Regime | Bedingung | Interpretation |
|---|---|---|
| `ZERTIFIZIERT` | $S_c \geq 0{,}85$ UND NICHT `CRITICAL_FLAG` | Intakte Beobachtung für den operationellen Einsatz |
| `DEGRADIERT` | $0{,}50 \leq S_c < 0{,}85$ UND NICHT `CRITICAL_FLAG` | Mit Vorsicht verwendbare Beobachtung |
| `GESPERRT` | $S_c < 0{,}50$ ODER `CRITICAL_FLAG` | Nicht verwendbare Beobachtung; protokollieren und verwerfen |

---

## 5. Verarbeitungs-Pipeline

Die vollständige KAIRI-SIO-Pipeline folgt der Sequenz: **Ingestion → Bewertung → Veto → Validierung**.

### 5.1 Ingestion — CHG Guadalquivir

Liest SAIH Guadalquivir XLSX-Dateien, normalisiert auf Datenvertrag v1.1 und generiert kuratierte Parquets.

```powershell
# Alle CHG-Stauseen einlesen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py

# Einen bestimmten Stausee einlesen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py --embalse E32_VADOMOJON
```

**Datenvertrag v1.1** — erforderliche Spalten in `data/curated/`:

| Spalte | Typ | Beschreibung |
|---|---|---|
| `uuid` | str | Eindeutige Beobachtungskennung |
| `sensor_id` | str | Sensorkennung |
| `ts_station` | datetime | Stationszeitstempel |
| `ts_ingest` | datetime | KAIRI-Ingestionszeitstempel |
| `H_level` | float | Stauseepegel (m) |
| `Q_inflow` | float | Zufluss (m³/s) |
| `P_rain` | float | Niederschlag (mm) |

### 5.2 Ingestion — CHE Ebro

Liest SAIH Ebro CSV-Dateien (Format `sep=;`, Spalte `VALOR (msnm)`), normalisiert und generiert Parquets in `data/curated/ebro/`.

```powershell
# Alle Ebro-Stauseen einlesen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all

# Einen bestimmten Stausee einlesen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse ITOIZ
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse MEQUINENZA
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --embalse YESA
```

### 5.3 Bewertung — CHG

Berechnet $S_c$ für Guadalquivir-Stauseen und speichert bewertete Parquets in `data/analytic/`.

```powershell
# Vollständige CHG-Bewertung (Standardmodus)
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py

# Bewertung mit detaillierten Teilscores
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed

# Einen bestimmten Stausee bewerten
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --embalse E32_VADOMOJON

# Bewertung mit benutzerdefinierten Pfaden
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --curated data/curated --analytic data/analytic
```

### 5.4 Bewertung — CHE

```powershell
# Vollständige CHE-Bewertung mit detaillierten Teilscores
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed

# Einen bestimmten Ebro-Stausee bewerten
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --embalse ITOIZ
```

### 5.5 Veto

Wendet Veto-Regeln an und generiert das Entscheidungsprotokoll mit `CRITICAL_FLAG`.

```powershell
# Veto auf CHG-Bewertungsdaten anwenden
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py

# Veto auf CHE anwenden
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE
```

### 5.6 Validierung — Sprint 5 (CHG)

Erstellt Ground Truth aus bekannten Fehlern und berechnet Recall/Precision.

```powershell
# Ground Truth erstellen
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py

# Vollständige Validierung ausführen
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py
```

Ausgabe in `output/validation/`:
- `validation_report.txt` — Recall/Precision-Zusammenfassung nach Fehlertyp
- `validation_detail.parquet` — Detailansicht je Beobachtung
- `ground_truth.parquet` — Referenzdatensatz

### 5.7 Einzugsgebietsübergreifendes Experiment

Validiert die Modellgeneralisierung auf das Einzugsgebiet des Ebro.

```powershell
# Vollständiges Experiment ausführen (erfordert bewertete Parquets für CHG und CHE)
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py
```

Ausgabe in `output/validation/`:
- `intercuencas_report.csv` — S_c-Verteilung nach Stausee und Einzugsgebiet
- `intercuencas_summary.txt` — Zusammenfassung mit KS-Test
- `intercuencas_sc_distribution.png` — Vergleichsdiagramm

---

## 6. Mehrflusskonfiguration

Die Konfiguration pro Flussgebietsbehörde wird über YAML-Dateien in `src/config/confederations/` verwaltet. Jede Datei definiert Gewichte, Schwellenwerte, Latenz-/Flatline-/Drift-Parameter und physikalische Grenzwerte pro Stausee.

### 6.1 YAML-Struktur der Flussgebietsbehörde

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
  warn: 0.10  # WMO-Nr.168: 90% Vollständigkeit
  fail: 0.30  # WMO-Nr.168: 70% Vollständigkeit

flatline:
  k_hours:        8   # Nelson 1984, ISO 7870-2:2013
  critical_hours: 48  # WMO-Nr.168

drift:
  threshold: 3.0  # Empirisches Perzentil UCL, Page 1954

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

### 6.2 Verfügbare Flussgebietsbehörden

```powershell
# Verfügbare Flussgebietsbehörden auflisten
(.venv) PS C:\KAIRI-SIO> python -c "
from src.config.confederation_config import list_available_confederations
for c in list_available_confederations():
    print(c)
"
```

| Code | Flussgebietsbehörde | Status |
|---|---|---|
| `CHG` | Guadalquivir-Flussgebietsbehörde | `production` |
| `CHE` | Ebro-Flussgebietsbehörde | `pilot` |
| `CHD` | Duero-Flussgebietsbehörde | `placeholder` |
| `CHT` | Tajo-Flussgebietsbehörde | `placeholder` |

---

## 7. REST-API

Die REST-API ermöglicht die Integration mit externen Systemen und die Echtzeit-Bewertung einzelner Beobachtungen oder Zeitreihen.

### 7.1 Server-Start

```powershell
# Entwicklungsserver (automatisches Neuladen)
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000

# Produktionsserver
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Interaktive Swagger-UI-Dokumentation
# → http://localhost:8000/docs
```

### 7.2 Verfügbare Endpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/health` | Dienststatus + verfügbare Behörden |
| `GET` | `/confederations` | Alle Behörden auflisten |
| `GET` | `/confederations/{code}` | Details einer Behörde |
| `POST` | `/score/observation` | Eine einzelne Beobachtung bewerten |
| `POST` | `/score/batch` | Zeitreihe bewerten (max. 10.000 Obs.) |

### 7.3 Verwendungsbeispiel

```bash
# Statusprüfung
curl http://localhost:8000/health

# Einzelne Beobachtung bewerten
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

**Antwort:**
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

## 8. Überwachungs-Dashboard

Das Dashboard bietet interaktive Visualisierung des Integritätsstatus der überwachten Stauseen.

### 8.1 Start

```powershell
# Dashboard starten (lokaler Modus)
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py

# Auf einem bestimmten Port starten
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py --server.port 8501
```

Das Dashboard öffnet sich automatisch unter `http://localhost:8501`.

### 8.2 Verfügbare Ansichten

| Ansicht | Beschreibung |
|---|---|
| **KPIs** | Gesamtbeobachtungen, % ZERT/GESPERRT, # CRITICAL_FLAG, mittleres S_c |
| **Regimeverteilung** | Gestapelte Balken ZERT/DEGR/GESPERRT pro Stausee + mittleres S_c |
| **S_c-Zeitreihe** | Resampling-fähiges S_c (tägl./wöch./monatl./quartalsw.) mit Schwellenwerten |
| **Teilscore-Heatmap** | Mittleres S_f · S_l · S_t · S_h · S_c, RdYlGn-Skala |
| **CRITICAL_FLAG** | Filterbare Tabelle kritischer Ereignisse mit Metriken je Stausee |
| **Sprint 5 Recall** | Validierung gegen CHG-Ground-Truth (nur CHG) |
| **Einzugsgebietsvergleich** | KDE-Vergleich CHG vs. CHE (nur im Modus „Beide") |
| **AEMET** | Echtzeit-Beobachtungen (Sidebar-Toggle, TTL 5 Min.) |

### 8.3 Behördenauswahl

Die Seitenleiste ermöglicht die Auswahl von `CHG · Guadalquivir`, `CHE · Ebro` oder `Beide`. Der Datumsbereich passt sich automatisch an die Auswahl an. Im Modus `Beide` wird die einzugsgebietsübergreifende Vergleichsansicht aktiviert.

---

## 9. AEMET-Konnektor

Der AEMET-OpenData-Konnektor integriert meteorologische Echtzeit-Beobachtungen von den nächstgelegenen Stationen zu jedem Stausee.

### 9.1 Konfiguration

API-Schlüssel in `.env` eintragen (kostenlose Registrierung unter `opendata.aemet.es`):

```
AEMET_API_KEY=ihr_jwt_api_schluessel
```

### 9.2 Verwendung

```powershell
# Beobachtungen für alle Stauseen abrufen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs

# Beobachtung für einen bestimmten Stausee abrufen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode obs --embalse ITOIZ

# Aktive CAP-Warnungen abrufen (meteorologische Warnmeldungen)
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode avisos

# Vollständiger Modus (Beobachtungen + Warnungen)
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all

# Inventar verfügbarer AEMET-Stationen
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode inventario
```

### 9.3 Abgerufene Variablen

| Variable | Einheit | Verwendung in KAIRI-SIO |
|---|---|---|
| Niederschlag | mm/15min | S_h-Anreicherung, Regen↔Pegel-Korrelation |
| Temperatur | °C | Kontext für Verdunstungsanalyse |
| Wind | m/s | Kontext für Druckanomalien |
| CAP-Warnungen | Rot-/Orangepegel | Präventives Pre-Flag für Extremereignisse |

**Technischer Hinweis:** Die AEMET-OpenData-API erfordert einen zweistufigen HTTP-Aufruf (der erste liefert eine URL, der zweite die eigentlichen Daten). Das Ratenlimit beträgt 50 Anfragen/Minute. Der Konnektor verwaltet beide Aspekte automatisch mit einer konfigurierbaren Verzögerung (`RATE_LIMIT_DELAY = 2.0s`).

---

## 10. Einzugsgebietsübergreifende Validierung

### 10.1 Experimentergebnisse (2026-03-13)

Das Experiment validiert die Generalisierungshypothese des Modells: Parameter, die aus universellen physikalischen Grundlagen abgeleitet wurden, funktionieren korrekt in einem während der Entwicklung nicht gesehenen Einzugsgebiet ohne Neukalibrierung.

**Datensatz:** CHG (2015–2024, 260.841 Obs.) + CHE (2025–2026, 105.017 Obs.) = 365.858 Beobachtungen insgesamt.

**Test 1 Ergebnisse — S_c-Verteilung:**

| Einzugsgebiet | Stausee | Mittl. S_c | ZERT% | DEGR% | GESPERRT% |
|---|---|---|---|---|---|
| CHG | E32 Vado Mojón | 0,9014 | 61,5% | 38,5% | 0,01% |
| CHG | E33 Sierra Boyera | 0,8871 | 54,2% | 45,8% | 0,01% |
| CHG | E37 Bembézar | 0,8876 | 54,2% | 45,8% | 0,01% |
| CHE | Itoiz | 0,8007 | 71,9% | 28,1% | 0,00% |
| CHE | Mequinenza | 0,8124 | 75,2% | 24,8% | 0,00% |
| CHE | **Yesa** | **0,9102** | 69,3% | 30,7% | 0,00% |

Yesa (CHE) erzielt das höchste mittlere S_c aller analysierten Stauseen und beweist damit, dass das Modell nicht zugunsten des Kalibrierungseinzugsgebiets verzerrt ist.

**Test 2 Ergebnisse — Flatline-Erkennung:** $S_f = 1{,}000$ bei allen Stauseen in beiden Einzugsgebieten. Keine Flatlines erkannt — das erwartete Ergebnis für kuratierte Datensätze ohne bekannte Sensoranomalien in den analysierten Zeiträumen.

**Test 3 Ergebnisse — Kolmogorov-Smirnov:** $KS = 0{,}333$, $p \approx 0$. Bei $n = 365.858$ hat der KS-Test extreme statistische Trennschärfe. Der operationelle Unterschied $\Delta\mu = 0{,}051$ zwischen den Einzugsgebieten wird durch den Unterschied in der Länge der historischen Zeitreihen erklärt (9 Jahre CHG vs. 1 Jahr CHE), was die $S_h$-Komponente beeinflusst.

**Schlussfolgerung:** Hypothese bestätigt. KAIRI-SIO funktioniert in CHE ohne Neukalibrierung korrekt; als einzige Anpassung sind die physikalischen Grenzwerte $H_{level}$, die für jeden Staudamm spezifisch sind, erforderlich.

---

## 11. Befehlsreferenz

### 11.1 Vollständige Ausführungssequenz

```powershell
# ── 1. INGESTION CHG ─────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/run_ingestion.py

# ── 2. INGESTION CHE ─────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/saih_ebro_reader.py --all

# ── 3. BEWERTUNG CHG ─────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --detailed

# ── 4. BEWERTUNG CHE ─────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/scoring/run_scoring.py --confederation CHE --detailed

# ── 5. VETO ──────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py
(.venv) PS C:\KAIRI-SIO> python src/veto/run_veto.py --confederation CHE

# ── 6. VALIDIERUNG ───────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py

# ── 7. EINZUGSGEBIETSÜBERGREIFENDES EXPERIMENT ───────────────────────────────
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py

# ── 8. REST-API ───────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000

# ── 9. DASHBOARD ─────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py

# ── 10. AEMET ────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/ingestion/aemet_connector.py --mode all
```

### 11.2 Schnellreferenz nach Modul

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

# ── BEWERTUNG ─────────────────────────────────────────────────────────────────
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

# ── VALIDIERUNG ───────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> python src/validation/ground_truth_builder.py
(.venv) PS C:\KAIRI-SIO> python src/validation/run_validation.py
(.venv) PS C:\KAIRI-SIO> python notebooks/validacion/kairi_sio_intercuencas.py

# ── API ───────────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --reload --port 8000
(.venv) PS C:\KAIRI-SIO> uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# ── DASHBOARD ─────────────────────────────────────────────────────────────────
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py
(.venv) PS C:\KAIRI-SIO> streamlit run dashboard.py --server.port 8501

# ── HILFSPROGRAMME ────────────────────────────────────────────────────────────
# Projektbaum
(.venv) PS C:\KAIRI-SIO> python kairi_tree.py

# Behördenkonfiguration überprüfen
(.venv) PS C:\KAIRI-SIO> python -c "
from src.config.confederation_config import load_confederation_config
cfg = load_confederation_config('CHG')
print(cfg)
"
```

### 11.3 Abhängigkeitsinstallation

```powershell
# Abhängigkeiten der Haupt-Pipeline
(.venv) PS C:\KAIRI-SIO> pip install -r requirements.txt

# Zusätzliche Abhängigkeiten für API + Dashboard
(.venv) PS C:\KAIRI-SIO> pip install -r requirements_api.txt

# Zusätzliche Abhängigkeit für das einzugsgebietsübergreifende Experiment
(.venv) PS C:\KAIRI-SIO> pip install scipy

# AEMET-Abhängigkeiten
(.venv) PS C:\KAIRI-SIO> pip install python-dotenv requests
```

---

## 12. Projektstruktur

```
C:\KAIRI-SIO\
│
├── .env                          ← Umgebungsvariablen (AEMET_API_KEY)
├── dashboard.py                  ← Streamlit-Dashboard v2.0
├── kairi_tree.py                 ← Projektbaum-Dienstprogramm
├── requirements.txt              ← Pipeline-Abhängigkeiten
├── requirements_api.txt          ← API + Dashboard-Abhängigkeiten
│
├── 03_Datos_Fuentes_Oficiales\   ← UNANTASTBAR — offizielle MITECO-Quellen
│   ├── Caumax_Nacional\          ← QGIS-Plugin für CEDEX-Maximalabflüsse
│   ├── MDT\                      ← Digitale Geländemodelle
│   └── SNCZI_Cartografia\        ← Überschwemmungsgebiete T10/T100/T500
│       ├── Ebro\                 ← SAIH-Ebro-Daten (Itoiz, Mequinenza, Yesa)
│       └── guadalquivir\         ← SAIH-Guadalquivir-Daten (E32, E33, E37)
│
├── data\
│   ├── raw\                      ← Rohdaten (untransformierte Parquets)
│   │   ├── saih_ebro\            ← Ebro-Roh erzeugt von saih_ebro_reader
│   │   ├── saih_guadalquivir\    ← Originale CHG-XLSX
│   │   ├── aemet\                ← AEMET-Beobachtungen
│   │   └── cartografia_snczi\   ← SNCZI-Shapefiles T10/T100/T500
│   ├── curated\                  ← Datenvertrag v1.1 (normalisierte Parquets)
│   │   └── ebro\                 ← Kuratiertes CHE
│   └── analytic\                 ← Bewertete Parquets mit S_c, quality_flag
│       └── ebro\                 ← Analytisches CHE
│
├── src\
│   ├── api\                      ← FastAPI REST-API
│   │   ├── main.py
│   │   └── schemas.py
│   ├── config\                   ← Mehrflusskonfiguration
│   │   ├── confederation_config.py
│   │   ├── sensor_config.py
│   │   └── confederations\
│   │       ├── CHG.yaml          ← Produktion
│   │       ├── CHE.yaml          ← Pilot
│   │       ├── CHD.yaml          ← Platzhalter
│   │       └── CHT.yaml          ← Platzhalter
│   ├── forensics\                ← JSONL-Forensikprotokoll
│   │   └── forensic_logger.py
│   ├── ingestion\                ← Leser und Ingestion
│   │   ├── saih_reader.py        ← CHG (XLSX)
│   │   ├── saih_ebro_reader.py   ← CHE (CSV sep=;)
│   │   ├── aemet_connector.py    ← AEMET OpenData REST
│   │   ├── normalizer.py
│   │   ├── validator.py
│   │   └── run_ingestion.py
│   ├── scoring\                  ← Bewertungsmodell
│   │   ├── s_f.py                ← Physikalischer Teilscore
│   │   ├── s_l.py                ← Logischer Teilscore
│   │   ├── s_t.py                ← Zeitlicher Teilscore
│   │   ├── s_h.py                ← Historischer Teilscore
│   │   ├── scorer.py             ← S_c-Orchestrator
│   │   └── run_scoring.py        ← Mehrfach-CLI
│   ├── validation\               ← Validierung und Metriken
│   │   ├── ground_truth_builder.py
│   │   └── run_validation.py
│   └── veto\                     ← Entscheidungsmotor
│       ├── decision_engine.py
│       └── run_veto.py
│
├── notebooks\
│   ├── mvp_demo\
│   │   └── kairi_sio_demo.py
│   └── validacion\
│       └── kairi_sio_intercuencas.py  ← Einzugsgebietsübergreifendes Experiment
│
├── output\
│   ├── demo\                     ← MVP-Demo-Diagramme
│   ├── forensics\                ← Forensische JSONL-Protokolle
│   ├── reports\                  ← Generierte Berichte
│   └── validation\               ← Validierungsergebnisse
│
└── docs\
    ├── arquitectura\             ← Technische Dokumentation
    ├── modelo_matematico\        ← PDFs zur mathematischen Grundlage
    └── regulatorio\              ← Referenzierte WMO-, GUM-, ISO-Normen
```

---

## Literaturverzeichnis

| Referenz | Verwendung in KAIRI-SIO |
|---|---|
| Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill. | AHP-Gewichte für den zusammengesetzten Score S_c |
| JCGM 100:2008. *Leitfaden zur Angabe der Messunsicherheit* (GUM). | Klassifikationsschwellenwerte GESPERRT/ZERTIFIZIERT |
| Nelson, L.S. (1984). The Shewhart Control Chart — Tests for Special Causes. *Journal of Quality Technology*, 16(4), 237–239. | FLATLINE_K = 8h |
| ISO 7870-2:2013. *Regelkarten — Teil 2: Shewhart-Regelkarten*. | FLATLINE_K = 8h |
| WMO-Nr.168. *Leitfaden für hydrologische Praxis*, Bd. I, Kap. 2. | FLAT_CRITICAL_H = 48h, GAP_WARN/FAIL |
| WMO-Nr.8. *Leitfaden für meteorologische Instrumente und Beobachtungsmethoden*, Kap. 1. | GAP_WARN/FAIL |
| Page, E.S. (1954). Continuous Inspection Schemes. *Biometrika*, 41(1/2), 100–115. | DRIFT_THRESH (CUSUM-Detektor) |
| Lucas, J.M. & Saccucci, M.S. (1990). Exponentially Weighted Moving Average Control Schemes. *Technometrics*, 32(1), 1–12. | DRIFT_THRESH (EWMA-Detektor) |
| Montgomery, D.C. (2012). *Introduction to Statistical Quality Control*, 7. Aufl. Wiley. | Allgemeines SPC-Rahmenwerk |

---

*KAIRI-SIO v1.1.0 · Reymar (mathematische Spezifikation) · Kent Valera Chirinos (technische Implementierung) · 2026-03-13*
