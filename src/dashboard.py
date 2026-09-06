import io
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
_DIM_PARTIDA_CSV = Path(__file__).parent.parent / "resources" / "dim_partida.csv"

# Configuración de página limpia y profesional
st.set_page_config(
    page_title="EconoLens — Inteligencia Arancelaria",
    page_icon="📊",
    layout="wide",
)

# -----------------------------------------------------------------------
# Selector de módulo — pantalla de entrada
#
# La app arranca preguntando qué análisis se quiere, no pidiendo un archivo.
# Freemium lee artefactos ya precomputados; premium corre el motor ISE sobre
# el dataset transaccional que suba el usuario.
# -----------------------------------------------------------------------

def _render_landing() -> None:
    st.markdown("""
        <style>
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.landing-card) {
            background:#111c30; border:1px solid #1e293b; border-radius:12px; padding:6px;
        }
        .landing-card { padding: 22px 24px 8px; }
        .landing-card h3 { color:#ffffff !important; margin:0 0 6px; font-size:20px; }
        .landing-card .tag { font-size:10px; letter-spacing:1.6px; text-transform:uppercase;
            font-weight:700; }
        .landing-card p { color:#94a3b8; font-size:14px; line-height:1.6; margin:10px 0 0; }
        .landing-card li { color:#94a3b8; font-size:13.5px; line-height:1.7; }
        </style>
    """, unsafe_allow_html=True)

    st.title("EconoLens")
    st.caption("Plataforma de inteligencia de comercio exterior")
    st.write("")

    izq, centro, der = st.columns(3, gap="large")

    with izq, st.container():
        st.markdown("""
            <div class="landing-card">
              <div class="tag" style="color:#38bdf8">Acceso abierto</div>
              <h3>📊 Comex Latam</h3>
              <p>Estadísticas de comercio exterior de 9 países de América Latina,
                 2024–2025, a nivel de subpartida de 6 dígitos.</p>
              <ul>
                <li>Crecimiento interanual por país y producto</li>
                <li>Participación de cada socio comercial</li>
                <li>Concentración de origen y sustitución de proveedores</li>
              </ul>
            </div>
        """, unsafe_allow_html=True)
        if st.button("Entrar a Comex Latam", use_container_width=True, type="primary"):
            st.session_state["view_mode"] = "freemium"
            st.rerun()

    with centro, st.container():
        st.markdown("""
            <div class="landing-card">
              <div class="tag" style="color:#4ade80">Manifiestos Perú</div>
              <h3>🔎 Buscador de manifiestos</h3>
              <p>Quién mueve qué en los manifiestos de carga del Perú,
                 aéreos y marítimos, de entrada y de salida.</p>
              <ul>
                <li>Busca una empresa, naviera, agente, puerto o partida</li>
                <li>Mira con quién trabaja y cuánto pesa en su mercado</li>
                <li>Arma tu propia tabla cuando la ficha no alcanza</li>
              </ul>
            </div>
        """, unsafe_allow_html=True)
        if st.button("Entrar al Buscador", use_container_width=True):
            st.session_state["view_mode"] = "manifiestos"
            st.rerun()

    with der, st.container():
        st.markdown("""
            <div class="landing-card">
              <div class="tag" style="color:#ff8c00">Análisis detallado</div>
              <h3>🔍 Motor ISE</h3>
              <p>Análisis de riesgo estructural sobre data transaccional propia,
                 a nivel de importador y partida de 10 dígitos.</p>
              <ul>
                <li>Índice de Sensibilidad Económica por actor</li>
                <li>Elasticidad precio-volumen y volatilidad</li>
                <li>Alertas de shock y matriz de proveedores</li>
              </ul>
            </div>
        """, unsafe_allow_html=True)
        if st.button("Entrar al Motor ISE", use_container_width=True):
            st.session_state["view_mode"] = "premium"
            st.rerun()


def _boton_volver() -> None:
    if st.sidebar.button("← Cambiar de módulo", use_container_width=True):
        st.session_state["view_mode"] = None
        st.rerun()


