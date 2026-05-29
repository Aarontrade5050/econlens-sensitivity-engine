import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl
import plotly.express as px
import streamlit as st

from src.database import load_aggregation, load_results
from src.narratives import add_narratives

DB_PATH = Path("data/processed/econolens.duckdb")

st.set_page_config(
    page_title="EconoLens",
    page_icon="📊",
    layout="wide",
)

st.title("EconoLens — Motor de Inteligencia Arancelaria")
st.caption("Análisis de Importaciones Perú–USA 2025 | Fuente: SUNAT")

# -----------------------------------------------------------------------
# Carga de datos (cacheado)
# -----------------------------------------------------------------------

@st.cache_data
def get_ise_data() -> pl.DataFrame:
    return load_results(DB_PATH)


@st.cache_data
def get_all_aggregations() -> dict[str, pl.DataFrame]:
    tables = ["market_share", "price_by_country", "price_by_route", "price_spread", "entities_over_time"]
    return {t: load_aggregation(DB_PATH, t) for t in tables}


df_ise = get_ise_data()

if df_ise is None or df_ise.is_empty():
    st.error("No hay datos en la base de datos. Corre primero `python run.py`.")
    st.stop()

aggs = get_all_aggregations()

# -----------------------------------------------------------------------
# Filtro principal: selector de partida arancelaria
# -----------------------------------------------------------------------

hs_options = sorted(df_ise["hs_code"].unique().to_list())
selected_hs = st.selectbox("**Partida Arancelaria**", hs_options)

st.divider()

# Datos filtrados para la partida seleccionada
df_hs = df_ise.filter(pl.col("hs_code") == selected_hs)

def _filter(table: str) -> pl.DataFrame:
    df = aggs.get(table, pl.DataFrame())
    if df.is_empty() or "hs_code" not in df.columns:
        return pl.DataFrame()
    return df.filter(pl.col("hs_code") == selected_hs)


ms_df = _filter("market_share")
country_df = _filter("price_by_country")
route_df = _filter("price_by_route")
spread_df = _filter("price_spread")
entities_df = _filter("entities_over_time")

# -----------------------------------------------------------------------
# 4 Pestañas
# -----------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs([
    "1. Competidores e Importadores",
    "2. Precios, Rutas y Adquisición",
    "3. Evolución Temporal",
    "4. Alertas ISE",
])

