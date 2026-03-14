"""
KAIRI-SIO — dashboard_lite.py
Versión mínima para Streamlit Cloud.
Solo carga parquets scored y muestra las vistas principales.
Sin imports de src/, sin AEMET, sin scipy.
"""

from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="KAIRI-SIO · Integridad Hidrológica",
    page_icon="💧",
    layout="wide",
)

# ── Constantes ────────────────────────────────────────────────────────────────
COLORS = {
    "CERTIFICADA": "#2ecc71",
    "DEGRADADA":   "#f39c12",
    "VETADA":      "#e74c3c",
}

ROOT = Path(__file__).resolve().parent

EMBALSE_META = {
    "E32_VADOMOJON":   {"label": "E32 · Vado Mojón",    "cuenca": "CHG"},
    "E33_SRRA_BOYERA": {"label": "E33 · Sierra Boyera", "cuenca": "CHG"},
    "E37_BEMBEZAR":    {"label": "E37 · Bembézar",      "cuenca": "CHG"},
    "ITOIZ":           {"label": "Itoiz",                "cuenca": "CHE"},
    "MEQUINENZA":      {"label": "Mequinenza",           "cuenca": "CHE"},
    "YESA":            {"label": "Yesa",                 "cuenca": "CHE"},
}

PATHS = {
    "E32_VADOMOJON":   ROOT / "data/analytic/E32_VADOMOJON_scored.parquet",
    "E33_SRRA_BOYERA": ROOT / "data/analytic/E33_SRRA_BOYERA_scored.parquet",
    "E37_BEMBEZAR":    ROOT / "data/analytic/E37_BEMBEZAR_scored.parquet",
    "ITOIZ":           ROOT / "data/analytic/ebro/ITOIZ_scored.parquet",
    "MEQUINENZA":      ROOT / "data/analytic/ebro/MEQUINENZA_scored.parquet",
    "YESA":            ROOT / "data/analytic/ebro/YESA_scored.parquet",
}


@st.cache_data(show_spinner="Cargando datos...")
def load_parquet(eid: str) -> pd.DataFrame:
    path = PATHS[eid]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["ts_station"] = pd.to_datetime(df["ts_station"])
    df["regime"] = df["quality_flag"] if "quality_flag" in df.columns else "DEGRADADA"
    df["embalse_id"] = eid
    df["cuenca"] = EMBALSE_META[eid]["cuenca"]
    return df


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("💧 KAIRI-SIO")
    st.caption("Integridad de Señal Hidrológica · v1.1")
    st.divider()

    cuenca_sel = st.radio("Confederación",
                          ["CHG · Guadalquivir", "CHE · Ebro", "Ambas"])
    st.divider()

    if cuenca_sel == "CHG · Guadalquivir":
        eid_options = ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"]
    elif cuenca_sel == "CHE · Ebro":
        eid_options = ["ITOIZ", "MEQUINENZA", "YESA"]
    else:
        eid_options = list(EMBALSE_META.keys())

    selected = st.multiselect(
        "Embalses", eid_options, default=eid_options,
        format_func=lambda x: EMBALSE_META[x]["label"],
    )
    st.divider()
    st.caption("**Modelo:** kairi-sio-sc-v1.0.0")
    st.caption("**Datos:** SAIH CHG 2015–2024 · CHE 2025–2026")
    st.caption("**GitHub:** kentvalerach/kairi-sio")


# ── Cargar datos ──────────────────────────────────────────────────────────────
if not selected:
    st.warning("Selecciona al menos un embalse.")
    st.stop()

dfs = {}
for eid in selected:
    df = load_parquet(eid)
    if not df.empty:
        dfs[eid] = df

if not dfs:
    st.error("No se encontraron datos. Verifica que los parquets están en data/analytic/")
    st.stop()