if st.session_state.get("view_mode") is None:
    _render_landing()
    st.stop()

if st.session_state["view_mode"] == "freemium":
    from src.dashboard_freemium import render as _render_freemium

    _boton_volver()
    _render_freemium()
    st.stop()

if st.session_state["view_mode"] == "manifiestos":
    from src.dashboard_manifiestos import render as _render_manifiestos

    _boton_volver()
    _render_manifiestos()
    st.stop()

_boton_volver()

# -----------------------------------------------------------------------
# Modo premium — motor ISE (flujo original, sin cambios)
# -----------------------------------------------------------------------

# Estilo global mínimo mediante Markdown (Mejora fuentes y contraste de pestañas)
# Estilo global optimizado para Modo Oscuro Integrado (Datasur Palette)
st.markdown("""
    <style>
    /* 1. Rescatar los títulos principales para que sean legibles */
    h1 { 
        color: #ffffff !important; 
        font-weight: 700 !important;
        letter-spacing: -0.025em;
    }
    h3 {
        color: #f1f5f9 !important;
    }
    
    /* 2. Transformación de las métricas (Ajustadas para evitar truncado) */
    div[data-testid="stMetric"] {
        background-color: #111c30 !important; /* Azul noche profundo integrado al fondo */
        padding: 20px !important;
        border-radius: 10px !important;
        border: 1px solid #1e293b !important; /* Borde sutil para dar volumen */
        border-left: 4px solid #ff8c00 !important; /* Acento naranja Datasur */
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2) !important;
    }
    
    /* 3. Forzar legibilidad y salto de línea automático para evitar puntos suspensivos (...) */
    div[data-testid="stMetric"] label [data-testid="stMarkdownContainer"] p {
        color: #94a3b8 !important; /* Gris Slate suave para etiquetas */
        font-weight: 500 !important;
        white-space: normal !important;
        word-break: break-word !important;
        font-size: 0.85em !important;
    }
    
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div {
        color: #ffffff !important; /* Blanco limpio para los números grandes */
        font-weight: 700 !important;
        white-space: normal !important;      /* <- Permite que el texto largo salte de línea */
        word-break: break-word !important;     /* <- Rompe palabras si es estrictamente necesario */
        font-size: 1.6rem !important;        /* <- Ajuste de tamaño para que quepa más información */
        line-height: 1.2 !important;
    }
    
    /* 4. Estilizado de pestañas (Tabs) */
    .stTabs [data-baseweb="tab-list"] button {
        color: #94a3b8 !important;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    .stTabs [data-baseweb="tab-list"] button [data-baseweb="tab-highlight"] {
        background-color: #ff8c00 !important; /* Línea naranja para la pestaña activa */
    }
    </style>
""", unsafe_allow_html=True)

st.title("EconoLens — Motor de Inteligencia Arancelaria")
st.caption("Análisis de Importaciones Perú | Fuente: Datasur")

# -----------------------------------------------------------------------
# Tabla de referencia HS (servidor — independiente del usuario)
# -----------------------------------------------------------------------

@st.cache_data
def get_dim_partida() -> pl.DataFrame:
    if DB_PATH.exists():
        return load_dim_partida(DB_PATH)
    if _DIM_PARTIDA_CSV.exists():
        return pl.read_csv(_DIM_PARTIDA_CSV, schema_overrides={
            "seccion": pl.String,
            "capitulo": pl.String,
            "partida_4d": pl.String,
            "subpartida_6d": pl.String,
        })
    return pl.DataFrame()


_SUPPLIER_TABLE_MAP: dict[str, str] = {
    "PROVEEDOR":            "supplier_proveedor",
    "EXPORTADOR":           "supplier_exportador",
    "EMPRESA EXPORTADORA":  "supplier_empresa_exportadora",
    "EMBARCADOR":           "supplier_embarcador",
    "PROBABLE EMBARCADOR":  "supplier_probable_embarcador",
}

# -----------------------------------------------------------------------
# Pipeline en memoria (por sesión de usuario)
# -----------------------------------------------------------------------

