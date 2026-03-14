"""
KAIRI-SIO — Demo Visual MVP
============================
Sprint 4 · Kent Valera Chirinos · 2026

Sistema de Verificación de Integridad de Señal Hidrológica
SAIH Guadalquivir · 3 embalses · 2015–2024 · 260,841 observaciones

Arquitectura de fuentes (Opción A — parquet scored inmutable):
  FUENTE PRIMARIA   → output/forensics/*_summary_*.csv
                      veto_flag, veto_level, critical_flag, primary_reason
  FUENTE SECUNDARIA → data/analytic/*_scored.parquet
                      sub-scores detallados, H_level, serie temporal S_c

Uso (desde C:/KAIRI-SIO):
    python notebooks/mvp_demo/kairi_sio_demo.py
    python notebooks/mvp_demo/kairi_sio_demo.py \
        --forensics output/forensics \
        --analytic  data/analytic \
        --output    output/demo

Genera:
    01_quality_flag_distribution.png
    02_sc_timeseries.png
    03_dst_zoom.png
    04_violin_subscores.png
    05_heatmap_detail.png
    06_summary_table.png
    kairi_sio_mvp_summary.csv
"""

import argparse
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import warnings

warnings.filterwarnings("ignore")

# ── CLI ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="KAIRI-SIO Demo Visual MVP")
parser.add_argument("--forensics", type=Path, default=Path("output/forensics"),
                    help="Carpeta con los *_summary_*.csv (default: output/forensics)")
parser.add_argument("--analytic",  type=Path, default=Path("data/analytic"),
                    help="Carpeta con los *_scored.parquet (default: data/analytic)")
parser.add_argument("--output",    type=Path, default=Path("output/demo"),
                    help="Carpeta de salida (default: output/demo)")
args = parser.parse_args()

FORENSICS_DIR = args.forensics
ANALYTIC_DIR  = args.analytic
OUT_DIR       = args.output
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Constantes ─────────────────────────────────────────────────────────────────
EMBALSES = ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"]
LABELS = {
    "E32_VADOMOJON":   "E32 · Vado Mojón",
    "E33_SRRA_BOYERA": "E33 · Sierra Boyera",
    "E37_BEMBEZAR":    "E37 · Bembézar",
}
COLORS = {
    "E32_VADOMOJON":   "#00b4d8",
    "E33_SRRA_BOYERA": "#90e0ef",
    "E37_BEMBEZAR":    "#48cae4",
}
FLAG_COLORS = {
    "CERTIFICADA": "#2dc653",
    "DEGRADADA":   "#f4a261",
    "VETADA":      "#e63946",
}
FLAG_ORDER = ["CERTIFICADA", "DEGRADADA", "VETADA"]

DETAILED_COLS = [
    "sl_C_PH", "sl_C_QH", "sl_C_z",
    "st_lat_seconds", "st_L_lat", "st_gap_rate_W1", "st_G_gap",
    "sh_F_flat", "sh_F_drift", "sh_F_gap24",
]

# ── Estilo global ──────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi":       120,
    "figure.facecolor": "#0f1117",
    "axes.facecolor":   "#1a1d27",
    "axes.edgecolor":   "#3a3d4a",
    "axes.labelcolor":  "#d0d4e0",
    "axes.grid":        True,
    "grid.color":       "#2a2d3a",
    "grid.linewidth":   0.5,
    "text.color":       "#d0d4e0",
    "xtick.color":      "#9093a0",
    "ytick.color":      "#9093a0",
    "legend.facecolor": "#1a1d27",
    "legend.edgecolor": "#3a3d4a",
    "font.family":      "monospace",
})


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 1 — Carga de datos
# Fuente primaria : CSV summary → veto_flag, critical_flag
# Fuente secundaria: parquet   → sub-scores, H_level, S_c
# Merge por ts_station + sensor_id
# ══════════════════════════════════════════════════════════════════════════════
def _latest_csv(forensics_dir: Path, embalse_id: str) -> Path:
    candidates = sorted(forensics_dir.glob(f"{embalse_id}_summary_*.csv"))
    if not candidates:
        print(f"  ✗  Sin CSV summary para {embalse_id} en {forensics_dir}", file=sys.stderr)
        sys.exit(1)
    if len(candidates) > 1:
        print(f"  ⚠  Múltiples CSV para {embalse_id} — usando: {candidates[-1].name}")
    return candidates[-1]


