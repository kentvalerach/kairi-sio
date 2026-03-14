"""
KAIRI-SIO — dashboard.py  v2.0
Dashboard de monitorización institucional — multiconfederación.

Vistas:
  1. Distribución CERT/DEGR/VETO por embalse
  2. Serie temporal S_c
  3. Mapa de calor sub-scores (S_f, S_l, S_t, S_h)
  4. Tabla de eventos CRITICAL_FLAG
  5. Recall de detección — Sprint 5 ground truth
  6. Comparación intercuencas CHG vs CHE  [NUEVO]
  7. Panel AEMET — observaciones en tiempo real [NUEVO]

Uso (desde C:/KAIRI-SIO):
  streamlit run dashboard.py

Despliegue Railway/Render:
  web: streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Configuración página ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="KAIRI-SIO · Integridad Hidrológica",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constantes ────────────────────────────────────────────────────────────────
COLORS = {
    "CERTIFICADA": "#2ecc71",
    "DEGRADADA":   "#f39c12",
    "VETADA":      "#e74c3c",
}

CUENCA_COLORS = {
    "CHG": "#2980b9",
    "CHE": "#27ae60",
}

EMBALSE_META = {
    # CHG
    "E32_VADOMOJON":   {"label": "E32 · Vado Mojón",    "cuenca": "CHG", "rio": "Guadalquivir"},
    "E33_SRRA_BOYERA": {"label": "E33 · Sierra Boyera", "cuenca": "CHG", "rio": "Bembézar"},
    "E37_BEMBEZAR":    {"label": "E37 · Bembézar",      "cuenca": "CHG", "rio": "Bembézar"},
    # CHE
    "ITOIZ":           {"label": "Itoiz",                "cuenca": "CHE", "rio": "Irati"},
    "MEQUINENZA":      {"label": "Mequinenza",           "cuenca": "CHE", "rio": "Ebro"},
    "YESA":            {"label": "Yesa",                 "cuenca": "CHE", "rio": "Aragón"},
}

GROUND_TRUTH = {
    "E32_VADOMOJON":   {"before": 0.674, "after": 0.762, "delta": 0.088},
    "E33_SRRA_BOYERA": {"before": 0.844, "after": 0.880, "delta": 0.036},
    "E37_BEMBEZAR":    {"before": 0.568, "after": 0.608, "delta": 0.040},
}

ANALYTIC_CHG = Path("data/analytic")
ANALYTIC_CHE = Path("data/analytic/ebro")
EMBALSES_CHG = ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"]
EMBALSES_CHE = ["ITOIZ", "MEQUINENZA", "YESA"]


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Cargando datos CHG (Guadalquivir)...")
def load_chg() -> dict[str, pd.DataFrame]:
    dfs = {}
    for eid in EMBALSES_CHG:
        path = ANALYTIC_CHG / f"{eid}_scored.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            df["ts_station"] = pd.to_datetime(df["ts_station"])
            df["regime"] = df.get("quality_flag", df.get("veto_flag", "DEGRADADA"))
            df["cuenca"] = "CHG"
            dfs[eid] = df
    return dfs


@st.cache_data(show_spinner="Cargando datos CHE (Ebro)...")
def load_che() -> dict[str, pd.DataFrame]:
    dfs = {}
    for eid in EMBALSES_CHE:
        path = ANALYTIC_CHE / f"{eid}_scored.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            df["ts_station"] = pd.to_datetime(df["ts_station"])
            df["regime"] = df.get("quality_flag", df.get("veto_flag", "DEGRADADA"))
            df["cuenca"] = "CHE"
            dfs[eid] = df
    return dfs


@st.cache_data(ttl=300, show_spinner="Consultando AEMET...")
def load_aemet() -> list:
    """Obtiene observaciones AEMET con TTL=5min. Falla silenciosamente."""
    try:
        from src.ingestion.aemet_connector import AEMETConnector, run_obs_all
        connector = AEMETConnector()
        if not connector.api_key:
            return []
        return run_obs_all(connector)
    except Exception:
        return []


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("💧 KAIRI-SIO")
    st.caption("Integridad de Señal Hidrológica")
    st.divider()

    # Selector de cuenca
    cuenca_sel = st.radio(
        "Confederación",
        options=["CHG · Guadalquivir", "CHE · Ebro", "Ambas"],
        index=0,
    )
    show_chg = cuenca_sel in ("CHG · Guadalquivir", "Ambas")
    show_che = cuenca_sel in ("CHE · Ebro", "Ambas")

    st.divider()

    # Selector de embalses
    embalse_options = []
    embalse_defaults = []
    if show_chg:
        embalse_options += EMBALSES_CHG
        embalse_defaults += EMBALSES_CHG
    if show_che:
        embalse_options += EMBALSES_CHE
        embalse_defaults += EMBALSES_CHE

    selected_embalses = st.multiselect(
        "Embalses",
        options=embalse_options,
        default=embalse_defaults,
        format_func=lambda x: EMBALSE_META[x]["label"],
    )

    st.divider()

    # Rango de fechas dinámico según cuenca
    if show_chg and not show_che:
        d_min, d_max = pd.Timestamp("2015-01-01"), pd.Timestamp("2024-12-31")
        d_def = (pd.Timestamp("2015-01-01"), pd.Timestamp("2024-12-31"))
    elif show_che and not show_chg:
        d_min, d_max = pd.Timestamp("2025-03-13"), pd.Timestamp("2026-03-13")
        d_def = (pd.Timestamp("2025-03-13"), pd.Timestamp("2026-03-13"))
    else:
        d_min, d_max = pd.Timestamp("2015-01-01"), pd.Timestamp("2026-03-13")
        d_def = (pd.Timestamp("2015-01-01"), pd.Timestamp("2026-03-13"))

    date_range = st.date_input("Período", value=d_def, min_value=d_min, max_value=d_max)

    st.divider()
    aemet_on = st.toggle("🌦 Panel AEMET (tiempo real)", value=False)
    st.divider()
    st.caption("**Modelo:** kairi-sio-sc-v1.0.0")
    st.caption("**Sprint:** Intercuencas · 2026-03-13")


# ── Load & merge ──────────────────────────────────────────────────────────────
all_dfs = {}
if show_chg:
    all_dfs.update(load_chg())
if show_che:
    all_dfs.update(load_che())

if not all_dfs:
    st.error("No se encontraron parquets scored. Ejecuta primero el scoring pipeline.")
    st.stop()

# Filtro fecha + embalse
try:
    date_start = pd.Timestamp(date_range[0])
    date_end   = pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)
except Exception:
    date_start, date_end = d_min, d_max + pd.Timedelta(days=1)

filtered = {}
for eid in selected_embalses:
    if eid in all_dfs:
        df   = all_dfs[eid]
        mask = (df["ts_station"] >= date_start) & (df["ts_station"] < date_end)
        filtered[eid] = df[mask].copy()

if not filtered:
    st.warning("Sin datos para los filtros seleccionados.")
    st.stop()


# ── Header ────────────────────────────────────────────────────────────────────
cuenca_titulo = {"CHG · Guadalquivir": "CHG · Guadalquivir",
                 "CHE · Ebro": "CHE · Ebro",
                 "Ambas": "CHG + CHE · Intercuencas"}[cuenca_sel]

st.markdown(f"## 💧 KAIRI-SIO · {cuenca_titulo}")
st.caption("Sistema de Verificación de Integridad de Señal Hidrológica · v1.0.0")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────
total_obs  = sum(len(df) for df in filtered.values())
total_cert = sum((df["regime"] == "CERTIFICADA").sum() for df in filtered.values())
total_vet  = sum((df["regime"] == "VETADA").sum() for df in filtered.values())
total_crit = sum(df.get("critical_flag", pd.Series(False, index=df.index)).sum()
                 for df in filtered.values())
mean_sc    = np.mean([df["S_c"].mean() for df in filtered.values()])

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Observaciones",  f"{total_obs:,}")
k2.metric("CERTIFICADA",    f"{total_cert/total_obs*100:.1f}%",
          delta=f"{total_cert:,} obs")
k3.metric("VETADA",         f"{total_vet/total_obs*100:.1f}%",
          delta=f"-{total_vet:,} obs", delta_color="inverse")
k4.metric("CRITICAL FLAG",  f"{total_crit:,}", delta_color="inverse")
k5.metric("S_c medio",      f"{mean_sc:.4f}")
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 1 — Distribución regímenes
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 📊 Distribución de regímenes por embalse")

dist_rows = []
for eid, df in filtered.items():
    n = len(df)
    meta = EMBALSE_META[eid]
    for regime in ["CERTIFICADA", "DEGRADADA", "VETADA"]:
        dist_rows.append({
            "Embalse":      meta["label"],
            "Cuenca":       meta["cuenca"],
            "Régimen":      regime,
            "Observaciones": (df["regime"] == regime).sum(),
            "Porcentaje":   (df["regime"] == regime).sum() / n * 100,
        })

dist_df = pd.DataFrame(dist_rows)

col1, col2 = st.columns([2, 1])
with col1:
    fig_bar = px.bar(
        dist_df, x="Embalse", y="Porcentaje", color="Régimen",
        color_discrete_map=COLORS, text="Porcentaje",
        barmode="stack", height=380,
        color_discrete_sequence=None,
    )
    fig_bar.update_traces(texttemplate="%{text:.1f}%", textposition="inside")
    fig_bar.update_layout(
        margin=dict(t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis_title="% observaciones", xaxis_title="",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col2:
    sc_rows = []
    for eid, df in filtered.items():
        meta = EMBALSE_META[eid]
        sc_rows.append({
            "Embalse": meta["label"],
            "Cuenca":  meta["cuenca"],
            "S_c µ":   round(df["S_c"].mean(), 4),
        })
    sc_df = pd.DataFrame(sc_rows)
    bar_colors = [CUENCA_COLORS[r["Cuenca"]] for _, r in sc_df.iterrows()]
    fig_sc = px.bar(
        sc_df, x="S_c µ", y="Embalse", orientation="h",
        color="S_c µ", color_continuous_scale="RdYlGn",
        range_color=[0.75, 1.0], height=380, text="S_c µ",
    )
    fig_sc.update_traces(texttemplate="%{text:.4f}", textposition="outside")
    fig_sc.update_layout(
        margin=dict(t=20, b=10), coloraxis_showscale=False,
        xaxis=dict(range=[0.75, 1.0]), xaxis_title="S_c medio", yaxis_title="",
    )
    st.plotly_chart(fig_sc, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 2 — Serie temporal S_c
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 📈 Serie temporal S_c")

resample_opt = st.select_slider(
    "Resolución temporal",
    options=["1D", "1W", "1ME", "3ME"],
    value="1ME",
    format_func=lambda x: {"1D": "Diaria", "1W": "Semanal",
                            "1ME": "Mensual", "3ME": "Trimestral"}[x],
)

fig_ts = go.Figure()
for eid, df in filtered.items():
    meta = EMBALSE_META[eid]
    df_r = df.set_index("ts_station")["S_c"].resample(resample_opt).mean().reset_index()
    fig_ts.add_trace(go.Scatter(
        x=df_r["ts_station"], y=df_r["S_c"],
        name=meta["label"], mode="lines", line=dict(width=2),
    ))

fig_ts.add_hline(y=0.85, line_dash="dash", line_color=COLORS["CERTIFICADA"],
                 annotation_text="CERTIFICADA (0.85)", annotation_position="right")
fig_ts.add_hline(y=0.50, line_dash="dash", line_color=COLORS["VETADA"],
                 annotation_text="VETADA (0.50)", annotation_position="right")
fig_ts.update_layout(
    height=380, margin=dict(t=20, b=10),
    yaxis=dict(range=[0.5, 1.0], title="S_c"), xaxis_title="",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_ts, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 3 — Mapa de calor sub-scores
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🌡️ Mapa de calor sub-scores")

subscores     = ["S_f", "S_l", "S_t", "S_h", "S_c"]
subscore_lbls = {"S_f": "S_f · Física", "S_l": "S_l · Lógica",
                 "S_t": "S_t · Temporal", "S_h": "S_h · Histórica",
                 "S_c": "S_c · Compuesto"}

hm_rows = []
for eid, df in filtered.items():
    row = {"Embalse": EMBALSE_META[eid]["label"]}
    for s in subscores:
        if s in df.columns:
            row[subscore_lbls[s]] = round(df[s].mean(), 4)
    hm_rows.append(row)

hm_df = pd.DataFrame(hm_rows).set_index("Embalse")
fig_hm = px.imshow(
    hm_df, color_continuous_scale="RdYlGn", zmin=0.7, zmax=1.0,
    text_auto=".4f", aspect="auto", height=max(200, 60 * len(hm_rows) + 80),
)
fig_hm.update_layout(
    margin=dict(t=20, b=10),
    coloraxis_colorbar=dict(title="Score"),
    xaxis_title="", yaxis_title="",
)
st.plotly_chart(fig_hm, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 4 — Tabla CRITICAL_FLAG
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🚨 Eventos CRITICAL_FLAG")

crit_rows = []
for eid, df in filtered.items():
    if "critical_flag" not in df.columns:
        continue
    crit_df = df[df["critical_flag"] == True].copy()
    if crit_df.empty:
        continue
    crit_df["Embalse"] = EMBALSE_META[eid]["label"]
    crit_rows.append(crit_df)

if crit_rows:
    crit_all = pd.concat(crit_rows, ignore_index=True)
    display_cols = {k: v for k, v in {
        "Embalse": "Embalse", "ts_station": "Timestamp",
        "S_c": "S_c", "S_f": "S_f", "S_t": "S_t", "regime": "Régimen",
    }.items() if k in crit_all.columns}
    crit_display = crit_all[list(display_cols.keys())].rename(columns=display_cols)
    crit_display["Timestamp"] = pd.to_datetime(crit_display["Timestamp"]).dt.strftime("%Y-%m-%d %H:%M")
    crit_display = crit_display.sort_values("Timestamp", ascending=False)

    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.dataframe(crit_display.head(200), use_container_width=True, hide_index=True)
    with col_b:
        st.metric("Total eventos críticos", f"{len(crit_all):,}")
        for eid, df in filtered.items():
            if "critical_flag" in df.columns:
                n_c = int(df["critical_flag"].sum())
                st.metric(EMBALSE_META[eid]["label"], f"{n_c:,}",
                          delta=f"{n_c/len(df)*100:.2f}%", delta_color="inverse")
else:
    st.info("No hay eventos CRITICAL_FLAG en el período seleccionado.")


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 5 — Recall Sprint 5 (solo CHG)
# ══════════════════════════════════════════════════════════════════════════════
chg_selected = [e for e in selected_embalses if EMBALSE_META[e]["cuenca"] == "CHG"]
if chg_selected:
    st.markdown("### ✅ Recall de detección — Validación Sprint 5 (CHG)")
    st.caption("Ground truth: 14,614 errores conocidos · SAIH Guadalquivir 2015–2024")

    recall_rows = [{"Embalse": EMBALSE_META[eid]["label"],
                    "Antes": gt["before"], "Después": gt["after"], "Δ": gt["delta"]}
                   for eid, gt in GROUND_TRUTH.items() if eid in chg_selected]
    recall_df = pd.DataFrame(recall_rows)

    col_r1, col_r2 = st.columns([2, 1])
    with col_r1:
        fig_recall = go.Figure()
        fig_recall.add_trace(go.Bar(
            name="Antes ext. 48h", x=recall_df["Embalse"], y=recall_df["Antes"],
            marker_color="#95a5a6", text=recall_df["Antes"].apply(lambda x: f"{x:.3f}"),
            textposition="outside",
        ))
        fig_recall.add_trace(go.Bar(
            name="Después ext. 48h", x=recall_df["Embalse"], y=recall_df["Después"],
            marker_color=COLORS["CERTIFICADA"], text=recall_df["Después"].apply(lambda x: f"{x:.3f}"),
            textposition="outside",
        ))
        fig_recall.update_layout(
            barmode="group", height=320, margin=dict(t=20, b=10),
            yaxis=dict(range=[0.0, 1.0], title="Recall"), xaxis_title="",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_recall, use_container_width=True)
    with col_r2:
        st.markdown("**Recalls adicionales**")
        st.markdown("| Tipo | Recall |\n|------|--------|\n"
                    "| SPIKE (3 embalses) | **1.000** 🟢 |\n"
                    "| GAP modo normal | **1.000** 🟢 |\n"
                    "| GAP modo strict | **0.000** ✓ |")
        st.caption("GAP strict = 0.000 es correcto por diseño.")


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 6 — Comparación intercuencas (solo si Ambas)
# ══════════════════════════════════════════════════════════════════════════════
if cuenca_sel == "Ambas" and filtered:
    st.markdown("### 🔀 Comparación intercuencas — CHG vs CHE")
    st.caption("Experimento validación 2026-03-13 · mismos parámetros sin recalibración")

    fig_kde = go.Figure()
    for cuenca_id, color in CUENCA_COLORS.items():
        sc_vals = pd.concat([
            df["S_c"] for eid, df in filtered.items()
            if EMBALSE_META[eid]["cuenca"] == cuenca_id
        ], ignore_index=True).dropna() if any(
            EMBALSE_META[eid]["cuenca"] == cuenca_id for eid in filtered
        ) else pd.Series(dtype=float)

        if sc_vals.empty:
            continue
        sc_vals.plot.kde()
        import scipy.stats as _stats
        kde   = _stats.gaussian_kde(sc_vals)
        x_rng = np.linspace(0.5, 1.0, 200)
        fig_kde.add_trace(go.Scatter(
            x=x_rng, y=kde(x_rng),
            name=f"{cuenca_id} (µ={sc_vals.mean():.4f})",
            mode="lines", line=dict(width=2.5, color=color),
        ))

    fig_kde.add_vline(x=0.85, line_dash="dash", line_color=COLORS["CERTIFICADA"],
                      annotation_text="0.85")
    fig_kde.add_vline(x=0.50, line_dash="dash", line_color=COLORS["VETADA"],
                      annotation_text="0.50")
    fig_kde.update_layout(
        height=300, margin=dict(t=20, b=10),
        xaxis=dict(range=[0.5, 1.05], title="S_c"),
        yaxis_title="Densidad",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        title="Distribución S_c — CHG (2015-2024) vs CHE (2025-2026)",
    )
    st.plotly_chart(fig_kde, use_container_width=True)

    # Tabla resumen intercuencas
    summary_rows = []
    for cuenca_id in ["CHG", "CHE"]:
        embalses_c = [e for e in filtered if EMBALSE_META[e]["cuenca"] == cuenca_id]
        if not embalses_c:
            continue
        sc_all = pd.concat([filtered[e]["S_c"] for e in embalses_c]).dropna()
        summary_rows.append({
            "Confederación": cuenca_id,
            "Embalses": len(embalses_c),
            "Observaciones": f"{len(sc_all):,}",
            "S_c medio": f"{sc_all.mean():.4f}",
            "S_c std": f"{sc_all.std():.4f}",
            "S_c mín": f"{sc_all.min():.4f}",
            "S_c máx": f"{sc_all.max():.4f}",
        })
    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.info("**KS test:** stat=0.333 · p≈0 (n=365,858 — potencia extrema, Δµ=0.051 "
            "operacionalmente irrelevante). Hipótesis confirmada: el modelo opera "
            "correctamente en CHE sin recalibración.", icon="📊")


# ══════════════════════════════════════════════════════════════════════════════
# VISTA 7 — Panel AEMET (opcional)
# ══════════════════════════════════════════════════════════════════════════════
if aemet_on:
    st.markdown("### 🌦️ Observaciones AEMET — Tiempo real")
    st.caption("Estaciones más cercanas a cada embalse · TTL cache: 5 min")

    with st.spinner("Consultando AEMET OpenData..."):
        obs_list = load_aemet()

    if obs_list:
        obs_df = pd.DataFrame([o for o in obs_list if o])
        if not obs_df.empty:
            # Filtrar por embalses seleccionados
            obs_df = obs_df[obs_df["embalse_id"].isin(selected_embalses)]
            obs_df["Embalse"] = obs_df["embalse_id"].map(
                lambda x: EMBALSE_META.get(x, {}).get("label", x))

            col_a1, col_a2, col_a3 = st.columns(3)
            for i, (_, row) in enumerate(obs_df.iterrows()):
                col = [col_a1, col_a2, col_a3][i % 3]
                with col:
                    st.markdown(f"**{row['Embalse']}**")
                    st.caption(f"Estación: {row.get('estacion', '?')} · {row.get('ts_aemet', '')}")
                    m1, m2 = st.columns(2)
                    prec = row.get("precip_mm")
                    temp = row.get("temp_c")
                    m1.metric("Precipitación", f"{prec:.1f} mm" if prec is not None else "N/A")
                    m2.metric("Temperatura",   f"{temp:.1f} °C" if temp is not None else "N/A")
    else:
        st.warning("Sin datos AEMET disponibles en este momento. "
                   "Verifica AEMET_API_KEY en .env o inténtalo en unos minutos.")
        st.caption("El servidor AEMET devuelve errores 500 de forma intermitente fuera de horario.")


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "KAIRI-SIO v2.0 · "
    "Kent Valera Chirinos (Analista de Datos) · "
    "2026-03-13"
)