def _process_raw(
    df_raw: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, pl.DataFrame], dict[str, pl.DataFrame]]:
    """Corre el pipeline completo en memoria sobre un DataFrame crudo.

    Retorna (df_ise, aggs, supplier_data) sin escribir a disco.
    """
    from src.cleaning import clean_raw_df, add_unit_adjusted_quantity
    from src.arquetipos import clasificar_arquetipo
    from src.pipeline import run_pipeline_multi
    from src.aggregations import (
        _SUPPLIER_COLS, _COUNTRY_COL, _ADUANA_COL, _add_periodo,
        compute_market_share, compute_price_by_country, compute_price_by_route,
        compute_price_spread, compute_entities_over_time, compute_supplier_matrix,
    )

    # Orden idéntico a run.py
    if "PARTIDA ARANCELARIA" in df_raw.columns:
        df_raw = df_raw.with_columns(pl.col("PARTIDA ARANCELARIA").cast(pl.String))
    df = clean_raw_df(df_raw)
    df = clasificar_arquetipo(df, hs_col="PARTIDA ARANCELARIA")
    df = add_unit_adjusted_quantity(df)

    df_ise = run_pipeline_multi(
        df,
        hs_col="PARTIDA ARANCELARIA",
        unit_col="UNIDAD DE MEDIDA",
        value_col="US$ FOB",
        quantity_col="cantidad_ajustada",
        day_col="DÍA",
        month_col="MES",
        year_col="AÑO",
        actor_col="IMPORTADOR",
    )

    df_p = _add_periodo(df)
    periodos = sorted(df_p["periodo"].unique().to_list())

    def _by_p(fn) -> pl.DataFrame:
        frames = []
        for p in periodos:
            r = fn(df_p.filter(pl.col("periodo") == p))
            if not r.is_empty():
                frames.append(r.with_columns(pl.lit(p, dtype=pl.Date).alias("periodo")))
        return pl.concat(frames) if frames else pl.DataFrame()

    aggs: dict[str, pl.DataFrame] = {
        "market_share":       _by_p(lambda d: compute_market_share(d)),
        "price_by_country":   _by_p(lambda d: compute_price_by_country(d)) if _COUNTRY_COL in df.columns else pl.DataFrame(),
        "price_by_route":     _by_p(lambda d: compute_price_by_route(d)) if _ADUANA_COL in df.columns else pl.DataFrame(),
        "price_spread":       _by_p(lambda d: compute_price_spread(d)),
        "entities_over_time": compute_entities_over_time(df),
    }

    supplier_data: dict[str, pl.DataFrame] = {}
    for col in _SUPPLIER_COLS:
        if col in df.columns:
            frames = []
            for p in periodos:
                r = compute_supplier_matrix(df_p.filter(pl.col("periodo") == p), col)
                if not r.is_empty():
                    frames.append(r.with_columns(pl.lit(p, dtype=pl.Date).alias("periodo")))
            if frames:
                supplier_data[col] = pl.concat(frames)

    return df_ise, aggs, supplier_data


# -----------------------------------------------------------------------
# Helpers de lectura — convierte cualquier formato a DataFrame Polars
# -----------------------------------------------------------------------

def _read_uploaded(file) -> pl.DataFrame:
    """Lee xlsx / csv / parquet y devuelve un DataFrame Polars."""
    ext = Path(file.name).suffix.lower()
    raw = io.BytesIO(file.getvalue())
    if ext == ".parquet":
        return pl.read_parquet(raw)
    if ext == ".csv":
        return pl.read_csv(raw)
    if ext in (".xlsx", ".xls"):
        return pl.read_excel(raw)
    raise ValueError(f"Formato no soportado: {ext}")


# -----------------------------------------------------------------------
# Sidebar — carga de archivo
# -----------------------------------------------------------------------
with st.sidebar:
    st.header("📂 Dataset")
    uploaded_file = st.file_uploader(
        "Sube tu archivo de importaciones",
        type=["parquet", "csv", "xlsx", "xls"],
        help=(
            "Formatos aceptados: .parquet, .csv, .xlsx. "
            "Columnas requeridas: PARTIDA ARANCELARIA, IMPORTADOR, US$ FOB, "
            "CANTIDAD, UNIDAD DE MEDIDA, PESO NETO, DÍA, MES, AÑO."
        ),
    )