def load_data(forensics_dir: Path, analytic_dir: Path) -> tuple[dict, bool]:
    print("\n[1/6] Cargando datos...")
    dfs = {}

    for e in EMBALSES:
        # ── CSV summary: fuente de verdad para flags ───────────────────────────
        csv_path = _latest_csv(forensics_dir, e)
        df_csv = pd.read_csv(csv_path, parse_dates=["ts_station"])
        df_csv["ts_station"] = pd.to_datetime(df_csv["ts_station"]).dt.tz_localize(None)

        # ── Parquet: sub-scores + H_level ─────────────────────────────────────
        pq_path = analytic_dir / f"{e}_scored.parquet"
        if not pq_path.exists():
            print(f"  ✗  Parquet no encontrado: {pq_path}", file=sys.stderr)
            sys.exit(1)
        df_pq = pd.read_parquet(pq_path)
        df_pq["ts_station"] = pd.to_datetime(df_pq["ts_station"]).dt.tz_localize(None)

        # Columnas exclusivas del parquet (no solapan con CSV)
        pq_keep = ["ts_station", "sensor_id", "H_level", "Q_inflow", "P_rain"] + \
                  [c for c in DETAILED_COLS if c in df_pq.columns]
        df_pq_slim = df_pq[[c for c in pq_keep if c in df_pq.columns]]

        # ── Merge ──────────────────────────────────────────────────────────────
        df = df_csv.merge(df_pq_slim, on=["ts_station", "sensor_id"], how="left")
        df = df.sort_values("ts_station").reset_index(drop=True)
        dfs[e] = df

        vc = df["veto_flag"].value_counts()
        n_crit = int(df["critical_flag"].sum())
        print(f"  ✓  {LABELS[e]:<30} {len(df):>7,} filas")
        print(f"       CERT={vc.get('CERTIFICADA',0):,}  "
              f"DEGR={vc.get('DEGRADADA',0):,}  "
              f"VETO={vc.get('VETADA',0):,}  "
              f"(CRITICAL={n_crit:,})")
        print(f"       CSV: {csv_path.name}")

    sample = dfs[EMBALSES[0]]
    has_detailed = all(c in sample.columns for c in DETAILED_COLS)
    print(f"\n  Sub-columnas --detailed: {'✓ disponibles' if has_detailed else '✗ no disponibles'}\n")
    return dfs, has_detailed


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 2 — Distribución veto_flag
# ══════════════════════════════════════════════════════════════════════════════
def plot_quality_flag(dfs: dict, out_dir: Path):
    print("[2/6] Distribución veto_flag...")
    df_all = pd.concat(dfs.values(), ignore_index=True)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.suptitle("Distribución veto_flag — KAIRI-SIO MVP", fontsize=13, y=1.01, color="#e0e4f0")

    # ── Barras apiladas horizontales ───────────────────────────────────────────
    ax = axes[0]
    counts = (
        df_all.groupby(["sensor_id", "veto_flag"])
        .size().unstack(fill_value=0)
        .reindex(columns=FLAG_ORDER, fill_value=0)
        .reindex(EMBALSES)
    )
    pcts = counts.div(counts.sum(axis=1), axis=0) * 100
    bottom = np.zeros(len(EMBALSES))
    y_pos = np.arange(len(EMBALSES))

    for flag in FLAG_ORDER:
        vals = pcts[flag].values
        ax.barh(y_pos, vals, left=bottom, color=FLAG_COLORS[flag],
                label=flag, height=0.55, alpha=0.92)
        for i, (v, b) in enumerate(zip(vals, bottom)):
            if v > 1.5:
                ax.text(b + v / 2, i, f"{v:.1f}%", ha="center", va="center",
                        fontsize=8.5, color="#0f1117", fontweight="bold")
        bottom += vals

    ax.set_yticks(y_pos)
    ax.set_yticklabels([LABELS[e] for e in EMBALSES], fontsize=9)
    ax.set_xlabel("% observaciones", fontsize=9)
    ax.set_xlim(0, 101)
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title("Composición por embalse", fontsize=10)

    # ── Donut total ────────────────────────────────────────────────────────────
    ax2 = axes[1]
    total_counts = df_all["veto_flag"].value_counts().reindex(FLAG_ORDER, fill_value=0)
    n_total   = len(df_all)
    n_critical = int(df_all["critical_flag"].sum())

    wedges, _, autotexts = ax2.pie(
        total_counts.values,
        colors=[FLAG_COLORS[f] for f in FLAG_ORDER],
        autopct="%1.2f%%",
        startangle=90,
        wedgeprops={"width": 0.55, "edgecolor": "#0f1117", "linewidth": 2},
        pctdistance=0.75,
    )
    for at in autotexts:
        at.set_fontsize(9)
        at.set_color("#0f1117")
        at.set_fontweight("bold")
    ax2.legend(wedges, [f"{f}  ({total_counts[f]:,})" for f in FLAG_ORDER],
               loc="lower center", fontsize=8.5, bbox_to_anchor=(0.5, -0.14))
    ax2.set_title(f"Total {n_total:,} obs · {n_critical} CRITICAL_FLAG", fontsize=10)
    ax2.text(0, 0, f"{n_total:,}\nobs", ha="center", va="center",
             fontsize=9, color="#c0c4d0")

    plt.tight_layout()
    out = out_dir / "01_quality_flag_distribution.png"
    plt.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → {out}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 3 — Serie temporal S_c con VETADA y CRITICAL_FLAG marcados
