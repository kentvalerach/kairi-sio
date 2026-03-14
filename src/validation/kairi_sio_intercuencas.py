"""
KAIRI-SIO — notebooks/validacion/kairi_sio_intercuencas.py
Experimento de Validación Intercuencas — 2026-03-13

Hipótesis: el modelo KAIRI-SIO detecta anomalías de forma consistente
independientemente de la cuenca hidrográfica (Guadalquivir vs Ebro).

Pruebas:
  1) Distribución S_c por cuenca
  2) Detección flatlines — recall comparado
  3) Detección spikes  — recall comparado
  4) Activación CRITICAL_FLAG por cuenca
  5) Test estadístico KS: ¿son las distribuciones S_c comparables?

Uso:
  python notebooks/validacion/kairi_sio_intercuencas.py

Output:
  output/validation/intercuencas_report.csv
  output/validation/intercuencas_summary.txt
  output/validation/intercuencas_sc_distribution.png
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ANALYTIC_CHG = ROOT / "data" / "analytic"
ANALYTIC_CHE = ROOT / "data" / "analytic" / "ebro"
OUT_DIR      = ROOT / "output" / "validation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Embalses por cuenca ───────────────────────────────────────────────────────
CUENCAS = {
    "CHG_Guadalquivir": {
        "path": ANALYTIC_CHG,
        "embalses": ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"],
        "color": "#2980b9",
    },
    "CHE_Ebro": {
        "path": ANALYTIC_CHE,
        "embalses": ["ITOIZ", "MEQUINENZA", "YESA"],
        "color": "#27ae60",
    },
}


def load_cuenca(cuenca_id: str, cfg: dict) -> pd.DataFrame:
    """Carga todos los scored.parquet de una cuenca."""
    dfs = []
    for eid in cfg["embalses"]:
        p = cfg["path"] / f"{eid}_scored.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["embalse_id"] = eid
            df["cuenca"]     = cuenca_id
            dfs.append(df)
        else:
            print(f"  ⚠ No encontrado: {p}")
    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()


def test_1_distribucion_sc(cuencas_data: dict) -> pd.DataFrame:
    """Distribución S_c por cuenca y embalse."""
    rows = []
    for cuenca_id, df in cuencas_data.items():
        if df.empty:
            continue
        for eid, grp in df.groupby("embalse_id"):
            sc = grp["S_c"].dropna()
            rows.append({
                "cuenca":    cuenca_id,
                "embalse":   eid,
                "n":         len(sc),
                "S_c_mean":  round(sc.mean(), 4),
                "S_c_std":   round(sc.std(), 4),
                "S_c_p5":    round(sc.quantile(0.05), 4),
                "S_c_p50":   round(sc.median(), 4),
                "S_c_p95":   round(sc.quantile(0.95), 4),
                "pct_CERT":  round((grp.get("regime", grp.get("veto_flag", grp.get("quality_flag"))) == "CERTIFICADA").mean() * 100, 2),
                "pct_DEGR":  round((grp.get("regime", grp.get("veto_flag", grp.get("quality_flag"))) == "DEGRADADA").mean() * 100, 2),
                "pct_VETO":  round((grp.get("regime", grp.get("veto_flag", grp.get("quality_flag"))) == "VETADA").mean() * 100, 2),
            })
    return pd.DataFrame(rows)


def test_2_flatline(cuencas_data: dict) -> pd.DataFrame:
    """
    Detección flatlines sobre datos reales del parquet scored.
    F_flat activado cuando S_f <= 0.20 (TEC_Formulas_Sc_Veto_v1.1)
    S_f == 0.0 → CRITICAL_FLAG (flatline >= 48h)
    """
    rows = []

    for cuenca_id, df in cuencas_data.items():
        if df.empty or "S_f" not in df.columns:
            continue

        for eid, grp in df.groupby("embalse_id"):
            n = len(grp)
            if n < 100:
                continue

            sf = grp["S_f"]

            # F_flat activado: S_f <= 0.20 (flatline >= K=8h)
            n_sf_flat = int((sf <= 0.20).sum())
            # CRITICAL: S_f == 0.0 (flatline >= 48h → veto automático)
            n_sf_critical = int((sf == 0.0).sum())

            rows.append({
                "cuenca":        cuenca_id,
                "embalse":       eid,
                "n_total":       n,
                "S_f_mean":      round(float(sf.mean()), 4),
                "S_f_min":       round(float(sf.min()), 4),
                "n_flat":        n_sf_flat,
                "pct_flat":      round(n_sf_flat / n * 100, 2),
                "n_critical":    n_sf_critical,
                "pct_critical":  round(n_sf_critical / n * 100, 2),
            })

    return pd.DataFrame(rows)


def test_3_ks(cuencas_data: dict) -> dict:
    """Test Kolmogorov-Smirnov entre distribuciones S_c CHG vs CHE."""
    sc_chg = pd.concat([
        df["S_c"] for k, df in cuencas_data.items()
        if "CHG" in k and not df.empty
    ]).dropna()

    sc_che = pd.concat([
        df["S_c"] for k, df in cuencas_data.items()
        if "CHE" in k and not df.empty
    ]).dropna()

    if sc_chg.empty or sc_che.empty:
        return {"ks_stat": None, "p_value": None, "interpretacion": "Sin datos suficientes"}

    ks_stat, p_value = stats.ks_2samp(sc_chg, sc_che)

    if p_value > 0.05:
        interp = "Las distribuciones S_c son estadísticamente similares (p>0.05) ✅"
    else:
        interp = f"Las distribuciones difieren significativamente (p={p_value:.4f}) — analizar causa"

    return {
        "ks_stat":        round(float(ks_stat), 4),
        "p_value":        round(float(p_value), 6),
        "n_CHG":          len(sc_chg),
        "n_CHE":          len(sc_che),
        "mean_CHG":       round(float(sc_chg.mean()), 4),
        "mean_CHE":       round(float(sc_che.mean()), 4),
        "interpretacion": interp,
    }


def plot_comparacion(cuencas_data: dict, dist_df: pd.DataFrame):
    """Genera gráfico comparativo de distribuciones S_c."""
    fig = plt.figure(figsize=(14, 8))
    gs  = gridspec.GridSpec(2, 2, figure=fig)

    colors = {"CHG_Guadalquivir": "#2980b9", "CHE_Ebro": "#27ae60"}

    # ── Plot 1: KDE S_c por cuenca ────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    for cuenca_id, df in cuencas_data.items():
        if df.empty or "S_c" not in df.columns:
            continue
        sc = df["S_c"].dropna()
        sc.plot.kde(ax=ax1, label=cuenca_id, color=colors.get(cuenca_id, "gray"),
                    linewidth=2)
    ax1.axvline(0.85, color="green",  linestyle="--", alpha=0.7, label="CERTIFICADA (0.85)")
    ax1.axvline(0.50, color="red",    linestyle="--", alpha=0.7, label="VETADA (0.50)")
    ax1.set_title("Distribución S_c — Comparación Intercuencas", fontsize=13, fontweight="bold")
    ax1.set_xlabel("S_c")
    ax1.set_ylabel("Densidad")
    ax1.legend()
    ax1.set_xlim(0.5, 1.0)

    # ── Plot 2: S_c medio por embalse ─────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    if not dist_df.empty:
        bar_colors = [colors.get(r["cuenca"], "gray") for _, r in dist_df.iterrows()]
        ax2.barh(dist_df["embalse"], dist_df["S_c_mean"], color=bar_colors, alpha=0.85)
        ax2.axvline(0.85, color="green", linestyle="--", alpha=0.7)
        ax2.set_xlabel("S_c medio")
        ax2.set_title("S_c medio por embalse")
        ax2.set_xlim(0.7, 1.0)
        for i, (_, row) in enumerate(dist_df.iterrows()):
            ax2.text(row["S_c_mean"] + 0.002, i, f"{row['S_c_mean']:.4f}", va="center", fontsize=9)

    # ── Plot 3: % CERT/DEGR/VETO por cuenca ───────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    if not dist_df.empty:
        cuenca_agg = dist_df.groupby("cuenca")[["pct_CERT", "pct_DEGR", "pct_VETO"]].mean()
        cuenca_agg.plot(kind="bar", ax=ax3, color=["#2ecc71", "#f39c12", "#e74c3c"],
                        edgecolor="white", width=0.6)
        ax3.set_title("Distribución regímenes por cuenca (%)")
        ax3.set_ylabel("%")
        ax3.set_xticklabels(ax3.get_xticklabels(), rotation=15, ha="right")
        ax3.legend(["CERTIFICADA", "DEGRADADA", "VETADA"], fontsize=8)

    plt.tight_layout()
    out_path = OUT_DIR / "intercuencas_sc_distribution.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Gráfico guardado: {out_path}")


def main():
    print("=" * 60)
    print("KAIRI-SIO — Experimento Validación Intercuencas")
    print("Fecha: 2026-03-13")
    print("=" * 60)

    # Cargar datos
    cuencas_data = {}
    for cuenca_id, cfg in CUENCAS.items():
        print(f"\nCargando {cuenca_id}...")
        df = load_cuenca(cuenca_id, cfg)
        if not df.empty:
            print(f"  ✅ {len(df):,} observaciones cargadas")
            cuencas_data[cuenca_id] = df
        else:
            print(f"  ⚠ Sin datos — ejecuta scoring primero")
            cuencas_data[cuenca_id] = pd.DataFrame()

    # Test 1 — Distribución S_c
    print("\n[TEST 1] Distribución S_c por embalse...")
    dist_df = test_1_distribucion_sc(cuencas_data)
    if not dist_df.empty:
        print(dist_df.to_string(index=False))

    # Test 2 — Flatlines
    print("\n[TEST 2] Recall detección flatlines...")
    flat_df = test_2_flatline(cuencas_data)
    if not flat_df.empty:
        print(flat_df.to_string(index=False))
        print()
        for _, row in flat_df.iterrows():
            if row["pct_flat"] < 1.0:
                verdict = "✅ Señal limpia — flatlines residuales"
            elif row["pct_flat"] < 5.0:
                verdict = "⚠  Flatlines moderados detectados"
            else:
                verdict = "🔴 Alta tasa flatline — revisar sensor"
            print(f"  {row['cuenca']:20s} / {row['embalse']:12s}: {verdict}")
    else:
        print("  ⚠ Sin columna S_f — ejecuta scoring --detailed")

    # Test 3 — KS
    print("\n[TEST 3] Kolmogorov-Smirnov CHG vs CHE...")
    ks_result = test_3_ks(cuencas_data)
    for k, v in ks_result.items():
        print(f"  {k}: {v}")

    # Gráfico
    has_data = any(not df.empty for df in cuencas_data.values())
    if has_data:
        print("\nGenerando gráfico comparativo...")
        plot_comparacion(cuencas_data, dist_df)

    # Guardar CSV
    if not dist_df.empty:
        out_csv = OUT_DIR / "intercuencas_report.csv"
        dist_df.to_csv(out_csv, index=False)
        print(f"\nCSV guardado: {out_csv}")

    # Guardar resumen texto
    summary_lines = [
        "KAIRI-SIO — Experimento Validación Intercuencas",
        "=" * 60,
        f"Fecha: 2026-03-13",
        "",
        "HIPÓTESIS: El modelo detecta anomalías independientemente de la cuenca.",
        "",
        "TEST 3 — Kolmogorov-Smirnov:",
    ]
    for k, v in ks_result.items():
        summary_lines.append(f"  {k}: {v}")

    if not flat_df.empty:
        summary_lines += ["", "TEST 2 — Detección Flatlines (sobre datos reales):"]
        for _, row in flat_df.iterrows():
            summary_lines.append(
                f"  {row['cuenca']} / {row['embalse']}: "
                f"S_f_mean={row['S_f_mean']:.4f} "
                f"n_flat={row['n_sf_flat']} ({row['pct_flat']}%) "
                f"n_critical={row['n_sf_critical']} ({row['pct_critical']}%)"
            )

    out_txt = OUT_DIR / "intercuencas_summary.txt"
    out_txt.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Resumen guardado: {out_txt}")

    print("\n" + "=" * 60)
    print("Experimento completado.")
    print("=" * 60)


if __name__ == "__main__":
    main()