# -----------------------------------------------------------------------
# Data loading: archivo subido (sesión) o DB (fallback local)
# -----------------------------------------------------------------------
if uploaded_file is not None:
    _file_id = hash(uploaded_file.getvalue())
    if st.session_state.get("_file_id") != _file_id:
        with st.spinner("⏳ Procesando dataset..."):
            _df_raw = _read_uploaded(uploaded_file)
            _df_ise, _aggs, _supp = _process_raw(_df_raw)
        st.session_state["_file_id"] = _file_id
        st.session_state["_df_ise"] = _df_ise
        st.session_state["_aggs"] = _aggs
        st.session_state["_supp"] = _supp
    df_ise = st.session_state["_df_ise"]
    aggs = st.session_state["_aggs"]
    supplier_data = st.session_state["_supp"]
else:
    if not DB_PATH.exists():
        st.info("👆 Sube un archivo **.parquet** en el panel izquierdo para comenzar el análisis.")
        st.stop()
    df_ise = load_results(DB_PATH)
    aggs = {t: load_aggregation(DB_PATH, t)
            for t in ["market_share", "price_by_country", "price_by_route", "price_spread", "entities_over_time"]}
    supplier_data = {}
    for label, table in _SUPPLIER_TABLE_MAP.items():
        try:
            df_t = load_aggregation(DB_PATH, table)
            if df_t is not None and not df_t.is_empty():
                supplier_data[label] = df_t
        except Exception:
            pass

if df_ise is None or df_ise.is_empty():
    st.error("El dataset procesado está vacío. Verifica que el archivo tiene las columnas requeridas.")
    st.stop()

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

# Date range filter
_ms_agg = aggs.get("market_share", pl.DataFrame())
_has_periodo_filter = "periodo" in _ms_agg.columns

if _has_periodo_filter:
    _periodos_disp = sorted(_ms_agg["periodo"].unique().to_list())
    _ES_MONTHS = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
                  7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}
    _fmt_p = lambda p: f"{_ES_MONTHS[p.month]} {p.year}"
    _col_d, _col_h, _col_sp = st.columns([1, 1, 2])
    with _col_d:
        selected_start = st.selectbox("Desde", options=_periodos_disp, format_func=_fmt_p, index=0)
    with _col_h:
        selected_end = st.selectbox("Hasta", options=_periodos_disp, format_func=_fmt_p, index=len(_periodos_disp) - 1)
    if selected_start > selected_end:
        selected_start, selected_end = selected_end, selected_start
else:
    selected_start = None
    selected_end = None

# Arquetipo del producto seleccionado
_ARCHETYPE_COLORS = {
    "COMMODITY":     "#0047AB", # Azul Datasur
    "BIEN_DURADERO": "#007BFF", # Azul claro
    "PERECEDERO":    "#FF8C00", # Naranja Datasur
    "ESTANDAR":      "#64748b",
}
_ARCHETYPE_LABELS = {
    "COMMODITY":     "COMMODITY — Cereales / Combustibles / Minerales",
    "BIEN_DURADERO": "BIEN DURADERO — Maquinaria / Electrónicos / Vehículos",
    "PERECEDERO":    "PERECEDERO — Carnes / Lácteos / Frutas / Hortalizas",
    "ESTANDAR":      "ESTÁNDAR — Consumo general",
}

# Datos filtrados para la partida y rango de fechas seleccionados
df_hs = df_ise.filter(pl.col("hs_code") == selected_hs)
if selected_start is not None and "periodo" in df_hs.columns:
    df_hs = df_hs.filter(
        (pl.col("periodo") >= selected_start) & (pl.col("periodo") <= selected_end)
    )