# ══════════════════════════════════════════════════════════════════════════════
def plot_sc_timeseries(dfs: dict, out_dir: Path):
    print("[3/6] Serie temporal S_c...")
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    fig.suptitle("Serie temporal S_c — Score global de confianza KAIRI-SIO", fontsize=13, y=1.01)

    for ax, e in zip(axes, EMBALSES):
        df = dfs[e]
        color = COLORS[e]

        df_day = df.set_index("ts_station")["S_c"].resample("D").mean()
        ax.plot(df_day.index, df_day.values, color=color, lw=0.7, alpha=0.85,
                label="S_c diario (media)")

        ax.axhline(0.85, color="#2dc653", lw=0.8, ls="--", alpha=0.6,
                   label="Umbral CERTIFICADA (0.85)")
        ax.axhline(0.50, color="#e63946", lw=0.8, ls="--", alpha=0.6,
                   label="Umbral VETADA (0.50)")

        vetados  = df[df["veto_flag"]    == "VETADA"]
        criticos = df[df["critical_flag"] == True]

        if len(vetados):
            ax.scatter(vetados["ts_station"], vetados["S_c"],
                       color="#e63946", s=30, zorder=5, alpha=0.9,
                       label=f"VETADA ({len(vetados)})")
        if len(criticos):
            ax.scatter(criticos["ts_station"], criticos["S_c"],
                       color="#ff6b6b", s=80, zorder=6, marker="X",
                       label=f"CRITICAL_FLAG ({len(criticos)})")

        ax.fill_between(df_day.index, 0.50, 0.85,
                        color="#f4a261", alpha=0.06, label="Zona DEGRADADA")

        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel("S_c", fontsize=9)
        ax.set_title(LABELS[e], fontsize=9, loc="left", pad=4)
        mu = df["S_c"].mean()
        ax.text(0.01, 0.08, f"μ={mu:.4f}", transform=ax.transAxes,
                fontsize=8, color=color, alpha=0.9)
        handles, labels_leg = ax.get_legend_handles_labels()
        ax.legend(handles[:5], labels_leg[:5], fontsize=7.5, loc="lower right", ncol=2)

    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[-1].xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    axes[-1].set_xlabel("Fecha", fontsize=9)

    plt.tight_layout()
    out = out_dir / "02_sc_timeseries.png"
    plt.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → {out}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 4 — Zoom DST (CRITICAL_FLAG en marzo)
