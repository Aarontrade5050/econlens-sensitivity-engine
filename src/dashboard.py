import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl
import plotly.express as px
import streamlit as st

from src.arquetipos import ARCHETYPE_THRESHOLDS
from src.database import load_aggregation, load_dim_partida, load_results
from src.narratives import add_narratives

DB_PATH = Path("data/processed/econolens.duckdb")

# Configuración de página limpia y profesional
st.set_page_config(
    page_title="EconoLens — Inteligencia Arancelaria",
    page_icon="📊",
    layout="wide",
)

# Estilo global mínimo mediante Markdown (Mejora fuentes y contraste de pestañas)
st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: #1e293b;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #334155;
    }
    div[data-testid="stNotification"] {
        border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("EconoLens — Motor de Inteligencia Arancelaria")
st.caption("Análisis de Importaciones Perú–USA 2025 | Fuente: SUNAT")

# -----------------------------------------------------------------------
# Carga de datos (cacheado)
# -----------------------------------------------------------------------

@st.cache_data
def get_ise_data() -> pl.DataFrame:
    return load_results(DB_PATH)


@st.cache_data
def get_dim_partida() -> pl.DataFrame:
    return load_dim_partida(DB_PATH)


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
# Filtro principal: navegador arancelario en cascada (5 niveles)
# -----------------------------------------------------------------------
hs_available_10d = sorted(df_ise["hs_code"].unique().to_list())
hs_available_6d = {h[:6] for h in hs_available_10d}

dim_full = get_dim_partida()
dim = (
    dim_full.filter(pl.col("subpartida_6d").is_in(list(hs_available_6d)))
    if not dim_full.is_empty()
    else pl.DataFrame()
)

with st.container(border=True):
    if dim.is_empty():
        # Fallback: selector simple si dim_partida aún no está en la DB
        selected_hs = st.selectbox("**Partida Arancelaria**", hs_available_10d)
    else:
        st.markdown("**Navegador Arancelario HS**")
        r1_l, r1_r = st.columns([2, 3])
        r2_1, r2_2, r2_3 = st.columns(3)

        # Nivel 1 — Sección
        with r1_l:
            sec_rows = (
                dim.select(["seccion", "desc_seccion"]).unique().sort("seccion").to_dicts()
            )
            sec_map = {r["seccion"]: f"Sección {r['seccion']} — {r['desc_seccion']}" for r in sec_rows}
            selected_seccion = st.selectbox(
                "GRUPO RAÍZ: SECCIÓN",
                options=list(sec_map.keys()),
                format_func=lambda k, m=sec_map: m[k],
            )

        # Nivel 2 — Capítulo (filtrado por Sección)
        with r1_r:
            cap_rows = (
                dim.filter(pl.col("seccion") == selected_seccion)
                .select(["capitulo", "desc_capitulo"]).unique().sort("capitulo").to_dicts()
            )
            cap_map = {r["capitulo"]: f"{r['capitulo']} — {r['desc_capitulo']}" for r in cap_rows}
            selected_cap = st.selectbox(
                "NIVEL 1: CAPÍTULO",
                options=list(cap_map.keys()),
                format_func=lambda k, m=cap_map: m[k],
            )

        # Nivel 3 — Partida 4d (filtrada por Capítulo)
        with r2_1:
            par_rows = (
                dim.filter(pl.col("capitulo") == selected_cap)
                .select(["partida_4d", "desc_partida"]).unique().sort("partida_4d").to_dicts()
            )
            par_map = {r["partida_4d"]: f"{r['partida_4d']} — {r['desc_partida']}" for r in par_rows}
            selected_partida = st.selectbox(
                "NIVEL 2: PARTIDA (4D)",
                options=list(par_map.keys()),
                format_func=lambda k, m=par_map: m[k],
            )

        # Nivel 4 — Subpartida 6d (filtrada por Partida)
        with r2_2:
            sub_rows = (
                dim.filter(pl.col("partida_4d") == selected_partida)
                .select(["subpartida_6d", "desc_subpartida"]).unique().sort("subpartida_6d").to_dicts()
            )
            sub_map = {r["subpartida_6d"]: f"{r['subpartida_6d']} — {r['desc_subpartida']}" for r in sub_rows}
            selected_sub = st.selectbox(
                "NIVEL 3: SUBPARTIDA (6D)",
                options=list(sub_map.keys()),
                format_func=lambda k, m=sub_map: m[k],
            )

        # Nivel 5 — Código 10d (viene de df_ise filtrado por los primeros 6 dígitos)
        with r2_3:
            hs10_opts = [h for h in hs_available_10d if h[:6] == selected_sub]
            if not hs10_opts:
                st.warning("Sin datos ISE para esta subpartida.")
                selected_hs = hs_available_10d[0]
            else:
                selected_hs = st.selectbox("NIVEL 4: CÓDIGO (10D)", options=hs10_opts)

        # Breadcrumb
        st.caption(
            f"**Filtro Activo:** Sección {selected_seccion} "
            f"→ Cap. {selected_cap} "
            f"→ {selected_partida} "
            f"→ {selected_sub} "
            f"→ `{selected_hs}`"
        )

# Arquetipo del producto seleccionado
_ARCHETYPE_COLORS = {
    "COMMODITY":     "#10b981",
    "BIEN_DURADERO": "#38bdf8",
    "PERECEDERO":    "#f59e0b",
    "ESTANDAR":      "#94a3b8",
}
_ARCHETYPE_LABELS = {
    "COMMODITY":     "COMMODITY — Cereales / Combustibles / Minerales",
    "BIEN_DURADERO": "BIEN DURADERO — Maquinaria / Electrónicos / Vehículos",
    "PERECEDERO":    "PERECEDERO — Carnes / Lácteos / Frutas / Hortalizas",
    "ESTANDAR":      "ESTÁNDAR — Consumo general",
}

# Datos filtrados para la partida seleccionada
df_hs = df_ise.filter(pl.col("hs_code") == selected_hs)

arquetipo = (
    df_hs["arquetipo_economico"][0]
    if not df_hs.is_empty() and "arquetipo_economico" in df_hs.columns
    else "ESTANDAR"
)
_arc_color = _ARCHETYPE_COLORS.get(arquetipo, "#94a3b8")
_arc_label = _ARCHETYPE_LABELS.get(arquetipo, arquetipo)
_thresholds = ARCHETYPE_THRESHOLDS.get(arquetipo, ARCHETYPE_THRESHOLDS["ESTANDAR"])

st.markdown(
    f'<p style="margin-top:4px;font-size:0.82em;">Arquetipo económico: '
    f'<span style="color:{_arc_color};font-weight:700;'
    f'background:#1e293b;padding:2px 8px;border-radius:4px;'
    f'border:1px solid {_arc_color}33">{_arc_label}</span> '
    f'&nbsp;·&nbsp; Umbrales activos: volumen <b>±{_thresholds["volume"]:.0f}%</b> '
    f'/ precio <b>±{_thresholds["price"]:.0f}%</b></p>',
    unsafe_allow_html=True,
)

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
# 4 Pestañas principales
# -----------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Competidores e Importadores",
    "🗺️ Precios, Rutas y Adquisición",
    "⏳ Evolución Temporal",
    "⚠️ Alertas ISE",
])