arquetipo = (
    df_hs["arquetipo_economico"][0]
    if not df_hs.is_empty() and "arquetipo_economico" in df_hs.columns
    else "ESTANDAR"
)
_arc_color = _ARCHETYPE_COLORS.get(arquetipo, "#94a3b8")
_arc_label = _ARCHETYPE_LABELS.get(arquetipo, arquetipo)
_thresholds = ARCHETYPE_THRESHOLDS.get(arquetipo, ARCHETYPE_THRESHOLDS["ESTANDAR"])
_vol_unit = "unidades" if arquetipo == "BIEN_DURADERO" else "kg"
_price_unit = f"USD/{_vol_unit}"

st.markdown(
    f'<p style="margin-top:4px;font-size:0.82em;">Arquetipo económico: '
    f'<span style="color:{_arc_color};font-weight:700;'
    f'background:#1e293b;padding:2px 8px;border-radius:4px;'
    f'border:1px solid {_arc_color}33">{_arc_label}</span> '
    f'&nbsp;·&nbsp; Umbrales activos: volumen <b>±{_thresholds["volume"]:,.0f}%</b> '
    f'/ precio <b>±{_thresholds["price"]:,.0f}%</b></p>',
    unsafe_allow_html=True,
)

def _filter(table: str) -> pl.DataFrame:
    df = aggs.get(table, pl.DataFrame())
    if df.is_empty() or "hs_code" not in df.columns:
        return pl.DataFrame()
    result = df.filter(pl.col("hs_code") == selected_hs)
    if selected_start is not None and "periodo" in result.columns:
        result = result.filter(
            (pl.col("periodo") >= selected_start) & (pl.col("periodo") <= selected_end)
        )
    return result


