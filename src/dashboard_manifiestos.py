"""Vista de manifiestos — constructor de tabla dinámica.

El usuario elige dimensiones, métricas y filtros y la tabla se recalcula. Es el
cuadro que los usuarios peruanos de esta data ya arman a mano en Excel —TEUs y
contenedores por naviera, peso por aerolínea— sin salir de la app.

No procesa nada por sesión: consulta con DuckDB el lake que dejó
`build_manifiestos.py`. Si el lake no existe (el caso del despliegue en la
nube), muestra el estado vacío y no falla.

La paleta es la misma que Comex Latam, que vive en `src.theme`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import polars as pl
import streamlit as st

from src.pivot import (
    DIMENSIONES,
    METRICAS,
    SIN_DATO,
    cobertura,
    dimensiones_disponibles,
    etiqueta_metrica,
    periodos_disponibles,
    run_pivot,
    run_totales,
)
from src.theme import C, css, esc, kpis, miles, usd

LAKE = Path(__file__).parent.parent / "data" / "manifiestos"

MAX_FILAS_PIVOTE = 3

FLUJOS: dict[str, str] = {"": "Ambos", "impo": "Importación", "expo": "Exportación"}
VIAS: dict[str, str] = {"": "Ambas", "maritimo": "Marítimo", "aereo": "Aéreo"}

# Métricas que se muestran como dinero. El resto va con separador de miles.
MONETARIAS = {"fob_usd", "cif_usd", "flete_usd", "seguro_usd"}


class Preset:
    """Un cuadro armado de entrada, para no empezar de cero."""

    def __init__(self, etiqueta: str, filas: list[str], metricas: list[str],
                 flujo: str = "", via: str = "", columna: str | None = None):
        self.etiqueta = etiqueta
        self.filas = filas
        self.metricas = metricas
        self.flujo = flujo
        self.via = via
        self.columna = columna


PRESETS: list[Preset] = [
    Preset("TEUs y FEUs por naviera", ["transportista"],
           ["teus", "cont_40", "registros"], flujo="impo", via="maritimo"),
    Preset("Peso por aerolínea", ["transportista"], ["peso_kg", "registros"],
           via="aereo"),
    Preset("Producto por país", ["pais", "partida_4d"],
           ["cif_usd", "peso_kg", "registros"], flujo="impo"),
    Preset("Naviera por mes", ["transportista"], ["teus"],
           via="maritimo", columna="periodo"),
]


# ---------------------------------------------------------------------------
# Datos (cacheados: Streamlit reejecuta el script en cada interacción)
# ---------------------------------------------------------------------------

def _clave(filtros: dict[str, Sequence[str]]) -> tuple:
    """Los dicts no son hashables; las claves de caché sí tienen que serlo."""
    return tuple(sorted((k, tuple(v)) for k, v in filtros.items() if v))


@st.cache_data(show_spinner=False)
def _periodos() -> list[str]:
    return periodos_disponibles(LAKE)


@st.cache_data(show_spinner=False)
def _dimensiones(clave: tuple, desde: str, hasta: str) -> list[str]:
    return dimensiones_disponibles(LAKE, dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _valores(dimension: str, clave: tuple, desde: str, hasta: str) -> list[str]:
    from src.pivot import valores_de_dimension

    return valores_de_dimension(LAKE, dimension, dict(clave), desde, hasta, tope=400)


@st.cache_data(show_spinner=False)
def _pivote(filas: tuple, metricas: tuple, columna: str | None, clave: tuple,
            desde: str, hasta: str, limite: int) -> pl.DataFrame:
    return run_pivot(LAKE, list(filas), list(metricas), columna, dict(clave),
                     desde, hasta, limite)


@st.cache_data(show_spinner=False)
def _totales(metricas: tuple, clave: tuple, desde: str, hasta: str) -> dict:
    return run_totales(LAKE, list(metricas), dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _cobertura(metrica: str, clave: tuple, desde: str, hasta: str) -> float:
    return cobertura(LAKE, metrica, dict(clave), desde, hasta)


def hay_datos(lake: Path | None = None) -> bool:
    """El lake existe y tiene algún parquet.

    Resuelve `LAKE` al llamarse y no al definirse: así se puede simular el
    despliegue sin lake, que es el caso de Streamlit Cloud.
    """
    lake = lake if lake is not None else LAKE
    return lake.is_dir() and any(lake.rglob("*.parquet"))


# ---------------------------------------------------------------------------
# Piezas de interfaz
# ---------------------------------------------------------------------------

def _sin_datos() -> None:
    """Estado vacío: en la nube no existe el lake, igual que la DB del ISE."""
    st.markdown(f"""
      <div class="fm-card" style="max-width:70ch">
        <div class="fm-kicker" style="color:{C['orange']}">Sin datos cargados</div>
        <h3 style="margin:8px 0 10px">Falta construir el lake de manifiestos</h3>
        <p class="fm-sub">Este módulo consulta los manifiestos de carga ya
          normalizados. Para generarlos, dejá los CSV en
          <span class="fm-mono">data/data-manifiestos/</span> y corré:</p>
        <p class="fm-mono" style="background:{C['line']};padding:10px 14px;
           border-radius:8px;font-size:13px">python build_manifiestos.py</p>
        <p class="fm-note">Los manifiestos no se versionan en el repositorio,
          así que el módulo funciona sobre una copia local de la data.</p>
      </div>""", unsafe_allow_html=True)


def _etiqueta_dim(nombre: str) -> str:
    return DIMENSIONES[nombre].etiqueta


def _etiqueta_met(nombre: str) -> str:
    return METRICAS[nombre].etiqueta


def _aplicar_preset(preset: Preset) -> None:
    """Deja la selección lista para el próximo run.

    Va como `on_click` y no en el cuerpo del `if st.button(...)`: Streamlit
    prohíbe escribir el estado de un widget una vez que ese widget se
    instanció, y los selectores del constructor ya existen cuando el botón se
    evalúa. Los callbacks corren antes de que se dibuje nada.
    """
    st.session_state["mf_flujo"] = preset.flujo
    st.session_state["mf_via"] = preset.via
    st.session_state["mf_filas"] = preset.filas
    st.session_state["mf_metricas"] = preset.metricas
    st.session_state["mf_columna"] = preset.columna
    st.session_state["mf_filtro_dim"] = None
    st.session_state["mf_filtro_val"] = []


def _formato_columna(nombre: str, metricas: Sequence[str], cruzada: bool) -> Any:
    """Configura una columna de la grilla según la métrica que representa.

    En una tabla cruzada de una sola métrica las columnas se llaman por el
    valor cruzado (`2026-06`) y no llevan el nombre de la métrica: el formato
    sale de la métrica única, o si no de la etiqueta que el título contenga.
    """
    if cruzada and len(metricas) == 1:
        monetaria = metricas[0] in MONETARIAS
    else:
        monetaria = any(
            m in MONETARIAS and METRICAS[m].etiqueta in nombre for m in metricas
        )
    return st.column_config.NumberColumn(
        nombre, format="$ %.0f" if monetaria else "%.0f"
    )


def _nota_cobertura(metricas: Sequence[str], clave: tuple, desde: str,
                    hasta: str) -> None:
    """Avisa cuánto del universo elegido trae realmente cada métrica de valor.

    El FOB solo existe donde la guía cruzó con una DUA: en exportación aérea
    llega al 6% de las filas. Sin este número, un total de exportación se lee
    como si fuera la exportación del país.
    """
    avisos = []
    for metrica in metricas:
        if metrica not in MONETARIAS:
            continue
        pct_cobertura = _cobertura(metrica, clave, desde, hasta)
        if pct_cobertura < 95:
            avisos.append(
                f"<b>{esc(METRICAS[metrica].etiqueta)}</b> existe en el "
                f"{pct_cobertura:.0f}% de las guías de esta selección"
            )
    if not avisos:
        return
    st.markdown(f"""
      <div class="fm-card" style="border-left:3px solid {C['orange']};padding:12px 16px">
        <div class="fm-note" style="color:{C['muted']};font-size:13px">
          ⚠ {' · '.join(avisos)}. El valor se declara en la DUA, y no todas las
          guías cruzan con una: el total es un piso, no el comercio completo.
          Peso, TEUs y contenedores sí están en todas.
        </div>
      </div>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render() -> None:
    """Dibuja el constructor de tabla dinámica."""
    css()

    st.markdown(
        '<div class="fm-kicker">Datasur · Manifiestos de carga · Perú</div>'
        '<h1 style="margin:2px 0 6px">Constructor de tablas</h1>'
        '<p class="fm-sub">Armá tu propio cuadro: elegí por qué agrupar, qué '
        'medir y sobre qué recorte. Cada fila es una guía aérea o un '
        'conocimiento de embarque.</p>',
        unsafe_allow_html=True,
    )

    if not hay_datos():
        _sin_datos()
        return

    periodos = _periodos()

    # --- Sidebar: recorte del universo -----------------------------------
    with st.sidebar:
        st.markdown('<div class="fm-kicker">Recorte</div>', unsafe_allow_html=True)
        flujo = st.radio("Flujo", list(FLUJOS), key="mf_flujo",
                         format_func=lambda v: FLUJOS[v])
        via = st.radio("Vía", list(VIAS), key="mf_via",
                       format_func=lambda v: VIAS[v])
        desde = st.selectbox("Desde", periodos, index=0, key="mf_desde")
        hasta = st.selectbox("Hasta", periodos, index=len(periodos) - 1,
                             key="mf_hasta")

    filtros: dict[str, list[str]] = {}
    if flujo:
        filtros["flujo"] = [flujo]
    if via:
        filtros["via"] = [via]

    disponibles = _dimensiones(_clave(filtros), desde, hasta)
    if not disponibles:
        # Ninguna dimensión tiene dato porque no hay ninguna guía: pasa, por
        # ejemplo, si el `desde` quedó después del `hasta`. Sin este aviso el
        # módulo se queda pidiendo elegir dimensiones que no existen.
        st.warning(
            f"No hay guías entre {desde} y {hasta} con ese flujo y esa vía. "
            "Ampliá el recorte en la barra lateral."
        )
        return

    # --- Sidebar: filtro por valores de una dimensión ---------------------
    with st.sidebar:
        st.markdown('<div class="fm-kicker">Filtro</div>', unsafe_allow_html=True)
        filtro_dim = st.selectbox(
            "Dimensión a filtrar", [None] + disponibles, key="mf_filtro_dim",
            format_func=lambda v: "— ninguna —" if v is None else _etiqueta_dim(v),
        )
        if filtro_dim:
            opciones = _valores(filtro_dim, _clave(filtros), desde, hasta)
            elegidos = st.multiselect("Valores", opciones, key="mf_filtro_val")
            if elegidos:
                filtros[filtro_dim] = elegidos

    # --- Presets ----------------------------------------------------------
    st.write("")
    columnas = st.columns(len(PRESETS))
    for columna_ui, preset in zip(columnas, PRESETS):
        with columna_ui:
            st.button(preset.etiqueta, use_container_width=True,
                      key=f"mf_preset_{preset.etiqueta}",
                      on_click=_aplicar_preset, args=(preset,))

    # --- Constructor ------------------------------------------------------
    st.write("")
    izq, centro, der = st.columns([2, 1.2, 2], gap="medium")
    with izq:
        filas = st.multiselect(
            f"Agrupar por (hasta {MAX_FILAS_PIVOTE})", disponibles,
            default=["transportista"] if "transportista" in disponibles else
            disponibles[:1],
            key="mf_filas", format_func=_etiqueta_dim,
            max_selections=MAX_FILAS_PIVOTE,
        )
    with centro:
        cruce = [d for d in disponibles if d not in filas]
        columna = st.selectbox(
            "Abrir en columnas", [None] + cruce, key="mf_columna",
            format_func=lambda v: "— sin cruce —" if v is None else _etiqueta_dim(v),
        )
    with der:
        metricas = st.multiselect(
            "Medir", list(METRICAS), default=["teus", "registros"],
            key="mf_metricas", format_func=_etiqueta_met,
        )

    if not filas or not metricas:
        st.info("Elegí al menos una dimensión para agrupar y una métrica.")
        return

    clave = _clave(filtros)

    # --- KPIs del universo recortado --------------------------------------
    totales = _totales(tuple(metricas), clave, desde, hasta)
    st.write("")
    st.markdown(kpis([
        (
            METRICAS[m].etiqueta,
            usd(totales[etiqueta_metrica(m)]) if m in MONETARIAS
            else miles(totales[etiqueta_metrica(m)]),
            C["navy"],
            "total de la selección",
        )
        for m in metricas[:4]
    ]), unsafe_allow_html=True)

    st.write("")
    _nota_cobertura(metricas, clave, desde, hasta)

    # --- Tabla ------------------------------------------------------------
    df = _pivote(tuple(filas), tuple(metricas), columna, clave, desde, hasta,
                 500)
    st.write("")
    if df.is_empty():
        st.warning("Ninguna guía cumple con esa combinación de filtros.")
        return

    etiquetas_fila = {DIMENSIONES[f].etiqueta for f in filas}
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            c: _formato_columna(c, metricas, columna is not None)
            for c in df.columns if c not in etiquetas_fila
        },
    )

    nota = f"{miles(df.height)} filas"
    if df.height >= 500:
        nota += " (recortado a las 500 primeras)"
    if columna:
        nota += f" · columnas: los {len(df.columns) - len(filas) - 1} valores más frecuentes de {_etiqueta_dim(columna)}"
    st.markdown(
        f'<div class="fm-note">{esc(nota)} · los nulos se agrupan como '
        f'<span class="fm-mono">{SIN_DATO}</span></div>',
        unsafe_allow_html=True,
    )