# =======================================================================
# TAB 1 — Competidores
# =======================================================================
with tab1:
    if ms_df.is_empty():
        st.info("No hay datos de market share. Ejecuta `python run.py` para generarlos.")
    else:
        ms_sorted = ms_df.sort("volumen_total", descending=True)
        top_row = ms_sorted.row(0, named=True)
        total_vol = ms_sorted["volumen_total"].sum()
        top3_pct = ms_sorted.head(3)["participacion_pct"].sum()

        # Métricas principales encapsuladas estéticamente
        c1, c2, c3 = st.columns(3)
        c1.metric("Importador Líder", f"🏆 {top_row['actor']}")
        c2.metric("Volumen Total Registrado", f"{total_vol:,.0f} kg")
        c3.metric("Concentración Top 3", f"{top3_pct:.1f}%")

        st.write("") # Espaciador
        
        with st.container(border=True):
            st.subheader("Cuota de Mercado por Importador")
            
            # Formateo de DataFrame nativo de Streamlit con barras de progreso integradas (Adiós al costoso bucle for)
            df_ms_display = (
                ms_sorted.select([
                    pl.col("actor").alias("Importador"),
                    pl.col("volumen_total").alias("Volumen Acumulado (kg)"),
                    pl.col("participacion_pct").alias("% Participación"),
                    pl.col("participacion_pct").alias("Barra de Cuota")
                ]).to_pandas()
            )
            
            st.dataframe(
                df_ms_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Volumen Acumulado (kg)": st.column_config.NumberColumn(format="%d kg"),
                    "% Participación": st.column_config.NumberColumn(format="%.1f%%"),
                    "Barra de Cuota": st.column_config.ProgressColumn(
                        "Progreso",
                        help="Representación gráfica de la cuota de mercado",
                        format=" ",
                        min_value=0,
                        max_value=100
                    )
                }
            )