# ===========================
# TAB 1 — Competidores
# ===========================
with tab1:
    if ms_df.is_empty():
        st.info("No hay datos de market share. Ejecuta `python run.py` para generarlos.")
    else:
        ms_sorted = ms_df.sort("volumen_total", descending=True)
        top_row = ms_sorted.row(0, named=True)
        total_vol = ms_sorted["volumen_total"].sum()
        top3_pct = ms_sorted.head(3)["participacion_pct"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Importador Líder", top_row["actor"])
        c2.metric("Volumen Total Registrado", f"{total_vol:,.0f} kg")
        c3.metric("Concentración Top 3", f"{top3_pct:.1f}%")

        st.subheader("Cuota de Mercado por Importador")

        header = st.columns([4, 2, 1, 3])
        header[0].markdown("**Importador**")
        header[1].markdown("**Volumen Acum.**")
        header[2].markdown("**%**")
        header[3].markdown("**Participación**")
        st.divider()

        for row in ms_sorted.to_dicts():
            cols = st.columns([4, 2, 1, 3])
            cols[0].write(row["actor"])
            cols[1].write(f"{row['volumen_total']:,.0f} kg")
            cols[2].write(f"{row['participacion_pct']:.1f}%")
            cols[3].progress(min(row["participacion_pct"] / 100, 1.0))

# ===========================
# TAB 2 — Precios y Rutas
# ===========================
with tab2:
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Precio por País de Adquisición")
        if country_df.is_empty():
            st.info("Sin datos. Ejecuta `python run.py`.")
        else:
            display = (
                country_df
                .sort("volumen_total", descending=True)
                .select(["pais", "volumen_total", "precio_promedio"])
                .rename({"pais": "País", "volumen_total": "Volumen (kg)", "precio_promedio": "Precio FOB USD/kg"})
            )
            st.dataframe(display.to_pandas(), use_container_width=True, hide_index=True)

    with col_right:
        st.subheader("Precio por Aduana de Ingreso")
        if route_df.is_empty():
            st.info("Sin datos. Ejecuta `python run.py`.")
        else:
            display = (
                route_df
                .sort("volumen_total", descending=True)
                .select(["aduana", "volumen_total", "precio_promedio"])
                .rename({"aduana": "Aduana", "volumen_total": "Volumen (kg)", "precio_promedio": "Precio FOB USD/kg"})
            )
            st.dataframe(display.to_pandas(), use_container_width=True, hide_index=True)

    st.subheader("Spread de Precios Mín/Máx por Importador")
    if spread_df.is_empty():
        st.info("Sin datos. Ejecuta `python run.py`.")
    else:
        display = (
            spread_df
            .sort("spread_pct", descending=True)
            .select(["actor", "precio_min", "precio_max", "spread_pct"])
            .rename({
                "actor": "Importador",
                "precio_min": "Precio Mín (USD/kg)",
                "precio_max": "Precio Máx (USD/kg)",
                "spread_pct": "Spread (%)",
            })
        )
        st.dataframe(display.to_pandas(), use_container_width=True, hide_index=True)

# ===========================
# TAB 3 — Evolución Temporal
# ===========================
with tab3:
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Empresas Activas por Período")
        if entities_df.is_empty():
            st.info("Sin datos. Ejecuta `python run.py`.")
        else:
            ent_sorted = entities_df.sort("periodo")
            prev = ent_sorted["n_actores"].shift(1)
            curr = ent_sorted["n_actores"]
            ent_with_trend = ent_sorted.with_columns(
                pl.when(curr > prev).then(pl.lit("▲ Expansión"))
                .when(curr < prev).then(pl.lit("▼ Consolidación"))
                .otherwise(pl.lit("— Estable"))
                .alias("Tendencia")
            ).rename({"periodo": "Mes", "n_actores": "Empresas Activas"}).select(
                ["Mes", "Empresas Activas", "Tendencia"]
            )
            st.dataframe(ent_with_trend.to_pandas(), use_container_width=True, hide_index=True)

    with col_right:
        st.subheader("Evolución de Volumen y Precio")
        if df_hs.is_empty():
            st.info("Sin datos para esta partida.")
        else:
            vol_price = (
                df_hs.group_by("periodo")
                .agg([
                    pl.col("volumen").sum().alias("Volumen Total (kg)"),
                    (
                        (pl.col("precio") * pl.col("volumen")).sum()
                        / pl.col("volumen").sum()
                    ).round(4).alias("Precio Ponderado (USD/kg)"),
                ])
                .sort("periodo")
            )
            fig = px.line(
                vol_price.to_pandas(),
                x="periodo",
                y="Volumen Total (kg)",
                markers=True,
                labels={"periodo": "Período"},
            )
            fig.update_layout(height=250)
            st.plotly_chart(fig, use_container_width=True)

            fig2 = px.line(
                vol_price.to_pandas(),
                x="periodo",
                y="Precio Ponderado (USD/kg)",
                markers=True,
                color_discrete_sequence=["#f59e0b"],
                labels={"periodo": "Período"},
            )
            fig2.update_layout(height=250)
            st.plotly_chart(fig2, use_container_width=True)

# ===========================
# TAB 4 — Alertas ISE
# ===========================
with tab4:
    st.subheader("Alertas de Shocks Económicos e Índice de Sensibilidad (ISE)")
    st.caption("Detección automática de movimientos fuera de lo común (shocks de volumen o quiebres de precios).")

    shocks = df_hs.filter(pl.col("shock_compuesto_flag") == 1)

    if shocks.is_empty():
        st.success("No se detectaron shocks para esta partida en el período analizado.")
    else:
        shocks_with_narratives = add_narratives(shocks.sort("ise_score", descending=True))
        for row in shocks_with_narratives.to_dicts():
            periodo_str = str(row["periodo"])[:7]
            actor = row.get("actor", "—")
            ise = row["ise_score"]
            narrativa = row.get("narrativa", "")
            st.error(
                f"**{actor}** — {periodo_str} | ISE Score: {ise:.1f}  \n{narrativa}"
            )