def _reagg_ms(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty() or "periodo" not in df.columns:
        return df
    return (
        df.group_by("actor")
        .agg([pl.col("volumen_total").sum(), pl.col("valor_fob_total").sum()])
        .with_columns([
            (pl.col("volumen_total") / pl.col("volumen_total").sum() * 100).round(2).alias("participacion_pct"),
            (pl.col("valor_fob_total") / pl.col("valor_fob_total").sum() * 100).round(2).alias("participacion_fob_pct"),
        ])
        .sort("valor_fob_total", descending=True)
    )


def _reagg_country(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty() or "periodo" not in df.columns:
        return df
    return (
        df.group_by("pais")
        .agg([pl.col("volumen_total").sum(), pl.col("valor_total").sum()])
        .filter(pl.col("volumen_total") > 0)
        .with_columns(
            (pl.col("valor_total") / pl.col("volumen_total")).round(4).alias("precio_promedio")
        )
        .sort("volumen_total", descending=True)
    )


def _reagg_route(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty() or "periodo" not in df.columns:
        return df
    return (
        df.group_by("aduana")
        .agg([pl.col("volumen_total").sum(), pl.col("valor_total").sum()])
        .filter(pl.col("volumen_total") > 0)
        .with_columns(
            (pl.col("valor_total") / pl.col("volumen_total")).round(4).alias("precio_promedio")
        )
        .sort("volumen_total", descending=True)
    )


def _reagg_spread(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty() or "periodo" not in df.columns:
        return df
    return (
        df.group_by("actor")
        .agg([pl.col("precio_min").min(), pl.col("precio_max").max()])
        .with_columns(
            pl.when(pl.col("precio_min") > 0)
            .then(
                ((pl.col("precio_max") - pl.col("precio_min")) / pl.col("precio_min") * 100).round(2)
            )
            .otherwise(None)
            .alias("spread_pct")
        )
        .sort("spread_pct", descending=True)
    )


ms_df = _reagg_ms(_filter("market_share"))
country_df = _reagg_country(_filter("price_by_country"))
route_df = _reagg_route(_filter("price_by_route"))
spread_df = _reagg_spread(_filter("price_spread"))
entities_df = _filter("entities_over_time")

# -----------------------------------------------------------------------
# 4 Pestañas principales
# -----------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Competidores e Importadores",
    "🗺️ Precios, Rutas y Adquisición",
    "⏳ Evolución Temporal",
    "⚠️ Alertas ISE",
    "🌐 Proveedores Internacionales",
])

# =======================================================================
# TAB 1 — Competidores
# =======================================================================
with tab1:
    if ms_df.is_empty():
        st.info("No hay datos de market share. Ejecuta `python run.py` para generarlos.")
    else:
        _has_fob = "valor_fob_total" in ms_df.columns

        # Ordenar por FOB si está disponible, si no por volumen
        ms_sorted = ms_df.sort(
            "valor_fob_total" if _has_fob else "volumen_total",
            descending=True,
        )
        top_row = ms_sorted.row(0, named=True)
        total_vol = ms_sorted["volumen_total"].sum()
        total_fob = ms_sorted["valor_fob_total"].sum() if _has_fob else None
        top3_pct = (
            ms_sorted.head(3)["participacion_fob_pct"].sum()
            if _has_fob
            else ms_sorted.head(3)["participacion_pct"].sum()
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Importador Líder", f"🏆 {top_row['actor']}")
        c2.metric(
            "Valor FOB Total",
            f"$ {total_fob:,.0f}" if total_fob is not None else "—",
        )
        c3.metric("Volumen Total Registrado", f"{total_vol:,.0f} {_vol_unit}")
        c4.metric("Concentración Top 3 (FOB)", f"{top3_pct:.1f}%")

        st.write("")

        with st.container(border=True):
            st.subheader("Cuota de Mercado por Importador")

            select_cols = [pl.col("actor").alias("Importador")]
            col_config: dict = {}

            if _has_fob:
                select_cols += [
                    pl.col("valor_fob_total").alias("US$ FOB Acumulado"),
                    pl.col("participacion_fob_pct").alias("% FOB"),
                    pl.col("participacion_fob_pct").alias("Progreso FOB"),
                    pl.col("volumen_total").alias(f"Volumen ({_vol_unit})"),
                ]
                col_config = {
                    "US$ FOB Acumulado": st.column_config.NumberColumn(format="$ %,.0f"),
                    "% FOB": st.column_config.NumberColumn(format="%.1f%%"),
                    "Progreso FOB": st.column_config.ProgressColumn(
                        "Progreso",
                        help="Cuota de mercado en valor FOB",
                        format=" ",
                        min_value=0,
                        max_value=100,
                    ),
                    f"Volumen ({_vol_unit})": st.column_config.NumberColumn(format=f"%,d {_vol_unit}"),
                }
            else:
                select_cols += [
                    pl.col("volumen_total").alias(f"Volumen Acumulado ({_vol_unit})"),
                    pl.col("participacion_pct").alias("% Participación"),
                    pl.col("participacion_pct").alias("Barra de Cuota"),
                ]
                col_config = {
                    f"Volumen Acumulado ({_vol_unit})": st.column_config.NumberColumn(format=f"%,d {_vol_unit}"),
                    "% Participación": st.column_config.NumberColumn(format="%.1f%%"),
                    "Barra de Cuota": st.column_config.ProgressColumn(
                        "Progreso",
                        format=" ",
                        min_value=0,
                        max_value=100,
                    ),
                }

            df_ms_display = ms_sorted.select(select_cols).to_pandas()
            st.dataframe(
                df_ms_display,
                use_container_width=True,
                hide_index=True,
                column_config=col_config,
            )

# =======================================================================
# TAB 2 — Precios y Rutas
# =======================================================================
with tab2:
    col_left, col_right = st.columns(2)

    with col_left:
        with st.container(border=True):
            st.subheader("Precio por País de Origen")
            if country_df.is_empty():
                st.info("Sin datos de países.")
            else:
                display_country = (
                    country_df
                    .sort("volumen_total", descending=True)
                    .select(["pais", "volumen_total", "precio_promedio"])
                    .rename({"pais": "País de Origen", "volumen_total": f"Volumen ({_vol_unit})", "precio_promedio": f"Precio FOB {_price_unit}"})
                )
                st.dataframe(
                    display_country.to_pandas(),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        f"Volumen ({_vol_unit})": st.column_config.NumberColumn(format=f"%,d {_vol_unit}"),
                        f"Precio FOB {_price_unit}": st.column_config.NumberColumn(format="$ %,.4f")
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
                    .rename({"aduana": "Aduana", "volumen_total": f"Volumen ({_vol_unit})", "precio_promedio": f"Precio FOB {_price_unit}"})
                )
                st.dataframe(
                    display_route.to_pandas(),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        f"Volumen ({_vol_unit})": st.column_config.NumberColumn(format=f"%,d {_vol_unit}"),
                        f"Precio FOB {_price_unit}": st.column_config.NumberColumn(format="$ %,.4f")
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
                    "precio_min": f"Precio Mín ({_price_unit})",
                    "precio_max": f"Precio Máx ({_price_unit})",
                    "spread_pct": "Spread (%)",
                })
            )
            st.dataframe(
                display_spread.to_pandas(),
                use_container_width=True,
                hide_index=True,
                column_config={
                    f"Precio Mín ({_price_unit})": st.column_config.NumberColumn(format="$ %,.4f"),
                    f"Precio Máx ({_price_unit})": st.column_config.NumberColumn(format="$ %,.4f"),
                    "Spread (%)": st.column_config.NumberColumn(format="%,.2f%%")
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
                    hide_index=True,
                    column_config={
                        "Empresas Activas": st.column_config.NumberColumn(format="%,d")
                    }
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
                        pl.col("volumen").sum().alias(f"Volumen Total ({_vol_unit})"),
                        (
                            (pl.col("precio") * pl.col("volumen")).sum()
                            / pl.col("volumen").sum()
                        ).round(4).alias(f"Precio Ponderado ({_price_unit})"),
                    ])
                    .sort("periodo")
                )
                
                df_plot = vol_price.to_pandas()

                # Configuración compartida de Plotly (Diseño Ultra-Limpio)
                layout_config = dict(
                    height=180,
                    margin=dict(l=55, r=15, t=10, b=10), # Ligero ajuste a la izquierda para el texto largo
                    hovermode="x unified",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False, title_text=""),
                )

                # Gráfico 1: Volumen (Forzado de comas en el eje Y y Hover)
                fig = px.line(df_plot, x="periodo", y=f"Volumen Total ({_vol_unit})", markers=True)
                fig.update_traces(
                    line=dict(width=3, color="#38bdf8"), 
                    marker=dict(size=6),
                    yhoverformat="%,d"  # Separador de miles al pasar el mouse
                )
                fig.update_layout(
                    **layout_config,
                    yaxis=dict(showgrid=True, gridcolor="#334155", tickformat="%,d") # Separador de miles en el eje
                )
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

                # Gráfico 2: Precio (Forzado de comas y decimales en el eje Y y Hover)
                fig2 = px.line(df_plot, x="periodo", y=f"Precio Ponderado ({_price_unit})", markers=True)
                fig2.update_traces(
                    line=dict(width=3, color="#f59e0b"), 
                    marker=dict(size=6),
                    yhoverformat="$,.4f" # Formato de moneda con miles y 4 decimales en Hover
                )
                fig2.update_layout(
                    **layout_config,
                    yaxis=dict(showgrid=True, gridcolor="#334155", tickformat=",.4f") # 4 decimales alineados en el eje
                )
                st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