# ══════════════════════════════════════════════════════════════════════════════
def plot_dst_zoom(dfs: dict, out_dir: Path):
    print("[4/6] Zoom DST eventos CRITICAL_FLAG...")

    e_zoom = max(EMBALSES, key=lambda e: dfs[e]["critical_flag"].sum())
    df_z = dfs[e_zoom].copy()
    df_z["year"] = df_z["ts_station"].dt.year

    dst_mask = df_z["critical_flag"] & (df_z["ts_station"].dt.month == 3)
    dst_years = sorted(df_z[dst_mask]["year"].unique())[:3]
    n_crit = int(df_z["critical_flag"].sum())
    print(f"  Embalse zoom: {LABELS[e_zoom]}  |  CRITICAL_FLAG total: {n_crit}")
    print(f"  Años DST marzo: {[int(y) for y in dst_years]}")

    if not dst_years:
        dst_years = sorted(df_z[df_z["veto_flag"] == "VETADA"]["year"].unique())[:3]
        if not dst_years:
            print("  ⚠  Sin eventos VETADA — bloque omitido.")
            return

    fig, axes = plt.subplots(len(dst_years), 2, figsize=(16, 4.5 * len(dst_years)))
    if len(dst_years) == 1:
        axes = axes.reshape(1, 2)
    fig.suptitle(f"Zoom DST — Cambio de hora (marzo) · {LABELS[e_zoom]}", fontsize=12)

    for row_i, yr in enumerate(dst_years):
        mask = (
            (df_z["ts_station"] >= f"{int(yr)}-03-27") &
            (df_z["ts_station"] <= f"{int(yr)}-04-01")
        )
        chunk   = df_z[mask]
        criticos = chunk[chunk["critical_flag"] == True]

        # Panel izquierdo: H_level
        ax_h = axes[row_i, 0]
        if "H_level" in chunk.columns:
            ax_h.plot(chunk["ts_station"], chunk["H_level"],
                      color=COLORS[e_zoom], lw=1.2, label="H_level (m)")
            if len(criticos):
                ax_h.scatter(criticos["ts_station"], criticos["H_level"],
                             color="#ff6b6b", s=90, zorder=5, marker="X",
                             label=f"CRITICAL_FLAG ({len(criticos)})")
        ax_h.set_title(f"{int(yr)} — Nivel", fontsize=9, loc="left")
        ax_h.set_ylabel("H_level (m)", fontsize=8)
        ax_h.legend(fontsize=8)
        ax_h.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        plt.setp(ax_h.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)

        # Panel derecho: S_t
        ax_t = axes[row_i, 1]
        ax_t.plot(chunk["ts_station"], chunk["S_t"],
                  color="#f4a261", lw=1.2, label="S_t (integridad temporal)")
        if len(criticos):
            ax_t.scatter(criticos["ts_station"], criticos["S_t"],
                         color="#ff6b6b", s=90, zorder=5, marker="X",
                         label=f"CRITICAL_FLAG ({len(criticos)})")
        ax_t.axhline(0.1, color="#e63946", ls="--", lw=0.8, alpha=0.7,
                     label="S_t=0.1  (lat>900s = DST)")
        ax_t.set_ylim(-0.05, 1.1)
        ax_t.set_title(f"{int(yr)} — S_t temporal", fontsize=9, loc="left")
        ax_t.set_ylabel("S_t", fontsize=8)
        ax_t.legend(fontsize=8)
        ax_t.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        plt.setp(ax_t.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)

    plt.tight_layout()
    out = out_dir / "03_dst_zoom.png"
    plt.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → {out}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 5 — Violin plot S_f / S_l / S_t / S_h
