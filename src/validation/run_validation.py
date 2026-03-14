"""
KAIRI-SIO — run_validation.py
===============================
Sprint 5 · Validación contra ground truth

Cruza el dataset de errores conocidos (ground_truth_builder.py)
con los veto_flag del motor de veto (CSV summary del Sprint 3).

Métricas calculadas:
    Precision  = TP / (TP + FP)
        De todos los VETADA/DEGRADADA que marcó KAIRI, ¿cuántos coinciden
        con un error conocido?

    Recall     = TP / (TP + FN)
        De todos los errores conocidos, ¿cuántos detectó KAIRI?

    F1         = 2 * P * R / (P + R)

Definición de "detección":
    Un error conocido en timestamp T se considera DETECTADO si KAIRI marcó
    veto_flag IN ('VETADA', 'DEGRADADA') en T o en T±WINDOW_H horas.
    WINDOW_H=1 por defecto (tolerancia de 1h para desfases de resolución).

Output:
    output/validation/validation_report.csv     ← métricas por embalse y tipo
    output/validation/validation_detail.parquet ← tabla completa con match
    output/validation/validation_report.txt     ← resumen legible

Uso (desde C:/KAIRI-SIO):
    python src/validation/run_validation.py
    python src/validation/run_validation.py --window 0   # sin tolerancia
    python src/validation/run_validation.py --window 2   # ±2h tolerancia
    python src/validation/run_validation.py --strict      # solo VETADA cuenta
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.validation.ground_truth_builder import build_ground_truth

# ── Config ─────────────────────────────────────────────────────────────────────
EMBALSES = ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"]
LABELS   = {
    "E32_VADOMOJON":   "E32 · Vado Mojón",
    "E33_SRRA_BOYERA": "E33 · Sierra Boyera",
    "E37_BEMBEZAR":    "E37 · Bembézar",
}


def _latest_csv(forensics_dir: Path, embalse_id: str) -> Path:
    candidates = sorted(forensics_dir.glob(f"{embalse_id}_summary_*.csv"))
    if not candidates:
        print(f"✗ Sin CSV summary para {embalse_id}", file=sys.stderr)
        sys.exit(1)
    return candidates[-1]


def load_veto(forensics_dir: Path) -> pd.DataFrame:
    """Carga todos los CSV summary y los combina."""
    frames = []
    for e in EMBALSES:
        df = pd.read_csv(_latest_csv(forensics_dir, e), parse_dates=["ts_station"])
        df["ts_station"] = pd.to_datetime(df["ts_station"]).dt.tz_localize(None)
        frames.append(df[["ts_station", "sensor_id", "veto_flag",
                           "veto_level", "critical_flag", "S_c"]])
    return pd.concat(frames, ignore_index=True)


def match_errors(
    gt: pd.DataFrame,
    veto: pd.DataFrame,
    window_h: int = 1,
    strict: bool = False,
) -> pd.DataFrame:
    """
    Para cada error conocido en gt, busca si veto lo detectó
    dentro de una ventana de ±window_h horas.

    strict=True → solo VETADA cuenta como detección
    strict=False → VETADA o DEGRADADA cuenta
    """
    detect_flags = {"VETADA"} if strict else {"VETADA", "DEGRADADA"}
    window = pd.Timedelta(hours=window_h)

    # Índice temporal del veto por embalse para búsqueda rápida
    veto_detected = veto[veto["veto_flag"].isin(detect_flags)].copy()

    results = []
    for _, err in gt.iterrows():
        e   = err["sensor_id"]
        ts  = err["ts_station"]

        # Buscar en ventana ±window_h
        candidates = veto_detected[
            (veto_detected["sensor_id"] == e) &
            (veto_detected["ts_station"] >= ts - window) &
            (veto_detected["ts_station"] <= ts + window)
        ]

        detected     = len(candidates) > 0
        best_veto    = candidates.iloc[0]["veto_flag"] if detected else None
        best_Sc      = candidates.iloc[0]["S_c"]       if detected else None
        is_critical  = bool(candidates.iloc[0]["critical_flag"]) if detected else False

        results.append({
            "sensor_id":    e,
            "ts_station":   ts,
            "error_type":   err["error_type"],
            "error_detail": err["error_detail"],
            "detected":     detected,
            "veto_flag":    best_veto,
            "S_c":          best_Sc,
            "critical_flag": is_critical,
        })

    return pd.DataFrame(results)


def compute_metrics(
    detail: pd.DataFrame,
    veto: pd.DataFrame,
    strict: bool,
) -> pd.DataFrame:
    """
    Calcula TP, FN, FP, Precision, Recall, F1
    por embalse y por tipo de error.
    """
    detect_flags = {"VETADA"} if strict else {"VETADA", "DEGRADADA"}
    rows = []

    for e in EMBALSES:
        gt_e    = detail[detail["sensor_id"] == e]
        veto_e  = veto[
            (veto["sensor_id"] == e) &
            (veto["veto_flag"].isin(detect_flags))
        ]

        # Total alertas emitidas por KAIRI para este embalse
        n_alerts = len(veto_e)

        for error_type in ["SPIKE_SENSOR", "FLATLINE", "GAP_COMM", "ALL"]:
            if error_type == "ALL":
                subset = gt_e
            else:
                subset = gt_e[gt_e["error_type"] == error_type]

            if len(subset) == 0:
                continue

            TP = subset["detected"].sum()
            FN = (~subset["detected"]).sum()

            # FP: alertas de KAIRI que NO coinciden con ningún error conocido
            # Aproximación: alertas totales - TP (conservador)
            FP = max(0, n_alerts - TP) if error_type == "ALL" else None

            precision = TP / (TP + FP) if (FP is not None and TP + FP > 0) else None
            recall    = TP / (TP + FN) if (TP + FN > 0) else 0.0
            f1        = (2 * precision * recall / (precision + recall)
                         if precision and recall and precision + recall > 0
                         else None)

            rows.append({
                "embalse":      LABELS[e],
                "error_type":   error_type,
                "n_errores":    len(subset),
                "TP":           int(TP),
                "FN":           int(FN),
                "FP":           int(FP) if FP is not None else "-",
                "recall":       round(recall, 4),
                "precision":    round(precision, 4) if precision is not None else "-",
                "F1":           round(f1, 4)        if f1        is not None else "-",
            })

    return pd.DataFrame(rows)


def write_report(metrics: pd.DataFrame, detail: pd.DataFrame,
                 output_dir: Path, window_h: int, strict: bool):
    """Escribe reporte legible en texto."""
    mode = "STRICT (solo VETADA)" if strict else "NORMAL (VETADA + DEGRADADA)"
    lines = [
        "═" * 70,
        "  KAIRI-SIO — Reporte de Validación contra Ground Truth",
        "═" * 70,
        f"  Modo        : {mode}",
        f"  Ventana     : ±{window_h}h",
        f"  Errores GT  : {len(detail):,} timestamps",
        "",
    ]

    for e in EMBALSES:
        m_e = metrics[metrics["embalse"] == LABELS[e]]
        if m_e.empty:
            continue
        lines.append(f"  {'─'*66}")
        lines.append(f"  {LABELS[e]}")
        lines.append(f"  {'─'*66}")
        lines.append(f"  {'Tipo':<15} {'N_err':>6} {'TP':>5} {'FN':>5} "
                     f"{'FP':>5} {'Recall':>8} {'Precision':>10} {'F1':>8}")
        lines.append(f"  {'-'*15} {'-'*6} {'-'*5} {'-'*5} "
                     f"{'-'*5} {'-'*8} {'-'*10} {'-'*8}")
        for _, row in m_e.iterrows():
            lines.append(
                f"  {row['error_type']:<15} {row['n_errores']:>6} "
                f"{row['TP']:>5} {row['FN']:>5} {str(row['FP']):>5} "
                f"{row['recall']:>8.3f} {str(row['precision']):>10} "
                f"{str(row['F1']):>8}"
            )
        lines.append("")

    # Falsos negativos más relevantes (no detectados)
    fn_rows = detail[~detail["detected"]].sort_values("ts_station")
    if len(fn_rows):
        lines.append(f"  {'─'*66}")
        lines.append(f"  Falsos Negativos — errores NO detectados por KAIRI (top 20)")
        lines.append(f"  {'─'*66}")
        lines.append(f"  {'Embalse':<22} {'Timestamp':<22} {'Tipo':<15} {'Detalle'}")
        for _, row in fn_rows.head(20).iterrows():
            lines.append(
                f"  {LABELS[row['sensor_id']]:<22} "
                f"{str(row['ts_station']):<22} "
                f"{row['error_type']:<15} "
                f"{str(row['error_detail'])[:40]}"
            )
        lines.append("")

    lines.append("═" * 70)

    txt = "\n".join(lines)
    print(txt)

    out = output_dir / "validation_report.txt"
    out.write_text(txt, encoding="utf-8")
    print(f"\n  → {out}")


def run_validation(
    curated_dir:   Path,
    forensics_dir: Path,
    output_dir:    Path,
    window_h:      int  = 1,
    strict:        bool = False,
    rebuild_gt:    bool = False,
):
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Ground truth ───────────────────────────────────────────────────────────
    gt_path = output_dir / "ground_truth.parquet"
    if gt_path.exists() and not rebuild_gt:
        print(f"\n[1/4] Ground truth cacheado → {gt_path}")
        gt = pd.read_parquet(gt_path)
        gt["ts_station"] = pd.to_datetime(gt["ts_station"]).dt.tz_localize(None)
        print(f"      {len(gt):,} errores conocidos")
    else:
        gt = build_ground_truth(curated_dir, output_dir)

    # ── Veto flags ─────────────────────────────────────────────────────────────
    print(f"\n[2/4] Cargando veto flags desde {forensics_dir}...")
    veto = load_veto(forensics_dir)
    print(f"      {len(veto):,} timestamps totales")
    vc = veto["veto_flag"].value_counts()
    for flag, n in vc.items():
        print(f"      {flag}: {n:,}")

    # ── Match ──────────────────────────────────────────────────────────────────
    print(f"\n[3/4] Cruzando ground truth con veto_flag (ventana ±{window_h}h)...")
    detail = match_errors(gt, veto, window_h=window_h, strict=strict)

    pq_out = output_dir / "validation_detail.parquet"
    detail.to_parquet(pq_out, index=False)
    print(f"      → {pq_out}")

    # ── Métricas ───────────────────────────────────────────────────────────────
    print(f"\n[4/4] Calculando métricas...")
    metrics = compute_metrics(detail, veto, strict=strict)

    csv_out = output_dir / "validation_report.csv"
    metrics.to_csv(csv_out, index=False)
    print(f"      → {csv_out}")

    # ── Reporte ────────────────────────────────────────────────────────────────
    print()
    write_report(metrics, detail, output_dir, window_h, strict)

    return metrics, detail


def main():
    parser = argparse.ArgumentParser(description="KAIRI-SIO Validation Runner")
    parser.add_argument("--curated",    type=Path, default=Path("data/curated"))
    parser.add_argument("--forensics",  type=Path, default=Path("output/forensics"))
    parser.add_argument("--output",     type=Path, default=Path("output/validation"))
    parser.add_argument("--window",     type=int,  default=1,
                        help="Ventana de tolerancia en horas (default: 1)")
    parser.add_argument("--strict",     action="store_true",
                        help="Solo VETADA cuenta como detección (default: VETADA+DEGRADADA)")
    parser.add_argument("--rebuild-gt", action="store_true",
                        help="Forzar reconstrucción del ground truth aunque exista cache")
    args = parser.parse_args()

    run_validation(
        curated_dir   = args.curated,
        forensics_dir = args.forensics,
        output_dir    = args.output,
        window_h      = args.window,
        strict        = args.strict,
        rebuild_gt    = args.rebuild_gt,
    )


if __name__ == "__main__":
    main()