all_data = pd.concat(dfs.values(), ignore_index=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 💧 KAIRI-SIO · Dashboard de Integridad Hidrológica")
st.caption("Sistema de Verificación de Integridad de Señal Hidrológica · CHG + CHE")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────
n_total = len(all_data)
n_cert  = (all_data["regime"] == "CERTIFICADA").sum()
n_vet   = (all_data["regime"] == "VETADA").sum()
mean_sc = all_data["S_c"].mean()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Observaciones",  f"{n_total:,}")
k2.metric("CERTIFICADA",    f"{n_cert/n_total*100:.1f}%")
k3.metric("VETADA",         f"{n_vet/n_total*100:.1f}%", delta_color="inverse")
k4.metric("S_c medio",      f"{mean_sc:.4f}")
st.divider()

# ── Vista 1 — Distribución ────────────────────────────────────────────────────
st.markdown("### 📊 Distribución de regímenes por embalse")
dist_rows = []
for eid, df in dfs.items():
    n = len(df)
    for regime in ["CERTIFICADA", "DEGRADADA", "VETADA"]:
        dist_rows.append({
            "Embalse":    EMBALSE_META[eid]["label"],
            "Cuenca":     EMBALSE_META[eid]["cuenca"],
            "Régimen":    regime,
            "Porcentaje": (df["regime"] == regime).sum() / n * 100,
        })

dist_df = pd.DataFrame(dist_rows)
fig = px.bar(dist_df, x="Embalse", y="Porcentaje", color="Régimen",
             color_discrete_map=COLORS, barmode="stack", height=360,
             text="Porcentaje")
fig.update_traces(texttemplate="%{text:.1f}%", textposition="inside")
fig.update_layout(margin=dict(t=20, b=10),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02),
                  yaxis_title="% observaciones", xaxis_title="")
st.plotly_chart(fig, use_container_width=True)

# ── Vista 2 — Serie temporal ──────────────────────────────────────────────────
st.markdown("### 📈 Serie temporal S_c")
resample = st.select_slider("Resolución",
                             options=["1W", "1ME", "3ME"],
                             value="1ME",
                             format_func=lambda x: {"1W": "Semanal",
                                                     "1ME": "Mensual",
                                                     "3ME": "Trimestral"}[x])
fig_ts = go.Figure()
for eid, df in dfs.items():
    df_r = df.set_index("ts_station")["S_c"].resample(resample).mean().reset_index()
    fig_ts.add_trace(go.Scatter(x=df_r["ts_station"], y=df_r["S_c"],
                                name=EMBALSE_META[eid]["label"],
                                mode="lines", line=dict(width=2)))
fig_ts.add_hline(y=0.85, line_dash="dash", line_color="#2ecc71",
                 annotation_text="CERTIFICADA (0.85)")
fig_ts.add_hline(y=0.50, line_dash="dash", line_color="#e74c3c",
                 annotation_text="VETADA (0.50)")
fig_ts.update_layout(height=360, margin=dict(t=20, b=10),
                      yaxis=dict(range=[0.5, 1.0], title="S_c"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
st.plotly_chart(fig_ts, use_container_width=True)

# ── Vista 3 — Heatmap sub-scores ─────────────────────────────────────────────
st.markdown("### 🌡️ Mapa de calor sub-scores")
subscores = ["S_f", "S_l", "S_t", "S_h", "S_c"]
hm_rows = []
for eid, df in dfs.items():
    row = {"Embalse": EMBALSE_META[eid]["label"]}
    for s in subscores:
        if s in df.columns:
            row[s] = round(df[s].mean(), 4)
    hm_rows.append(row)

hm_df = pd.DataFrame(hm_rows).set_index("Embalse")
fig_hm = px.imshow(hm_df, color_continuous_scale="RdYlGn",
                   zmin=0.7, zmax=1.0, text_auto=".4f",
                   aspect="auto", height=max(200, 60*len(hm_rows)+80))
fig_hm.update_layout(margin=dict(t=20, b=10))
st.plotly_chart(fig_hm, use_container_width=True)

# ── Vista 4 — Tabla resumen ───────────────────────────────────────────────────
st.markdown("### 📋 Resumen por embalse")
summary = []
for eid, df in dfs.items():
    summary.append({
        "Embalse":   EMBALSE_META[eid]["label"],
        "Cuenca":    EMBALSE_META[eid]["cuenca"],
        "N":         f"{len(df):,}",
        "S_c medio": f"{df['S_c'].mean():.4f}",
        "CERT%":     f"{(df['regime']=='CERTIFICADA').mean()*100:.1f}%",
        "DEGR%":     f"{(df['regime']=='DEGRADADA').mean()*100:.1f}%",
        "VETO%":     f"{(df['regime']=='VETADA').mean()*100:.1f}%",
    })
st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption("KAIRI-SIO v1.1 · Reymar · Kent Valera Chirinos · 2026-03-14 · "
           "[GitHub](https://github.com/kentvalerach/kairi-sio)")