# =======================================================================
# TAB 2 — Precios y Rutas
# =======================================================================
with tab2:
    col_left, col_right = st.columns(2)

    with col_left:
        with st.container(border=True):
            st.subheader("Precio por País de Adquisición")
            if country_df.is_empty():
                st.info("Sin datos de países.")
            else:
                display_country = (
                    country_df
                    .sort("volumen_total", descending=True)
                    .select(["pais", "volumen_total", "precio_promedio"])
                    .rename({"pais": "País", "volumen_total": "Volumen (kg)", "precio_promedio": "Precio FOB USD/kg"})
                )
                st.dataframe(
                    display_country.to_pandas(), 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Volumen (kg)": st.column_config.NumberColumn(format="%d kg"),
                        "Precio FOB USD/kg": st.column_config.NumberColumn(format="$ %.4f")
                    }
                )

    with col_right:
        with st.container(border=True):
            st.subheader("Precio por Aduana de Ingreso")
            if route_df.is_empty():
                st.info("Sin datos de aduanas.")
            else:
                display_route = (
                    route_df
                    .sort("volumen_total", descending=True)
                    .select(["aduana", "volumen_total", "precio_promedio"])
                    .rename({"aduana": "Aduana", "volumen_total": "Volumen (kg)", "precio_promedio": "Precio FOB USD/kg"})
                )
                st.dataframe(
                    display_route.to_pandas(), 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Volumen (kg)": st.column_config.NumberColumn(format="%d kg"),
                        "Precio FOB USD/kg": st.column_config.NumberColumn(format="$ %.4f")
                    }
                )

    st.write("")
    
    with st.container(border=True):
        st.subheader("Spread de Precios Mín/Máx por Importador")
        if spread_df.is_empty():
            st.info("Sin datos de spreads.")
        else:
            display_spread = (
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
            st.dataframe(
                display_spread.to_pandas(), 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "Precio Mín (USD/kg)": st.column_config.NumberColumn(format="$ %.4f"),
                    "Precio Máx (USD/kg)": st.column_config.NumberColumn(format="$ %.4f"),
                    "Spread (%)": st.column_config.NumberColumn(format="%.2f%%")
                }
            )

# =======================================================================
# TAB 3 — Evolución Temporal
# =======================================================================
with tab3:
    col_left, col_right = st.columns([1, 1.2])

    with col_left:
        with st.container(border=True):
            st.subheader("Empresas Activas por Período")
            if entities_df.is_empty():
                st.info("Sin datos temporales.")
            else:
                ent_sorted = entities_df.sort("periodo")
                
                if ent_sorted["periodo"].dtype in [pl.Date, pl.Datetime]:
                    ent_sorted = ent_sorted.with_columns(pl.col("periodo").dt.strftime("%Y-%m-%d"))
                else:
                    ent_sorted = ent_sorted.with_columns(pl.col("periodo").str.slice(0, 10))

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
                
                st.dataframe(
                    ent_with_trend.to_pandas(), 
                    use_container_width=True, 
                    hide_index=True
                )

    with col_right:
        with st.container(border=True):
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
                
                df_plot = vol_price.to_pandas()

                # Configuración compartida de Plotly (Diseño Ultra-Limpio)
                layout_config = dict(
                    height=180,
                    margin=dict(l=40, r=15, t=10, b=10),
                    hovermode="x unified",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False, title_text=""),
                    yaxis=dict(showgrid=True, gridcolor="#334155")
                )

                # Gráfico 1: Volumen (Azul Neón sutil)
                fig = px.line(df_plot, x="periodo", y="Volumen Total (kg)", markers=True)
                fig.update_traces(line=dict(width=3, color="#38bdf8"), marker=dict(size=6))
                fig.update_layout(**layout_config)
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

                # Gráfico 2: Precio (Ámbar)
                fig2 = px.line(df_plot, x="periodo", y="Precio Ponderado (USD/kg)", markers=True)
                fig2.update_traces(line=dict(width=3, color="#f59e0b"), marker=dict(size=6))
                fig2.update_layout(**layout_config)
                st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

# =======================================================================
# TAB 4 — Alertas ISE
# =======================================================================
with tab4:
    st.subheader("Alertas de Shocks Económicos e Índice de Sensibilidad (ISE)")
    st.caption(
        f"Detección automática calibrada para arquetipo "
        f"**{arquetipo}** — umbrales: volumen ±{_thresholds['volume']:.0f}% / "
        f"precio ±{_thresholds['price']:.0f}%"
    )
    st.write("")

    shocks = df_hs.filter(pl.col("shock_compuesto_flag") == 1)

    if shocks.is_empty():
        st.success("✅ No se detectaron shocks para esta partida en el período analizado.")
    else:
        shocks_with_narratives = add_narratives(shocks.sort("ise_score", descending=True))

        for row in shocks_with_narratives.to_dicts():
            periodo_str = str(row["periodo"])[:7]
            actor = row.get("actor", "—")
            ise = row["ise_score"]
            narrativa = row.get("narrativa", "")
            arc = row.get("arquetipo_economico", arquetipo)

            tag = f"`{arc}`"
            if ise >= 95.0:
                st.error(f"🚨 **{actor}** — Período: `{periodo_str}` | **ISE: {ise:.1f} (Crítico)** | {tag}\n\n{narrativa}")
            elif ise >= 85.0:
                st.warning(f"⚠️ **{actor}** — Período: `{periodo_str}` | **ISE: {ise:.1f} (Alto)** | {tag}\n\n{narrativa}")
            else:
                st.info(f"💡 **{actor}** — Período: `{periodo_str}` | **ISE: {ise:.1f} (Moderado)** | {tag}\n\n{narrativa}")