# ══════════════════════════════════════════════════════════════════════════════
def plot_violin_subscores(dfs: dict, out_dir: Path):
    print("[5/6] Violin sub-scores...")
    SUBSCORES = ["S_f", "S_l", "S_t", "S_h"]
    SUBSCORE_LABELS = {
        "S_f": "S_f\nIntegridad física",
        "S_l": "S_l\nCoherencia lógica",
        "S_t": "S_t\nIntegridad temporal",
        "S_h": "S_h\nSalud histórica",
    }

    frames = []
    for e in EMBALSES:
        cols_ok = [c for c in SUBSCORES if c in dfs[e].columns]
        df_s = dfs[e][cols_ok + ["sensor_id"]].dropna()
        if len(df_s) > 20_000:
            df_s = df_s.sample(20_000, random_state=42)
        frames.append(df_s.melt(id_vars="sensor_id", value_vars=cols_ok,
                                var_name="subscore", value_name="valor"))
    df_violin = pd.concat(frames, ignore_index=True)

    fig, axes = plt.subplots(1, 4, figsize=(16, 6), sharey=True)
    fig.suptitle("Distribución de sub-scores por embalse — KAIRI-SIO", fontsize=12, y=1.01)

    for ax, sc in zip(axes, SUBSCORES):
        data_sc = df_violin[df_violin["subscore"] == sc]
        arrays  = [data_sc[data_sc["sensor_id"] == e]["valor"].values for e in EMBALSES]

        if all(len(a) > 1 for a in arrays):
            parts = ax.violinplot(arrays, positions=range(len(EMBALSES)),
                                  showmedians=True, showextrema=False, widths=0.7)
            for body, e in zip(parts["bodies"], EMBALSES):
                body.set_facecolor(COLORS[e])
                body.set_alpha(0.75)
                body.set_edgecolor("#3a3d4a")
            parts["cmedians"].set_color("#ffffff")
            parts["cmedians"].set_linewidth(1.5)

        for i, e in enumerate(EMBALSES):
            arr = data_sc[data_sc["sensor_id"] == e]["valor"]
            if len(arr):
                mu = arr.mean()
                ax.scatter(i, mu, color="#ffffff", s=40, zorder=5, marker="D", lw=0)
                ax.text(i, mu + 0.03, f"{mu:.3f}", ha="center", va="bottom",
                        fontsize=7, color="#ffffff")

        ax.set_xticks(range(len(EMBALSES)))
        ax.set_xticklabels(["E32\nV.Mojón", "E33\nS.Boyera", "E37\nBembézar"], fontsize=8)
        ax.set_title(SUBSCORE_LABELS[sc], fontsize=9)
        ax.set_ylim(-0.05, 1.15)
        if ax is axes[0]:
            ax.set_ylabel("Valor del sub-score", fontsize=9)
        ax.axhline(0.85, color="#2dc653", lw=0.7, ls=":", alpha=0.5)
        ax.axhline(0.50, color="#e63946", lw=0.7, ls=":", alpha=0.5)

    plt.tight_layout()
    out = out_dir / "04_violin_subscores.png"
    plt.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → {out}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 5b — Heatmap sub-scores detallados
# ══════════════════════════════════════════════════════════════════════════════
def plot_heatmap_detail(dfs: dict, out_dir: Path):
    print("[5b] Heatmap sub-scores detallados...")
    DETAIL_COLS = {
        "sl_C_PH":       "C_PH\nLluvia→Nivel",
        "sl_C_QH":       "C_QH\nCaudal→Nivel",
        "sl_C_z":        "C_z\nz-score MAD",
        "sh_F_flat":     "F_flat\nFlatline",
        "sh_F_drift":    "F_drift\nDrift EMA",
        "sh_F_gap24":    "F_gap24\nGap 24h",
        "st_gap_rate_W1":"gap_W1\nGap rate W1",
    }
    available = {k: v for k, v in DETAIL_COLS.items()
                 if k in dfs[EMBALSES[0]].columns}

    records = []
    for e in EMBALSES:
        row = {"embalse": LABELS[e]}
        for col, label in available.items():
            row[label] = dfs[e][col].mean()
        records.append(row)

    df_heat = pd.DataFrame(records).set_index("embalse")

    fig, ax = plt.subplots(figsize=(12, 3.5))
    fig.suptitle("Media de sub-scores detallados por embalse", fontsize=11)
    sns.heatmap(df_heat, ax=ax, annot=True, fmt=".3f", cmap="Blues",
                vmin=0, vmax=1, linewidths=0.5, linecolor="#2a2d3a",
                annot_kws={"size": 9}, cbar_kws={"label": "Media"})
    ax.tick_params(axis="x", labelsize=8)
    ax.tick_params(axis="y", labelsize=8, rotation=0)

    plt.tight_layout()
    out = out_dir / "05_heatmap_detail.png"
    plt.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → {out}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUE 6 — Tabla resumen + CSV