# =======================================================================
# TAB 4 — Alertas ISE
# =======================================================================
with tab4:
    st.subheader("Alertas de Shocks Económicos e Índice de Sensibilidad (ISE)")
    st.caption(
        f"Detección automática calibrada para arquetipo "
        f"**{arquetipo}** — umbrales: volumen ±{_thresholds['volume']:,.0f}% / "
        f"precio ±{_thresholds['price']:,.0f}%"
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
                st.error(f"🚨 **{actor}** — Período: `{periodo_str}` | **ISE: {ise:,.1f} (Crítico)** | {tag}\n\n{narrativa}")
            elif ise >= 85.0:
                st.warning(f"⚠️ **{actor}** — Período: `{periodo_str}` | **ISE: {ise:,.1f} (Alto)** | {tag}\n\n{narrativa}")
            else:
                st.info(f"💡 **{actor}** — Período: `{periodo_str}` | **ISE: {ise:,.1f} (Moderado)** | {tag}\n\n{narrativa}")

# =======================================================================
# TAB 5 — Proveedores Internacionales
# =======================================================================
with tab5:
    st.subheader("Proveedores Internacionales (Análisis B2B)")
    st.caption("Identificación de los principales exportadores en origen y sus canales de distribución locales.")

    if not supplier_data:
        st.info("No hay datos de proveedores. Ejecuta `python run.py` para generarlos.")
    else:
        fuente = st.selectbox(
            "Fuente del proveedor",
            options=list(supplier_data.keys()),
            key="supplier_fuente",
        )

        supp_df = supplier_data[fuente].filter(pl.col("hs_code") == selected_hs)
        if selected_start is not None and "periodo" in supp_df.columns:
            supp_df = supp_df.filter(
                (pl.col("periodo") >= selected_start) & (pl.col("periodo") <= selected_end)
            )
            if not supp_df.is_empty():
                supp_df = (
                    supp_df.group_by(["proveedor", "actor"])
                    .agg([pl.col("valor_fob_total").sum(), pl.col("volumen_total").sum()])
                    .with_columns(
                        (pl.col("valor_fob_total") / pl.col("valor_fob_total").sum() * 100)
                        .round(2).alias("participacion_pct")
                    )
                    .sort("valor_fob_total", descending=True)
                )

        if supp_df.is_empty():
            st.info("Sin datos de proveedores para esta partida con la fuente seleccionada.")
        else:
            supp_sorted = supp_df.sort("valor_fob_total", descending=True)

            n_proveedores = supp_sorted["proveedor"].n_unique()
            top_proveedor = supp_sorted.row(0, named=True)
            dependencia = supp_sorted.head(1)["participacion_pct"].sum()
            dep_label = "Alta" if dependencia >= 70 else "Media" if dependencia >= 40 else "Baja"
            dep_color = "🔴" if dependencia >= 70 else "🟡" if dependencia >= 40 else "🟢"

            k1, k2, k3 = st.columns(3)
            k1.metric("Proveedores Extranjeros Activos", f"{n_proveedores} empresas")
            k2.metric("Principal Exportador Global", f"🏢 {top_proveedor['proveedor']}")
            k3.metric("Dependencia Comercial", f"{dependencia:.1f}% {dep_color} {dep_label}")

            st.write("")

            with st.container(border=True):
                st.subheader("Matriz de Relaciones Comerciales")
                st.caption("Mapeo de canales logísticos: vendedores en el extranjero y sus compradores directos en Perú.")

                df_supp_display = supp_sorted.select([
                    pl.col("proveedor").alias("Proveedor en Origen"),
                    pl.col("actor").alias("Importador Peruano"),
                    pl.col("valor_fob_total").alias("US$ FOB"),
                    pl.col("volumen_total").alias(f"Masa Embarcada ({_vol_unit})"),
                    pl.col("participacion_pct").alias("% Suministro"),
                    pl.col("participacion_pct").alias("Participación"),
                ]).to_pandas()

                st.dataframe(
                    df_supp_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "US$ FOB": st.column_config.NumberColumn(format="$ %,.0f"),
                        f"Masa Embarcada ({_vol_unit})": st.column_config.NumberColumn(format=f"%,d {_vol_unit}"),
                        "% Suministro": st.column_config.NumberColumn(format="%.1f%%"),
                        "Participación": st.column_config.ProgressColumn(
                            "Participación de Suministro",
                            format=" ",
                            min_value=0,
                            max_value=100,
                        ),
                    },
                )

            st.write("")
            st.info(
                "**Nota de Inteligencia Operativa:** Cruzar el nombre del proveedor permite identificar "
                "si un importador está comprándole a una **empresa vinculada** (filial corporativa en el "
                "extranjero) o si tiene un contrato de exclusividad cerrado, lo cual suele explicar por "
                "qué sus precios se mantienen estables frente a shocks globales."
            )