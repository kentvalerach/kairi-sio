"""
KAIRI-SIO — ground_truth_builder.py
=====================================
Sprint 5 · Validación contra ground truth

Construye un dataset de errores conocidos a partir de los parquet curated,
usando únicamente patrones detectables en los datos crudos sin fuente externa.

Tres tipos de error:
    SPIKE_SENSOR   → |ΔH| > SPIKE_THRESH en 1h  (imposible físico)
    FLATLINE       → H_level idéntico >= FLAT_MIN_H horas consecutivas
    GAP_COMM       → NaN simultáneo H+Q+P >= GAP_MIN_H horas consecutivas

Umbrales calibrados sobre percentiles reales de los 3 embalses:
    SPIKE_THRESH  = 1.0m   (p999 oscila 0.06–0.12m; 1m es 8–16x p999)
    FLAT_MIN_H    = 24     (sensor atascado ≥1 día)
    GAP_MIN_H     = 3      (comunicación cortada ≥3h)

Output:
    output/validation/ground_truth.parquet
    output/validation/ground_truth_summary.csv
"""

from pathlib import Path
import pandas as pd
import numpy as np

# ── Umbrales calibrados empíricamente ─────────────────────────────────────────
SPIKE_THRESH_M  = 1.0    # metros — |ΔH| en 1h para considerar spike
FLAT_MIN_HOURS  = 24     # horas consecutivas idénticas → flatline
GAP_MIN_HOURS   = 3      # horas consecutivas NaN(H+Q+P) → gap comunicación

EMBALSES = ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"]


def detect_spikes(df: pd.DataFrame, embalse_id: str) -> pd.DataFrame:
    """
    Detecta spikes: |ΔH| > SPIKE_THRESH_M en 1 hora.
    Marca AMBAS filas del salto (la que sube y la que baja).
    """
    dH = df["H_level"].diff().abs()
    mask = dH > SPIKE_THRESH_M

    # También marcar la fila anterior (origen del salto)
    mask_prev = mask.shift(-1, fill_value=False)
    combined  = mask | mask_prev

    events = df[combined].copy()
    events["error_type"]  = "SPIKE_SENSOR"
    events["error_detail"] = dH[combined].apply(
        lambda x: f"dH={x:.3f}m > {SPIKE_THRESH_M}m threshold" if pd.notna(x) else "spike_pair"
    )
    return events[["ts_station", "sensor_id", "error_type", "error_detail"]]


def detect_flatlines(df: pd.DataFrame, embalse_id: str) -> pd.DataFrame:
    """
    Detecta flatlines: H_level idéntico >= FLAT_MIN_HOURS consecutivas.
    Excluye NaN (NaN != NaN en comparación directa).
    """
    h = df["H_level"]
    is_flat = (h == h.shift(1)) & h.notna() & h.shift(1).notna()
    group   = (is_flat != is_flat.shift()).cumsum()

    records = []
    for grp_id, grp in df[is_flat].groupby(group[is_flat]):
        if len(grp) >= FLAT_MIN_HOURS - 1:  # -1 porque el primer igual es shift(1)
            # Recuperar fila de inicio (la anterior al primer igual)
            idx_start = grp.index[0] - 1
            if idx_start >= 0:
                start_row = df.loc[idx_start]
                records.append({
                    "ts_station":   start_row["ts_station"],
                    "sensor_id":    embalse_id,
                    "error_type":   "FLATLINE",
                    "error_detail": f"flatline_{len(grp)+1}h_value={grp['H_level'].iloc[0]:.4f}m",
                })
            for _, row in grp.iterrows():
                records.append({
                    "ts_station":   row["ts_station"],
                    "sensor_id":    embalse_id,
                    "error_type":   "FLATLINE",
                    "error_detail": f"flatline_{len(grp)+1}h_value={row['H_level']:.4f}m",
                })

    if not records:
        return pd.DataFrame(columns=["ts_station", "sensor_id", "error_type", "error_detail"])
    return pd.DataFrame(records).drop_duplicates("ts_station")


def detect_gap_comm(df: pd.DataFrame, embalse_id: str) -> pd.DataFrame:
    """
    Detecta gaps de comunicación: NaN simultáneo en H_level + Q_inflow + P_rain
    durante >= GAP_MIN_HOURS consecutivas.
    """
    all_nan = df["H_level"].isna() & df["Q_inflow"].isna() & df["P_rain"].isna()
    group   = (all_nan != all_nan.shift()).cumsum()

    records = []
    for grp_id, grp in df[all_nan].groupby(group[all_nan]):
        if len(grp) >= GAP_MIN_HOURS:
            for _, row in grp.iterrows():
                records.append({
                    "ts_station":   row["ts_station"],
                    "sensor_id":    embalse_id,
                    "error_type":   "GAP_COMM",
                    "error_detail": f"gap_comm_{len(grp)}h_simultaneous_NaN",
                })

    if not records:
        return pd.DataFrame(columns=["ts_station", "sensor_id", "error_type", "error_detail"])
    return pd.DataFrame(records)


def build_ground_truth(curated_dir: Path, output_dir: Path) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_errors = []

    print("\n[ground_truth_builder] Detectando errores conocidos...")
    print(f"  Umbrales: SPIKE>{SPIKE_THRESH_M}m | FLAT>={FLAT_MIN_HOURS}h | GAP>={GAP_MIN_HOURS}h")
    print()

    for e in EMBALSES:
        path = curated_dir / f"{e}.parquet"
        if not path.exists():
            print(f"  ✗ No encontrado: {path}")
            continue

        df = pd.read_parquet(path)
        df["ts_station"] = pd.to_datetime(df["ts_station"]).dt.tz_localize(None)
        df = df.sort_values("ts_station").reset_index(drop=True)

        spikes   = detect_spikes(df, e)
        flats    = detect_flatlines(df, e)
        gaps     = detect_gap_comm(df, e)

        embalse_errors = pd.concat([spikes, flats, gaps], ignore_index=True)
        all_errors.append(embalse_errors)

        print(f"  {e}")
        print(f"    SPIKE_SENSOR : {len(spikes):>5} filas  ({len(spikes[spikes['error_type']=='SPIKE_SENSOR']) if len(spikes) else 0} eventos brutos)")
        print(f"    FLATLINE     : {len(flats):>5} filas")
        print(f"    GAP_COMM     : {len(gaps):>5} filas")
        print(f"    TOTAL errores: {len(embalse_errors):>5} filas únicas")
        print()

    gt = pd.concat(all_errors, ignore_index=True)
    gt = gt.drop_duplicates(subset=["ts_station", "sensor_id", "error_type"])
    gt = gt.sort_values(["sensor_id", "ts_station"]).reset_index(drop=True)

    # ── Output ────────────────────────────────────────────────────────────────
    pq_out  = output_dir / "ground_truth.parquet"
    csv_out = output_dir / "ground_truth_summary.csv"
    gt.to_parquet(pq_out, index=False)
    gt.to_csv(csv_out, index=False)

    print(f"  Ground truth total: {len(gt):,} filas de error")
    print(f"  → {pq_out}")
    print(f"  → {csv_out}")

    return gt


if __name__ == "__main__":
    build_ground_truth(
        curated_dir = Path("data/curated"),
        output_dir  = Path("output/validation"),
    )