# veto_flag es la fuente de verdad — no quality_flag del parquet
# ══════════════════════════════════════════════════════════════════════════════
def plot_summary_table(dfs: dict, out_dir: Path):
    print("[6/6] Tabla resumen...")
    rows = []
    for e in EMBALSES:
        df  = dfs[e]
        n   = len(df)
        vc  = df["veto_flag"].value_counts()
        rows.append({
            "Embalse":  LABELS[e],
            "Filas":    n,
            "CERT (%)": round(vc.get("CERTIFICADA", 0) / n * 100, 2),
            "DEGR (%)": round(vc.get("DEGRADADA",   0) / n * 100, 2),
            "VETO (%)": round(vc.get("VETADA",      0) / n * 100, 3),
            "N_CERT":   vc.get("CERTIFICADA", 0),
            "N_DEGR":   vc.get("DEGRADADA",   0),
            "N_VETO":   vc.get("VETADA",      0),
            "N_CRIT":   int(df["critical_flag"].sum()),
            "S_c μ":    round(df["S_c"].mean(), 4),
            "S_c min":  round(df["S_c"].min(),  4),
            "S_c p5":   round(df["S_c"].quantile(0.05), 4),
            "S_f μ":    round(df["S_f"].mean(), 4),
            "S_l μ":    round(df["S_l"].mean(), 4),
            "S_t μ":    round(df["S_t"].mean(), 4),
            "S_h μ":    round(df["S_h"].mean(), 4),
        })

    df_sum = pd.DataFrame(rows)

    csv_out = out_dir / "kairi_sio_mvp_summary.csv"
    df_sum.to_csv(csv_out, index=False)
    print(f"  → {csv_out}")

    display_cols = ["Embalse", "Filas", "CERT (%)", "DEGR (%)", "VETO (%)",
                    "N_CRIT", "S_c μ", "S_c min", "S_c p5",
                    "S_f μ", "S_l μ", "S_t μ", "S_h μ"]
    df_disp = df_sum[display_cols].copy()
    df_disp["Filas"] = df_disp["Filas"].apply(lambda x: f"{x:,}")

    fig, ax = plt.subplots(figsize=(18, 2.5))
    ax.axis("off")
    fig.patch.set_facecolor("#0f1117")

    table = ax.table(cellText=df_disp.values, colLabels=df_disp.columns,
                     cellLoc="center", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.6)

    for j in range(len(df_disp.columns)):
        cell = table[0, j]
        cell.set_facecolor("#00b4d8")
        cell.set_text_props(color="#0f1117", fontweight="bold")

    row_bg = ["#1a1d27", "#222536"]
    for i in range(1, len(df_disp) + 1):
        for j in range(len(df_disp.columns)):
            cell = table[i, j]
            cell.set_facecolor(row_bg[(i - 1) % 2])
            cell.set_text_props(color="#d0d4e0")
            cell.set_edgecolor("#2a2d3a")

    fig.suptitle("KAIRI-SIO MVP — Tabla Resumen Sprint 4  [fuente: veto_flag]",
                 fontsize=10, color="#d0d4e0", y=0.98)

    out = out_dir / "06_summary_table.png"
    plt.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
    plt.close()
    print(f"  → {out}")

    print()
    print(df_sum[["Embalse", "N_CERT", "N_DEGR", "N_VETO", "N_CRIT", "S_c μ"]].to_string(index=False))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("═" * 62)
    print("  KAIRI-SIO — Demo Visual MVP · Sprint 4")
    print("═" * 62)
    print(f"  forensics_dir : {FORENSICS_DIR.resolve()}")
    print(f"  analytic_dir  : {ANALYTIC_DIR.resolve()}")
    print(f"  output_dir    : {OUT_DIR.resolve()}")

    dfs, has_detailed = load_data(FORENSICS_DIR, ANALYTIC_DIR)

    plot_quality_flag(dfs, OUT_DIR)
    plot_sc_timeseries(dfs, OUT_DIR)
    plot_dst_zoom(dfs, OUT_DIR)
    plot_violin_subscores(dfs, OUT_DIR)

    if has_detailed:
        plot_heatmap_detail(dfs, OUT_DIR)
    else:
        print("[5b] Sub-columnas --detailed no disponibles — bloque omitido.")
        print("     Regenerar con: python src/scoring/run_scoring.py --detailed")

    plot_summary_table(dfs, OUT_DIR)

    print()
    print("═" * 62)
    print("  DEMO COMPLETADA")
    print("═" * 62)
    for f in sorted(OUT_DIR.glob("*.png")) + sorted(OUT_DIR.glob("*.csv")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()