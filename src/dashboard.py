import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import polars as pl

from src.database import load_results

DB_PATH = Path("data/processed/econolens.duckdb")

st.set_page_config(
    page_title="EconoLens",
    page_icon="📊",
    layout="wide",
)

st.title("📊 EconoLens — Motor de Sensibilidad Económica")
st.caption("Importaciones Perú–USA 2025 | Fuente: SUNAT")


@st.cache_data
def get_all_data():
    return load_results(DB_PATH)


df_all = get_all_data()

if df_all is None or df_all.is_empty():
    st.error("No hay datos en la base de datos. Corre primero `python run.py`.")
    st.stop()

has_actor = "actor" in df_all.columns

# --- sidebar: filtros ---
with st.sidebar:
    st.header("🔍 Filtros")

    hs_options = sorted(df_all["hs_code"].unique().to_list())
    hs_selected = st.multiselect("Producto (HS Code)", hs_options, default=[])

    actor_options = sorted(df_all["actor"].unique().to_list()) if has_actor else []
    actor_selected = st.multiselect("Importador", actor_options, default=[])

    periodos = sorted(df_all["periodo"].unique().to_list())
    desde = st.selectbox("Desde", periodos, index=0)
    hasta = st.selectbox("Hasta", periodos, index=len(periodos) - 1)

# --- aplicar filtros en memoria ---
df = df_all.filter(
    (pl.col("periodo") >= desde) & (pl.col("periodo") <= hasta)
)

if hs_selected:
    df = df.filter(pl.col("hs_code").is_in(hs_selected))
if actor_selected and has_actor:
    df = df.filter(pl.col("actor").is_in(actor_selected))

# --- métricas resumen ---
ise_counts = (
    df.group_by("ise_nivel")
    .agg(pl.len().alias("n"))
    .to_pandas()
    .set_index("ise_nivel")["n"]
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total registros", df.shape[0])
col2.metric("🔴 Alto", int(ise_counts.get("Alto", 0)))
col3.metric("🟡 Medio", int(ise_counts.get("Medio", 0)))
col4.metric("🟢 Bajo", int(ise_counts.get("Bajo", 0)))

st.divider()

# --- preparar datos ordenados una sola vez ---
df_sorted = df.sort("periodo")
df_pd = df_sorted.to_pandas()

# --- gráfico ISE en el tiempo ---
st.subheader("📈 ISE en el tiempo")

if df.is_empty():
    st.info("Selecciona filtros para ver el gráfico.")
else:
    group_col = "actor" if has_actor and not df["actor"].is_null().all() else "hs_code"
    fig = px.line(
        df_pd,
        x="periodo",
        y="ise_score",
        color=group_col,
        markers=True,
        labels={"ise_score": "ISE Score", "periodo": "Período", group_col: group_col.capitalize()},
    )
    fig.update_layout(yaxis_range=[0, 100], height=400)
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- tabla de resultados ---
st.subheader("📋 Tabla de resultados")

display_cols = [c for c in [
    "periodo", "hs_code", "actor", "volumen", "precio",
    "var_pct_volumen_mensual", "var_pct_precio_mensual",
    "volatilidad_precio_6m", "elasticidad_simple",
    "shock_compuesto_flag", "ise_score", "ise_nivel",
] if c in df.columns]

st.dataframe(
    df_pd[display_cols],
    use_container_width=True,
    height=400,
)
