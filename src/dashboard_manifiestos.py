"""Vista de manifiestos — buscador de la cadena logística del Perú.

Tres pantallas y un destino. Escribes un nombre —una empresa, una naviera, un
agente, un país, una nave— y caes en la ficha de esa entidad, que muestra
cuánto mueve y con quién trabaja. La tabla dinámica sigue estando para cuando
la ficha no alcanza, pero ya no es la puerta de entrada.

No procesa nada por sesión: consulta con DuckDB el lake que dejó
`build_manifiestos.py`. Si el lake no existe (el caso del despliegue en la
nube), muestra el estado vacío y no falla.

Cada número de estas pantallas está definido en `docs/manifiestos_metricas.md`,
que es el contrato con el diseño. Los §§ de los comentarios son de ahí.

La paleta es la misma que Comex Latam y vive en `src.theme`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

import polars as pl
import streamlit as st

from src.buscador import (
    ROLES,
    buscar,
    captura,
    cardinalidad,
    costo_implicito,
    es_bucket,
    mix,
    oportunidad,
    ranking,
    resumen_cuadrantes,
    serie,
    tramos,
)
from src.pivot import (
    DIMENSIONES,
    METRICAS,
    SIN_DATO,
    cobertura,
    dimensiones_disponibles,
    etiqueta_metrica,
    metricas_disponibles,
    periodos_disponibles,
    run_pivot,
    run_totales,
)
from src.theme import C, css, esc, kpis, miles, usd

LAKE = Path(__file__).parent.parent / "data" / "manifiestos"

MAX_FILAS_PIVOTE = 3
TOPE_TABLA = 500
TOPE_VISIBLE = 150

PANTALLAS: dict[str, str] = {
    "buscador": "Buscador",
    "rankings": "Quién mueve más",
    "tabla": "Tabla dinámica",
}

# Los cuatro manifiestos, en el orden en que se muestran.
CUADRANTES: list[tuple[str, str, str, str]] = [
    ("impo", "maritimo", "Marítimo", "Ingreso"),
    ("expo", "maritimo", "Marítimo", "Salida"),
    ("impo", "aereo", "Aéreo", "Ingreso"),
    ("expo", "aereo", "Aéreo", "Salida"),
]

MONETARIAS = {"fob_usd", "cif_usd", "flete_usd", "seguro_usd"}

# Roles que son operadores de la cadena: su ficha muestra cartera de clientes y
# cuentas donde no está, en vez de «con quién trabaja».
ROLES_OPERADOR = {"transportista", "agente_aduana", "agencia_carga",
                  "almacen", "agente_portuario"}

# Con quién trabaja un importador o exportador, en orden de utilidad comercial.
CADENA = ("transportista", "agente_aduana", "agencia_carga", "almacen")

# Filtros de la búsqueda. Agrupan roles que el usuario lee como uno solo: los
# dos puertos son «Puertos», y no vale la pena separarlos en la interfaz.
CHIPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("todo", "Todo", ()),
    ("actor", "Importadores", ("actor",)),
    ("transportista", "Navieras", ("transportista",)),
    ("agente_aduana", "Agentes de aduana", ("agente_aduana",)),
    ("agencia_carga", "Agencias de carga", ("agencia_carga",)),
    ("almacen", "Almacenes", ("almacen",)),
    ("pais", "Países", ("pais",)),
    ("partida", "Partidas", ("partida_4d",)),
    ("nave", "Naves y vuelos", ("nave_vuelo",)),
    ("puerto", "Puertos", ("puerto_embarque", "puerto_desembarque")),
]
ETIQUETA_CHIP = {c: e for c, e, _ in CHIPS}
ROLES_CHIP = {c: r for c, _, r in CHIPS}


def _principal(via: str) -> str:
    """§5.3 — La métrica que encabeza cada pantalla, según el manifiesto.

    En aéreo no hay TEUs. Nunca el valor: no está en todas las guías.
    """
    return "peso_kg" if via == "aereo" else "teus"


# ---------------------------------------------------------------------------
# Iconos (SVG en línea: escalan y toman el color del contenedor)
# ---------------------------------------------------------------------------

_BARCO = ('<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
          'stroke-linejoin="round"><path d="M3.5 18c1.1 0 1.1.9 2.2.9S6.8 18 '
          '7.9 18s1.1.9 2.2.9S11.2 18 12.3 18s1.1.9 2.2.9S15.6 18 16.7 18s1.1'
          '.9 2.2.9"/><path d="M5.5 16V9.5h13V16"/><path d="M9 9.5V6.5h6v3"/>'
          '</svg>')
_AVION = ('<svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor">'
          '<path d="M12 3.4c.75 0 1.3.62 1.3 1.4v4.05l6.9 4.05v1.7l-6.9-2.05'
          'v3.6l1.95 1.45v1.3L12 18.35 8.75 18.9v-1.3l1.95-1.45v-3.6L3.8 14.6'
          'v-1.7l6.9-4.05V4.8c0-.78.55-1.4 1.3-1.4z"/></svg>')


def _icono(via: str) -> str:
    return _AVION if via == "aereo" else _BARCO


def _etiqueta_cuadrante(flujo: str, via: str) -> str:
    return next(f"{ev} · {ef}" for f, v, ev, ef in CUADRANTES
                if (f, v) == (flujo, via))


# ---------------------------------------------------------------------------
# Datos (cacheados: Streamlit reejecuta el script en cada interacción)
# ---------------------------------------------------------------------------

def _clave(filtros: dict[str, Sequence[str]] | None) -> tuple:
    """Los dicts no son hashables; las claves de caché sí tienen que serlo."""
    return tuple(sorted((k, tuple(v)) for k, v in (filtros or {}).items() if v))


def _dict(clave: tuple | None) -> dict[str, list[str]] | None:
    return None if clave is None else {k: list(v) for k, v in clave}


@st.cache_data(show_spinner=False)
def _periodos() -> list[str]:
    return periodos_disponibles(LAKE)


@st.cache_data(show_spinner=False)
def _resumen(desde: str, hasta: str) -> pl.DataFrame:
    return resumen_cuadrantes(LAKE, desde, hasta)


@st.cache_data(show_spinner=False)
def _buscar(termino: str, desde: str, hasta: str,
            roles: tuple[str, ...] = ()) -> pl.DataFrame:
    return buscar(LAKE, termino, desde, hasta, roles or None)


@st.cache_data(show_spinner=False)
def _ranking(dimension: str, metrica: str, clave: tuple, desde: str, hasta: str,
             cardinalidades: tuple = (), extras: tuple = (),
             excluir: bool = False, denominador: tuple | None = None,
             tope: int = 12) -> pl.DataFrame:
    return ranking(LAKE, dimension, metrica, _dict(clave), desde, hasta,
                   cardinalidades, extras, excluir, _dict(denominador), tope)


@st.cache_data(show_spinner=False)
def _captura(rol: str, valor: str, metrica: str, clave: tuple, desde: str,
             hasta: str, tope: int = 10) -> pl.DataFrame:
    return captura(LAKE, rol, valor, metrica, _dict(clave), desde, hasta,
                   tope=tope)


@st.cache_data(show_spinner=False)
def _oportunidad(rol: str, valor: str, metrica: str, clave: tuple, desde: str,
                 hasta: str, piso: float, techo: float) -> pl.DataFrame:
    return oportunidad(LAKE, rol, valor, metrica, _dict(clave), desde, hasta,
                       piso=piso, techo=techo, tope=6)


@st.cache_data(show_spinner=False)
def _serie(metrica: str, clave: tuple, desde: str, hasta: str,
           share_sobre: tuple | None = None) -> pl.DataFrame:
    return serie(LAKE, metrica, _dict(clave), desde, hasta, _dict(share_sobre))


@st.cache_data(show_spinner=False)
def _mix(dimension: str, clave: tuple, desde: str, hasta: str) -> pl.DataFrame:
    return mix(LAKE, dimension, _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _costo(clave: tuple, desde: str, hasta: str) -> dict:
    return costo_implicito(LAKE, _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _cardinalidad(dims: tuple, clave: tuple, desde: str, hasta: str) -> dict:
    return cardinalidad(LAKE, dims, _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _tramos(dimension: str, metrica: str, clave: tuple, desde: str,
            hasta: str) -> dict:
    return tramos(LAKE, dimension, metrica, _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _totales(metricas: tuple, clave: tuple, desde: str, hasta: str) -> dict:
    return run_totales(LAKE, list(metricas), _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _dimensiones(clave: tuple, desde: str, hasta: str) -> list[str]:
    return dimensiones_disponibles(LAKE, _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _metricas(clave: tuple, desde: str, hasta: str) -> list[str]:
    return metricas_disponibles(LAKE, _dict(clave), desde, hasta)


@st.cache_data(show_spinner=False)
def _valores(dimension: str, clave: tuple, desde: str, hasta: str) -> list[str]:
    from src.pivot import valores_de_dimension

    return valores_de_dimension(LAKE, dimension, _dict(clave), desde, hasta, 400)


@st.cache_data(show_spinner=False)
def _pivote(filas: tuple, metricas: tuple, columna: str | None, clave: tuple,
            desde: str, hasta: str) -> pl.DataFrame:
    return run_pivot(LAKE, list(filas), list(metricas), columna, _dict(clave),
                     desde, hasta, TOPE_TABLA)


@st.cache_data(show_spinner=False)
def _cobertura(metrica: str, clave: tuple, desde: str, hasta: str) -> float:
    return cobertura(LAKE, metrica, _dict(clave), desde, hasta)


def hay_datos(lake: Path | None = None) -> bool:
    """El lake existe y tiene algún parquet.

    Resuelve `LAKE` al llamarse y no al definirse: así se puede simular el
    despliegue sin lake, que es el caso de Streamlit Cloud.
    """
    lake = lake if lake is not None else LAKE
    return lake.is_dir() and any(lake.rglob("*.parquet"))


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

def _valor(metrica: str, v: float | None) -> str:
    """Un número con la unidad de su métrica. El nulo es `—`, nunca cero."""
    if v is None:
        return "—"
    if metrica in MONETARIAS:
        return usd(v)
    if metrica in ("peso_kg", "peso_neto_kg"):
        return f"{miles(v / 1000)} t"
    return miles(v)


def _unidad(metrica: str) -> str:
    return {"teus": "TEUs", "contenedores": "contenedores",
            "peso_kg": "toneladas", "registros": "guías",
            "actores": "clientes"}.get(metrica, METRICAS[metrica].etiqueta)


# Un salto de línea y la sangría que lo sigue: lo que Markdown confundiría con
# un bloque de código si llegara tal cual.
BLANCOS = re.compile(r"\n\s*")


def _md(bloque: str) -> None:
    """Dibuja HTML propio, aplanando antes su indentación.

    Markdown lee una línea con cuatro espacios o más como bloque de código, así
    que un fragmento indentado llega a la pantalla como texto crudo en vez de
    renderizarse. Pasó con «Cuentas donde no está», cuyo cuerpo empezaba con un
    salto de línea y catorce espacios. Todo el HTML del módulo sale por acá.
    """
    st.markdown(_html_plano(bloque), unsafe_allow_html=True)


def _html_plano(bloque: str) -> str:
    """El mismo HTML en una sola línea, sin sangría."""
    return BLANCOS.sub(" ", bloque).strip()


def _pct(v: float | None, dec: int = 1) -> str:
    return "—" if v is None else f"{v:.{dec}f}%".replace(".", ",")


def _dinero(v: float | None) -> str:
    if v is None:
        return "—"
    return f"$ {miles(v)}" if v >= 100 else f"$ {v:.2f}".replace(".", ",")


# ---------------------------------------------------------------------------
# Piezas visuales
# ---------------------------------------------------------------------------

def _filas_ranking(filas: Sequence[tuple[str, str, float | None, str]],
                   color: str | None = None) -> str:
    """Ranking con barra proporcional. `filas` = (nombre, valor, pct, nota)."""
    color = color or C["blue"]
    if not filas:
        return '<div class="fm-note">Sin datos para este recorte.</div>'
    tope = max((f[2] or 0) for f in filas) or 1
    piezas = []
    for nombre, valor, pct, nota in filas:
        ancho = round((pct or 0) / tope * 100)
        piezas.append(f"""
          <div style="display:flex;flex-direction:column;gap:5px">
            <div style="display:flex;justify-content:space-between;gap:12px;font-size:13.5px">
              <span style="font-weight:500;overflow:hidden;text-overflow:ellipsis;
                    white-space:nowrap">{esc(nombre)}</span>
              <span style="display:flex;gap:10px;align-items:baseline;flex-shrink:0">
                <span class="fm-mono" style="font-weight:600">{esc(valor)}</span>
                <span class="fm-mono" style="color:{C['muted']};font-size:12.5px;
                      width:52px;text-align:right">{_pct(pct)}</span>
              </span>
            </div>
            <div style="height:7px;background:{C['track']};border-radius:4px;overflow:hidden">
              <div style="height:100%;background:{color};border-radius:4px;width:{ancho}%"></div>
            </div>
            <div class="fm-note" style="font-size:11.5px">{esc(nota)}</div>
          </div>""")
    return (f'<div style="display:flex;flex-direction:column;gap:13px">'
            f'{"".join(piezas)}</div>')


def _bloque(titulo: str, nota: str, cuerpo: str, pie: str = "") -> str:
    return f"""
      <div class="fm-card" style="display:flex;flex-direction:column;gap:14px">
        <div>
          <h2 class="fm-h2">{esc(titulo)}</h2>
          <div class="fm-note" style="margin-top:3px">{nota}</div>
        </div>
        {cuerpo}{pie}
      </div>"""


def _serie_html(df: pl.DataFrame, metrica: str, alto: int = 110) -> str:
    """Serie mensual. El mes más alto en naranja, como en Comex Latam."""
    columna = metrica if metrica in df.columns else df.columns[1]
    valores = [v or 0 for v in df[columna]]
    tope = max(valores) or 1
    barras = []
    for periodo, v in zip(df["periodo"], valores):
        alta = v == tope
        barras.append(f"""
          <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:7px">
            <div class="fm-mono" style="font-size:12.5px;font-weight:600;
                 color:{C['orange'] if alta else C['muted']}">
              {esc(_valor(metrica, v))}</div>
            <div style="width:100%;height:{alto}px;display:flex;align-items:flex-end">
              <div style="width:100%;border-radius:3px 3px 0 0;
                   background:{C['bar_cur'] if alta else C['bar_prev']};
                   height:{max(2, round(v / tope * 100))}%"></div>
            </div>
            <div class="fm-note" style="font-size:11.5px">{esc(periodo)}</div>
          </div>""")
    return (f'<div style="display:flex;align-items:flex-end;gap:14px;'
            f'border-bottom:1px solid #E7E9F3;padding-bottom:2px">'
            f'{"".join(barras)}</div>')


PLANTILLA_FILA = '''
              <div style="display:flex;flex-direction:column;gap:5px;
                   padding:11px 0 3px;border-top:1px solid {linea}">
                <div style="display:flex;justify-content:space-between;gap:12px;
                     font-size:13.5px">
                  <span style="font-weight:500;overflow:hidden;
                        text-overflow:ellipsis;white-space:nowrap">
                    <span class="fm-mono" style="color:{tenue};margin-right:8px">
                      {posicion}</span>{nombre}</span>
                  <span style="display:flex;gap:10px;align-items:baseline;flex-shrink:0">
                    <span class="fm-mono" style="font-weight:600">{valor}</span>
                    <span class="fm-mono" style="color:{apagado};font-size:12.5px;
                          width:52px;text-align:right">{pct}</span>
                  </span>
                </div>
                <div class="fm-bar"><div style="width:{ancho}%"></div></div>
                <div class="fm-note" style="font-size:11.5px">{nota}</div>
              </div>'''

COLORES_CANAL = {"VERDE": C["up"], "ROJO": C["down"], "NARANJA": C["orange"],
                 "FISICO": "#8E6FC7", "DOCUMENTARIO": "#5A6180",
                 SIN_DATO: C["bar_prev"]}


def _apilada(tramos_: Sequence[tuple[str, float, str]]) -> str:
    """Barra apilada de composición, con su leyenda."""
    if not tramos_:
        return '<div class="fm-note">Sin datos.</div>'
    barra = "".join(f'<div style="width:{pct}%;background:{color}"></div>'
                    for _, pct, color in tramos_)
    leyenda = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;font-size:12.5px">'
        f'<span style="width:9px;height:9px;border-radius:2px;background:{color}"></span>'
        f'<span style="color:#3B4266">{esc(etiqueta)}</span>'
        f'<span class="fm-mono" style="color:{C["muted"]}">{_pct(pct)}</span></div>'
        for etiqueta, pct, color in tramos_)
    return (f'<div style="display:flex;flex-direction:column;gap:11px">'
            f'<div style="display:flex;height:12px;border-radius:4px;overflow:hidden">'
            f'{barra}</div><div style="display:flex;gap:16px;flex-wrap:wrap">'
            f'{leyenda}</div></div>')


def _nota_fila(r: dict) -> str:
    """El pie de una fila de ranking: guías y las cardinalidades que traiga."""
    piezas = [f"{miles(r['registros'])} guías"] if "registros" in r else []
    for clave, etiqueta in (("n_transportista", "navieras"),
                            ("n_pais", "países"), ("n_actor", "clientes")):
        if r.get(clave) is not None:
            piezas.append(f"{miles(r[clave])} {etiqueta}")
    return " · ".join(piezas)


def _filas_de(df: pl.DataFrame, metrica: str) -> list[tuple]:
    return [(r["valor"], _valor(metrica, r[metrica]), r["share"], _nota_fila(r))
            for r in df.iter_rows(named=True)]


# ---------------------------------------------------------------------------
# Navegación
#
# Todo cambio de estado va en un callback `on_click` / `on_change`, que corre
# antes del rerun. Escribirlo dentro de un `if st.button(...)` es lo que
# Streamlit prohíbe: para ese momento los widgets ya se instanciaron.
# ---------------------------------------------------------------------------

def _elegir_cuadrante(flujo: str, via: str) -> None:
    st.session_state["mf_flujo"] = flujo
    st.session_state["mf_via"] = via


def _abrir_ficha(rol: str, valor: str, flujo: str | None = None,
                 via: str | None = None) -> None:
    st.session_state["mf_ficha"] = (rol, valor)
    if flujo and via:
        _elegir_cuadrante(flujo, via)


def _cerrar_ficha() -> None:
    st.session_state["mf_ficha"] = None


def _ver_ranking(dimension: str, metrica: str) -> None:
    st.session_state["mf_pantalla"] = "rankings"
    st.session_state["mf_ficha"] = None
    st.session_state["mf_rank_dim"] = dimension
    st.session_state["mf_rank_met"] = metrica


def _a_la_tabla(rol: str, valor: str) -> None:
    """Salta a la tabla dinámica con el filtro de la ficha ya puesto."""
    st.session_state["mf_pantalla"] = "tabla"
    st.session_state["mf_ficha"] = None
    st.session_state["mf_heredado"] = (rol, valor)


def _quitar_heredado() -> None:
    st.session_state["mf_heredado"] = None


def _iniciar_estado() -> None:
    por_defecto = {
        "mf_pantalla": "buscador", "mf_flujo": "impo", "mf_via": "maritimo",
        "mf_ficha": None, "mf_q": "", "mf_heredado": None, "mf_chip": "todo",
        "mf_rank_dim": "actor", "mf_rank_met": "contenedores",
        "mf_rank_excluir": True,
    }
    for clave, valor in por_defecto.items():
        st.session_state.setdefault(clave, valor)


# ---------------------------------------------------------------------------
# Selector de manifiesto
# ---------------------------------------------------------------------------

def _sin_datos() -> None:
    """Estado vacío: en la nube no existe el lake, igual que la DB del ISE."""
    _md(f"""
      <div class="fm-card" style="max-width:70ch">
        <div class="fm-kicker" style="color:{C['orange']}">Sin datos cargados</div>
        <h3 style="margin:8px 0 10px">Falta construir el lake de manifiestos</h3>
        <p class="fm-sub">Este módulo consulta los manifiestos de carga ya
          normalizados. Para generarlos, deja los CSV en
          <span class="fm-mono">data/data-manifiestos/</span> y corre:</p>
        <p class="fm-mono" style="background:{C['line']};padding:10px 14px;
           border-radius:8px;font-size:13px">python build_manifiestos.py</p>
        <p class="fm-note">Los manifiestos no se versionan en el repositorio,
          así que el módulo funciona sobre una copia local de la data.</p>
      </div>""")


def _tarjetas_cuadrante(resumen: pl.DataFrame, flujo: str, via: str) -> None:
    """Las cuatro tarjetas grandes de la pantalla de entrada."""
    _md('<div class="fm-kicker" style="margin-bottom:9px">'
                'Qué manifiesto estás mirando</div>')
    columnas = st.columns(len(CUADRANTES))
    for columna, (f, v, ev, ef) in zip(columnas, CUADRANTES):
        fila = resumen.filter((pl.col("flujo") == f) & (pl.col("via") == v))
        with columna:
            if fila.is_empty():
                _md(
                    f'<div class="fm-card" style="padding:14px 16px;opacity:.5">'
                    f'<div style="font-size:13.5px;font-weight:700">'
                    f'{esc(ev)} · {esc(ef)}</div>'
                    f'<div class="fm-note" style="margin-top:8px">Sin guías en '
                    f'este periodo</div></div>')
                continue
            _tarjeta(fila.to_dicts()[0], f, v, ev, ef, (f, v) == (flujo, via))


def _tarjeta(r: dict, flujo: str, via: str, ev: str, ef: str,
             activo: bool) -> None:
    principal = _principal(via)
    detalle = [
        ("Guías aéreas" if via == "aereo" else "Conocimientos de embarque",
         miles(r["registros"])),
        ("Aerolíneas", miles(r["transportistas"])) if via == "aereo"
        else ("Contenedores", _valor("contenedores", r["contenedores"])),
        ("Importadores" if flujo == "impo" else "Exportadores",
         miles(r["actores"])),
    ]
    filas = "".join(
        f'<div style="display:flex;justify-content:space-between;font-size:12.5px;'
        f'padding:5px 0;border-top:1px solid {C["line"]}">'
        f'<span style="color:{C["muted"]}">{esc(k)}</span>'
        f'<span class="fm-mono" style="font-weight:500">{esc(val)}</span></div>'
        for k, val in detalle)
    tinta = C["navy"] if activo else C["ink"]
    borde = (f"border-color:{C['navy']};box-shadow:0 0 0 1px {C['navy']}"
             if activo else "")
    _md(f"""
      <div class="fm-card" style="padding:14px 16px;display:flex;
           flex-direction:column;gap:9px;{borde}">
        <div style="display:flex;align-items:center;gap:7px;
             color:{C['orange'] if activo else C['faint']}">
          {_icono(via)}
          <span style="font-size:13.5px;font-weight:700;color:{tinta}">
            {esc(ev)} · {esc(ef)}</span>
        </div>
        <div style="display:flex;align-items:baseline;gap:6px">
          <span class="fm-mono" style="font-size:26px;font-weight:700;
                letter-spacing:-1.2px;line-height:1;color:{tinta}">
            {esc(_valor(principal, r[principal]))}</span>
          <span class="fm-note" style="font-size:11.5px">
            {esc(_unidad(principal))}</span>
        </div>
        <div>{filas}</div>
      </div>""")
    st.button("Ver este manifiesto", key=f"mf_cuad_{flujo}_{via}",
              use_container_width=True, disabled=activo,
              on_click=_elegir_cuadrante, args=(flujo, via))


def _pills_cuadrante(resumen: pl.DataFrame, flujo: str, via: str) -> None:
    """Selector compacto para las pantallas que no son la entrada."""
    columnas = st.columns(len(CUADRANTES) + 2)
    for columna, (f, v, ev, ef) in zip(columnas, CUADRANTES):
        hay = not resumen.filter(
            (pl.col("flujo") == f) & (pl.col("via") == v)).is_empty()
        with columna:
            if not hay:
                # Deshabilitado quiere decir «es el que estás mirando», así que
                # un manifiesto sin guías va como texto y no como botón apagado.
                _md(
                    f'<div style="border:1px dashed {C["border"]};border-radius:8px;'
                    f'padding:8px 15px;text-align:center;font-size:13.5px;'
                    f'color:{C["faint"]}">{esc(ev)} · {esc(ef)}</div>')
                continue
            st.button(f"{ev} · {ef}", key=f"mf_pill_{f}_{v}",
                      use_container_width=True,
                      disabled=(f, v) == (flujo, via),
                      on_click=_elegir_cuadrante, args=(f, v))


# ---------------------------------------------------------------------------
# Pantalla 1 — Buscador
# ---------------------------------------------------------------------------

def _pantalla_buscador(resumen: pl.DataFrame, flujo: str, via: str,
                       desde: str, hasta: str) -> None:
    _md(
        '<div class="fm-kicker">Datasur · Manifiestos de carga · Perú</div>'
        '<h1 style="margin:4px 0 7px">Buscador de manifiestos</h1>'
        '<p class="fm-sub">Cada guía aérea y cada conocimiento de embarque que '
        'entró o salió del Perú. Escribe un nombre, una empresa, una naviera, '
        'un agente, un producto, un país o una nave, y mira cuánto mueve y con '
        'quién trabaja.</p>')
    st.write("")

    _tarjetas_cuadrante(resumen, flujo, via)
    st.write("")

    st.text_input(
        "Buscar", key="mf_q", label_visibility="collapsed",
        placeholder="Busca un importador, una naviera, un agente, "
                    "una partida, un país, una nave")
    st.radio("Tipo", list(ROLES_CHIP), key="mf_chip", horizontal=True,
             format_func=ETIQUETA_CHIP.get, label_visibility="collapsed")
    termino = st.session_state.get("mf_q", "").strip()

    if termino:
        _resultados(termino, desde, hasta,
                    ROLES_CHIP[st.session_state["mf_chip"]])
        return

    ejemplos = " · ".join(
        f'<span class="fm-mono" style="color:{C["blue"]}">{e}</span>'
        for e in ("MAERSK", "RANSA", "SUPERMERCADOS", "8703", "CHINA", "DP WORLD"))
    _md(f'<div class="fm-note">Ejemplos: {ejemplos}</div>')
    st.write("")
    _mini_rankings(flujo, via, desde, hasta)


def _mini_rankings(flujo: str, via: str, desde: str, hasta: str) -> None:
    """Lo que ya se ve sin escribir nada: tres lecturas de un vistazo."""
    clave = _clave({"flujo": [flujo], "via": [via]})
    principal = _principal(via)
    cajas = "contenedores" if via == "maritimo" else "peso_kg"
    disponibles = _dimensiones(clave, desde, hasta)

    pedidos = []
    if "actor" in disponibles:
        pedidos.append((
            "actor", cajas,
            "Quién trae más contenedores" if via == "maritimo"
            else "Quién mueve más carga",
            "Importadores" if flujo == "impo" else "Exportadores",
            ("transportista", "pais"), True, C["blue"]))
    if "transportista" in disponibles:
        pedidos.append((
            "transportista", principal,
            "Qué naviera mueve más TEUs" if via == "maritimo"
            else "Qué aerolínea mueve más carga",
            "Participación sobre el total del manifiesto",
            ("actor",), False, C["orange"]))
    if "pais" in disponibles:
        pedidos.append((
            "pais", principal,
            "De dónde llega la carga" if flujo == "impo"
            else "A dónde va la carga",
            "País declarado en el manifiesto", ("actor",), False, C["blue"]))
    if not pedidos:
        return

    _md(
        f'<div class="fm-kicker" style="margin-bottom:9px">Sin buscar nada · '
        f'{esc(_etiqueta_cuadrante(flujo, via))} · {esc(desde)} a {esc(hasta)}'
        f'</div>')

    columnas = st.columns(len(pedidos))
    for columna, (dim, met, titulo, nota, cards, excluir, color) in zip(
            columnas, pedidos):
        df = _ranking(dim, met, clave, desde, hasta, cards, (), excluir, clave, 5)
        with columna:
            _md(
                _bloque(titulo, nota, _filas_ranking(_filas_de(df, met), color)))
            st.button("Ver el ranking completo", key=f"mf_mini_{dim}",
                      use_container_width=True, on_click=_ver_ranking,
                      args=(dim, met))


# ---------------------------------------------------------------------------
# Pantalla 2 — Resultados de búsqueda
# ---------------------------------------------------------------------------

def _resultados(termino: str, desde: str, hasta: str,
                roles: tuple[str, ...] = ()) -> None:
    df = _buscar(termino, desde, hasta, roles)
    if df.is_empty():
        acotado = (f" entre los {ETIQUETA_CHIP[st.session_state['mf_chip']].lower()}"
                   if roles else "")
        st.info(f"No hay ninguna entidad que contenga «{termino}»{acotado} en "
                f"los manifiestos de {desde} a {hasta}.")
        return

    roles = list(dict.fromkeys(df["rol"]))
    _md(f"""
      <div class="fm-card" style="border-left:3px solid {C['blue']};padding:14px 18px">
        <div style="font-size:13.5px;color:#3B4266;line-height:1.55">
          <b style="color:{C['navy']}">{len(df)} coincidencias en {len(roles)}
          roles distintos.</b> La misma cadena puede ser naviera, agente de
          aduana, agencia de carga, consignataria y almacén a la vez: son
          negocios distintos bajo el mismo nombre. Cada recuadro es un
          manifiesto, y el porcentaje dice cuánto de ese manifiesto mueve:
          es una participación, no una variación.
        </div>
      </div>""")
    st.write("")

    for rol in roles:
        del_rol = df.filter(pl.col("rol") == rol)
        valores = list(dict.fromkeys(del_rol["valor"]))
        _md(
            f'<div style="display:flex;align-items:baseline;'
            f'justify-content:space-between;margin:6px 0 2px">'
            f'<h2 class="fm-h2">{esc(ROLES[rol].etiqueta)}</h2>'
            f'<span class="fm-note">{len(valores)} '
            f'{"coincidencia" if len(valores) == 1 else "coincidencias"}</span>'
            f'</div>')
        for valor in valores:
            _fila_resultado(del_rol.filter(pl.col("valor") == valor), rol, valor)


def _fila_resultado(df: pl.DataFrame, rol: str, valor: str) -> None:
    """Una entidad, con un recuadro por manifiesto donde aparece."""
    recuadros = "".join(f"""
      <div style="display:flex;align-items:center;gap:8px;background:#F7F8FD;
           border:1px solid {C['border']};border-radius:6px;padding:5px 9px;
           font-size:12px;color:#3B4266">
        <span style="color:{C['faint']};display:flex">{_icono(r['via'])}</span>
        <span style="font-weight:600">
          {esc(_etiqueta_cuadrante(r['flujo'], r['via']))}</span>
        <span style="color:{C['bar_prev']}">|</span>
        <span class="fm-mono">{esc(_valor(r['unidad'], r['metrica']))}
          {esc(_unidad(r['unidad']))} · {_pct(r['share'])}</span>
      </div>""" for r in df.iter_rows(named=True))
    marca = ""
    if bool(df["bucket"][0]):
        marca = ('<span style="font-size:10.5px;letter-spacing:.8px;'
                 'text-transform:uppercase;font-weight:700;border-radius:4px;'
                 'padding:3px 7px;border:1px solid #F6C79A;background:#FEF4EC;'
                 'color:#B0510A">No es una empresa</span>')

    izq, der = st.columns([5, 1])
    with izq:
        _md(f"""
          <div style="display:flex;flex-direction:column;gap:8px;padding:13px 0;
               border-top:1px solid {C['line']}">
            <div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap">
              <span style="font-size:15px;font-weight:600;color:{C['navy']}">
                {esc(valor)}</span>{marca}
            </div>
            <div style="display:flex;gap:7px;flex-wrap:wrap">{recuadros}</div>
          </div>""")
    with der:
        primero = df.to_dicts()[0]
        st.write("")
        st.button("Ver ficha", key=f"mf_res_{rol}_{valor}",
                  use_container_width=True, on_click=_abrir_ficha,
                  args=(rol, valor, primero["flujo"], primero["via"]))


# ---------------------------------------------------------------------------
# Pantalla 3 — Quién mueve más
# ---------------------------------------------------------------------------

def _pantalla_rankings(flujo: str, via: str, desde: str, hasta: str) -> None:
    clave = _clave({"flujo": [flujo], "via": [via]})
    disponibles = [d for d in _dimensiones(clave, desde, hasta) if d in ROLES]
    if not disponibles:
        st.warning("No hay guías con ese recorte. Amplía el periodo o cambia "
                   "de manifiesto en la fila de arriba.")
        return

    _md(
        '<div class="fm-kicker">Datasur · Manifiestos de carga · Perú</div>'
        '<h1 style="margin:4px 0 7px">Quién mueve más</h1>'
        '<p class="fm-sub">El mismo mercado visto desde cada eslabón de la '
        'cadena. Elige a quién quieres rankear y con qué medida.</p>')
    st.write("")

    medibles = [m for m in _metricas(clave, desde, hasta)
                if m not in ("documentos", "duas", "n_partidas")]
    if st.session_state.get("mf_rank_dim") not in disponibles:
        st.session_state["mf_rank_dim"] = disponibles[0]
    if st.session_state.get("mf_rank_met") not in medibles:
        st.session_state["mf_rank_met"] = (
            "contenedores" if "contenedores" in medibles else medibles[0])

    izq, centro, der = st.columns([2, 2, 1.6])
    with izq:
        dimension = st.selectbox("Rankear", disponibles, key="mf_rank_dim",
                                 format_func=lambda d: ROLES[d].etiqueta)
    with centro:
        metrica = st.selectbox("Ordenar por", medibles, key="mf_rank_met",
                               format_func=lambda m: METRICAS[m].etiqueta)
    with der:
        excluir = st.checkbox(
            "Excluir navieras y «a la orden»", key="mf_rank_excluir",
            disabled=dimension != "actor",
            help="Deja fuera a las filiales peruanas de las navieras, que "
                 "figuran como consignatarias de su propia carga, y a los "
                 "conocimientos sin consignatario nombrado.")

    columnas = _columnas_ranking(flujo, via, dimension, medibles, disponibles)
    cardinalidades = tuple(c[2:] for c, _ in columnas if c.startswith("n_"))
    extras = _metricas_de(columnas)
    df = _ranking(dimension, metrica, clave, desde, hasta, cardinalidades,
                  extras, excluir and dimension == "actor", clave, 12)
    if df.is_empty():
        st.warning("Ninguna entidad cumple con este recorte.")
        return

    total = _totales((metrica,), clave, desde, hasta)[etiqueta_metrica(metrica)]
    cuantos = _cardinalidad((dimension,), clave, desde, hasta).get(dimension)
    st.write("")
    _ranking_clickeable(
        df, metrica, dimension, columnas,
        f"{ROLES[dimension].etiqueta} por {METRICAS[metrica].etiqueta.lower()}",
        f"{miles(cuantos)} en total · se muestran los {len(df)} primeros · "
        f"{esc(_valor(metrica, total))} {esc(_unidad(metrica))} en el manifiesto")

    st.write("")
    _paneles_mercado(dimension, metrica, clave, desde, hasta, disponibles,
                     excluir)


def _columnas_ranking(flujo: str, via: str, dimension: str,
                      medibles: Sequence[str],
                      disponibles: Sequence[str]) -> list[tuple[str, str]]:
    """Las columnas del ranking, según el manifiesto y el eslabón que se mira.

    No son fijas: el aéreo no tiene contenedores, y contar «navieras» en el
    ranking de navieras no dice nada, así que ahí se cambia por «clientes».
    """
    valor = "cif_usd" if flujo == "impo" else "fob_usd"
    if via == "maritimo":
        # Las cajas de 20 y de 40 van juntas en una columna, como en el diseño:
        # separarlas sumaba un track y la grilla dejaba de entrar.
        columnas = [("contenedores", "Contenedores"), ("cont_20_40", "20' / 40'"),
                    ("teus", "TEUs")]
    else:
        columnas = [("peso_kg", "Peso")]
    columnas = [(c, e) for c, e in columnas
                if c in medibles or c == "cont_20_40" and "contenedores" in medibles]
    columnas.append(("registros", "BL" if via == "maritimo" else "Guías"))

    if dimension in ROLES_OPERADOR:
        columnas.append(("n_actor", "Clientes"))
    elif "transportista" in disponibles:
        columnas.append(
            ("n_transportista", "Navieras" if via == "maritimo" else "Aerolíneas"))
    if dimension != "pais" and "pais" in disponibles:
        columnas.append(("n_pais", "Países"))
    if valor in medibles:
        columnas.append((valor, "CIF" if flujo == "impo" else "FOB"))
    return columnas


def _grilla_ranking(columnas: Sequence[tuple[str, str]]) -> str:
    """El `grid-template-columns` que comparten el encabezado y cada fila.

    Todos los tracks arrancan en `minmax(0, …)`: con un mínimo fijo la grilla
    no entraba en su columna, se desbordaba hacia la derecha y tapaba los
    botones de «Ver ficha». El síntoma era que los botones parecían borrados.
    """
    return (f"grid-template-columns:26px minmax(0,1.7fr) "
            f"repeat({len(columnas)},minmax(0,0.9fr)) minmax(0,1.5fr);"
            f"min-width:0")


def _ranking_clickeable(df: pl.DataFrame, metrica: str, dimension: str,
                        columnas: Sequence[tuple[str, str]], titulo: str,
                        nota: str) -> None:
    """Ranking donde cada fila lleva a su ficha.

    Va dentro de un `st.container` con clave propia, y no de un `st.markdown`,
    porque una tarjeta escrita a mano no puede contener widgets: los botones
    quedarían fuera del fondo blanco. `st.container(key=…)` deja una clase
    `st-key-fmcard-…` en el DOM, y el CSS del tema la pinta como `.fm-card`.

    El encabezado y las filas comparten el mismo `grid-template-columns`, que
    es lo que mantiene las columnas alineadas entre sí.
    """
    grilla = _grilla_ranking(columnas)
    encabezados = "".join(
        f'<div class="fm-kicker" style="text-align:right;font-size:10px;'
        f'letter-spacing:1px">{esc(e)}</div>' for _, e in columnas)
    tope = max((r["share"] or 0) for r in df.iter_rows(named=True)) or 1

    with st.container(key="fmcard-ranking"):
        _md(f'<div style="display:flex;align-items:baseline;justify-content:'
            f'space-between;gap:14px;margin-bottom:10px">'
            f'<h2 class="fm-h2">{esc(titulo)}</h2>'
            f'<span class="fm-note">{nota}</span></div>')

        izq, der = st.columns([8, 1.15], vertical_alignment="bottom")
        with izq:
            _md(f'<div style="display:grid;{grilla};gap:8px;align-items:end">'
                f'<div></div><div class="fm-kicker" style="font-size:10px;'
                f'letter-spacing:1px">{esc(ROLES[dimension].singular)}</div>'
                f'{encabezados}'
                f'<div class="fm-kicker" style="font-size:10px;'
                f'letter-spacing:1px;text-align:right">Participación</div></div>')
        with der:
            _md('<div class="fm-kicker" style="font-size:10px;'
                'letter-spacing:1px">Ficha</div>')

        for posicion, r in enumerate(df.iter_rows(named=True), start=1):
            celdas = []
            for clave, _ in columnas:
                # La columna por la que se ordenó va en negrita: es la que manda.
                realce = ("font-weight:700" if clave == metrica
                          else "color:" + C["muted"])
                celdas.append(f'<div class="fm-mono" style="text-align:right;'
                              f'font-size:13px;{realce}">'
                              f'{esc(_celda_ranking(clave, r))}</div>')
            izq, der = st.columns([8, 1.15], vertical_alignment="center")
            with izq:
                _md(f'<div style="display:grid;{grilla};gap:8px;'
                    f'align-items:center;padding:9px 0;'
                    f'border-top:1px solid {C["line"]}">'
                    f'<div class="fm-mono" style="color:{C["faint"]};'
                    f'font-size:12.5px">{posicion}</div>'
                    f'<div style="font-size:13.5px;font-weight:500;'
                    f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
                    f'title="{esc(r["valor"])}">{esc(r["valor"])}</div>'
                    f'{"".join(celdas)}'
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f'min-width:0"><div class="fm-bar" style="flex:1">'
                    f'<div style="width:'
                    f'{round((r["share"] or 0) / tope * 100)}%"></div></div>'
                    f'<span class="fm-mono" style="font-size:12px;'
                    f'color:{C["muted"]};flex-shrink:0">{_pct(r["share"])}</span>'
                    f'</div></div>')
            with der:
                st.button("Ver ficha", key=f"mf_rank_{dimension}_{posicion}",
                          use_container_width=True, on_click=_abrir_ficha,
                          args=(dimension, r["valor"]))


def _metricas_de(columnas: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Las métricas del lake que hacen falta para dibujar esas columnas.

    `cont_20_40` no es una métrica: es una celda que muestra dos.
    """
    pedidas: list[str] = []
    for clave, _ in columnas:
        if clave.startswith("n_"):
            continue
        pedidas.extend(("cont_20", "cont_40") if clave == "cont_20_40"
                       else (clave,))
    return tuple(dict.fromkeys(pedidas))


def _celda_ranking(clave: str, fila: dict) -> str:
    """Una celda del ranking: las cardinalidades van sin unidad."""
    if clave == "cont_20_40":
        return f"{miles(fila.get('cont_20'))} / {miles(fila.get('cont_40'))}"
    valor = fila.get(clave)
    if clave.startswith("n_"):
        return "—" if valor is None else miles(valor)
    return _valor(clave, valor)


def _paneles_mercado(dimension: str, metrica: str, clave: tuple, desde: str,
                     hasta: str, disponibles: Sequence[str],
                     excluir: bool = False) -> None:
    """Las tres lecturas del mercado que acompañan al ranking."""
    izq, centro, der = st.columns(3)

    with izq:
        t = _tramos(dimension, metrica, clave, desde, hasta)
        colores = [C["blue"], C["bar_prev"], C["line"]]
        piezas = []
        for i, tramo in enumerate(t["tramos"]):
            if tramo["desde"] == 1:
                etiqueta = f"Top {tramo['hasta']}"
            elif tramo["hasta"]:
                etiqueta = f"Del {tramo['desde']} al {tramo['hasta']}"
            else:
                etiqueta = f"Los otros {miles(0)}".replace("0", "demás")
            piezas.append((etiqueta, tramo["pct"],
                           colores[min(i, len(colores) - 1)]))
        if t["excluido_pct"] > 0:
            piezas.append(("Navieras y «a la orden»", t["excluido_pct"], "#F6C79A"))
        _md(_bloque(
            "Cómo se reparte el mercado",
            f"Cuánto se llevan los primeros, medido en "
            f"{METRICAS[metrica].etiqueta.lower()}",
            _apilada(piezas)))

    with centro:
        dims = tuple(d for d in ("agencia_carga", "transportista", "almacen",
                                 "agente_aduana", "actor") if d in disponibles)
        cuantos = _cardinalidad(dims, clave, desde, hasta)
        filas = []
        for d in dims:
            # Si el ranking de arriba excluye los cajones de actor, este panel
            # también: si no, señala como primer importador a una naviera que
            # el listado de al lado acaba de dejar fuera.
            top = _ranking(d, metrica, clave, desde, hasta, (), (),
                           excluir and d == "actor", clave, 1)
            if top.is_empty():
                continue
            r = top.to_dicts()[0]
            filas.append((f"{ROLES[d].etiqueta} · {r['valor']}",
                          _valor(metrica, r[metrica]), r["share"],
                          f"de {miles(cuantos.get(d))} "
                          f"{ROLES[d].etiqueta.lower()}"))
        _md(_bloque(
            "Quién concentra de verdad",
            "Participación del primero de cada eslabón",
            _filas_ranking(filas, C["navy_soft"])))

    with der:
        costo = _costo(clave, desde, hasta)
        piezas = "".join(f"""
          <div style="border-top:1px solid {C['line']};padding-top:12px">
            <div class="fm-kicker">{esc(etiqueta)}</div>
            <div class="fm-mono" style="font-size:30px;font-weight:700;
                 letter-spacing:-1.3px;color:{C['navy']};line-height:1.15">
              {esc(_dinero(valor))}</div>
            <div class="fm-note">dato en el {_pct(cob, 0)} de las guías</div>
          </div>""" for etiqueta, valor, cob in (
            ("Flete por TEU", costo["usd_por_teu"], costo["cobertura_flete"]),
            ("CIF por kilo", costo["usd_por_kg"], costo["cobertura_cif"])))
        _md(_bloque(
            "Costo implícito del mercado",
            "Solo donde la guía cruzó con una DUA",
            f'<div style="display:flex;flex-direction:column;gap:12px">{piezas}</div>',
            f'<div class="fm-note" style="border-top:1px solid {C["line"]};'
            f'padding-top:11px">Es razón de sumas, no promedio de razones: '
            f'sirve para comparar rutas, navieras y meses entre sí. No es una '
            f'tarifa.</div>'))


# ---------------------------------------------------------------------------
# Ficha de una entidad
# ---------------------------------------------------------------------------

def _ficha(rol: str, valor: str, flujo: str, via: str, desde: str,
           hasta: str) -> None:
    cuadrante = {"flujo": [flujo], "via": [via]}
    clave_cuadrante = _clave(cuadrante)
    clave = _clave({**cuadrante, rol: [valor]})
    principal = _principal(via)
    disponibles = _dimensiones(clave, desde, hasta)

    izq, der = st.columns([4, 1.4])
    with izq:
        marca = ('<span style="color:#B0510A"> · no es una empresa, es un '
                 'cajón de la fuente</span>' if es_bucket(rol, valor) else "")
        _md(
            f'<div class="fm-kicker" style="color:{C["blue"]}">'
            f'{esc(ROLES[rol].singular)}{marca}</div>'
            f'<h1 style="margin:4px 0 6px;font-size:26px">{esc(valor)}</h1>'
            f'<div class="fm-note">{esc(_etiqueta_cuadrante(flujo, via))}, '
            f'de {esc(desde)} a {esc(hasta)}</div>')
    with der:
        st.button("← Volver", key="mf_volver", use_container_width=True,
                  on_click=_cerrar_ficha)
        st.button("Abrir en la tabla", key="mf_a_tabla",
                  use_container_width=True, on_click=_a_la_tabla,
                  args=(rol, valor))
    st.write("")

    medibles = _metricas(clave, desde, hasta)
    pedidas = [m for m in (principal, "contenedores", "registros",
                           "cif_usd" if flujo == "impo" else "fob_usd")
               if m in medibles]
    totales = _totales(tuple(pedidas), clave, desde, hasta)
    del_mercado = _totales((principal,), clave_cuadrante, desde, hasta)
    mio = totales.get(etiqueta_metrica(principal))
    suyo = del_mercado.get(etiqueta_metrica(principal))
    share = round(mio / suyo * 100, 1) if mio and suyo else None

    tarjetas = []
    for m in pedidas:
        v = totales.get(etiqueta_metrica(m))
        if m == principal:
            nota = (f"{_pct(share)} del manifiesto" if share is not None
                    else "del manifiesto")
        elif m in MONETARIAS:
            nota = (f"dato en el {_pct(_cobertura(m, clave, desde, hasta), 0)} "
                    f"de las guías")
        elif m == "registros":
            nota = "documentos de transporte"
        else:
            nota = "en el recorte elegido"
        tarjetas.append((METRICAS[m].etiqueta, _valor(m, v), C["navy"], nota))
    if tarjetas:
        _md(kpis(tarjetas))
        st.write("")

    if rol in ROLES_OPERADOR:
        _ficha_operador(rol, valor, flujo, clave, clave_cuadrante, principal,
                        desde, hasta, disponibles)
    else:
        _ficha_actor(flujo, clave, principal, desde, hasta, disponibles)


def _ficha_actor(flujo: str, clave: tuple, principal: str, desde: str,
                 hasta: str, disponibles: Sequence[str]) -> None:
    """Con quién trabaja un importador o exportador, y qué mueve.

    Los porcentajes de estos bloques son reparto interno (§3.2): el
    denominador es el propio total de la entidad, no el del mercado. Por eso
    `_ranking` va sin `denominador`.
    """
    izq, der = st.columns([1.05, 1])

    with izq:
        bloques = []
        for eslabon in CADENA:
            if eslabon not in disponibles:
                continue
            df = _ranking(eslabon, principal, clave, desde, hasta, (), (), False,
                          None, 6)
            if df.is_empty():
                continue
            borde = (f'border-top:1px solid {C["line"]};padding-top:16px'
                     if bloques else "")
            bloques.append(
                f'<div style="{borde}"><div class="fm-kicker" '
                f'style="margin-bottom:10px">{esc(ROLES[eslabon].etiqueta)}</div>'
                f'{_filas_ranking(_filas_de(df, principal), C["navy_soft"])}</div>')
        if bloques:
            _md(_bloque(
                "Con quién trabaja",
                "Cómo reparte su carga entre los operadores de la cadena. Es la "
                "lectura que decide a quién se le puede vender.",
                "".join(bloques)))

    with der:
        _panel_serie(clave, principal, desde, hasta)
        for dimension, titulo in ((_dim_pais(flujo)), ("partida_4d", "Qué mueve")):
            if dimension not in disponibles:
                continue
            df = _ranking(dimension, principal, clave, desde, hasta, (), (), False,
                          None, 6)
            if df.is_empty():
                continue
            st.write("")
            _md(_bloque(
                titulo,
                f"{DIMENSIONES[dimension].etiqueta}, sobre su propio total",
                _filas_ranking(_filas_de(df, principal), C["navy_soft"])))
        if "canal" in disponibles:
            df = _mix("canal", clave, desde, hasta)
            piezas = [
                ("Sin DUA cruzada" if v == SIN_DATO else v, pct,
                 COLORES_CANAL.get(str(v), C["bar_prev"]))
                for v, pct in zip(df["valor"], df["pct"])]
            st.write("")
            _md(_bloque(
                "Canal de la declaración", "Sobre sus documentos de transporte",
                _apilada(piezas),
                f'<div class="fm-note" style="border-top:1px solid {C["line"]};'
                f'padding-top:11px">El nulo no es un canal: son las guías que '
                f'no cruzaron con una DUA.</div>'))


def _ficha_operador(rol: str, valor: str, flujo: str, clave: tuple,
                    clave_cuadrante: tuple, principal: str, desde: str,
                    hasta: str, disponibles: Sequence[str]) -> None:
    """Cartera de clientes de un operador y las cuentas donde no está."""
    izq, der = st.columns([1.35, 1])

    with izq:
        df = _captura(rol, valor, principal, clave_cuadrante, desde, hasta, 10)
        if not df.is_empty():
            filas = "".join(f"""
              <tr>
                <td style="font-weight:500">{esc(r['valor'])}</td>
                <td class="fm-mono fm-r">{esc(_valor(principal, r['metrica']))}</td>
                <td class="fm-mono fm-r" style="color:{C['muted']}">
                  {esc(_valor(principal, r['total']))}</td>
                <td style="width:190px;padding-left:14px">
                  <div style="display:flex;align-items:center;gap:10px">
                    <div style="flex:1;height:7px;background:{C['track']};
                         border-radius:4px;overflow:hidden">
                      <div style="height:100%;background:{C['orange']};
                           border-radius:4px;
                           width:{min(100, round(r['captura'] or 0))}%"></div>
                    </div>
                    <span class="fm-mono" style="font-size:12.5px;font-weight:700;
                          width:52px;text-align:right">{_pct(r['captura'])}</span>
                  </div>
                </td>
              </tr>""" for r in df.iter_rows(named=True))
            _md(f"""
              <div class="fm-card">
                <h2 class="fm-h2">Sus clientes, y cuánto de cada uno ya tiene</h2>
                <div class="fm-note" style="margin:3px 0 14px">La última columna
                  es la parte del volumen total de ese cliente que hoy viaja con
                  esta entidad. Lo que falta para 100% está en manos de otro.</div>
                <table class="fm-t">
                  <thead><tr><th>Cliente</th>
                    <th class="fm-r">{esc(_unidad(principal))}</th>
                    <th class="fm-r">Total del cliente</th>
                    <th style="padding-left:14px">Participación</th></tr></thead>
                  <tbody>{filas}</tbody></table>
              </div>""")

        for dimension, titulo in (_dim_puerto(flujo), ("capitulo", "Qué mueve")):
            if dimension not in disponibles:
                continue
            top = _ranking(dimension, principal, clave, desde, hasta, (), (), False,
                           None, 6)
            if top.is_empty():
                continue
            st.write("")
            _md(_bloque(
                titulo,
                f"{DIMENSIONES[dimension].etiqueta}, sobre su propio total",
                _filas_ranking(_filas_de(top, principal), C["navy_soft"])))

    with der:
        _panel_serie(clave, principal, desde, hasta, clave_cuadrante)
        st.write("")
        piso = 1500 if principal == "teus" else 100_000
        df = _oportunidad(rol, valor, principal, clave_cuadrante, desde, hasta,
                          piso, 12.0)
        # Con cuántos operadores de este mismo tipo trabaja el cliente.
        def competencia(cuantos: int | None) -> str:
            uno = (cuantos or 0) == 1
            return (ROLES[rol].singular if uno else ROLES[rol].etiqueta).lower()
        if df.is_empty():
            cuerpo = ('<div class="fm-note">No hay cuentas grandes sin atender '
                      'con este recorte.</div>')
        else:
            cuerpo = "".join(f"""
              <div style="display:flex;justify-content:space-between;
                   align-items:center;gap:14px;padding:11px 0;
                   border-top:1px solid {C['line']}">
                <div style="min-width:0">
                  <div style="font-size:13.5px;font-weight:500">{esc(r['valor'])}</div>
                  <div class="fm-note" style="font-size:11.5px">
                    usa {miles(r['alternativas'])}
                    {competencia(r['alternativas'])} · ya tiene el
                    {_pct(r['captura'])}</div>
                </div>
                <div style="text-align:right;flex-shrink:0">
                  <div class="fm-mono" style="font-size:15px;font-weight:700">
                    {esc(_valor(principal, r['total']))}</div>
                  <div class="fm-note" style="font-size:11.5px">
                    {esc(_unidad(principal))} en total</div>
                </div>
              </div>""" for r in df.iter_rows(named=True))
        _md(_bloque(
            "Cuentas donde no está",
            f"Clientes de más de {miles(piso)} {_unidad(principal)} con menos "
            f"del 12% de su carga en esta entidad", cuerpo))


def _dim_pais(flujo: str) -> tuple[str, str]:
    """El país es el de origen en entrada y el de destino en salida."""
    return ("pais", "De qué país viene" if flujo == "impo"
            else "A qué país va")


def _dim_puerto(flujo: str) -> tuple[str, str]:
    """En entrada interesa el puerto de origen; en salida, el de destino.

    `puerto_embarque` en una exportación es el puerto peruano de carga, que no
    dice nada nuevo: lo que se quiere saber es a dónde llegó.
    """
    return (("puerto_embarque", "De qué puerto viene") if flujo == "impo"
            else ("puerto_desembarque", "A qué puerto va"))


def _panel_serie(clave: tuple, principal: str, desde: str, hasta: str,
                 share_sobre: tuple | None = None) -> None:
    df = _serie(principal, clave, desde, hasta, share_sobre)
    if df.is_empty():
        return
    pie = ""
    if share_sobre is not None and "share" in df.columns:
        pasos = " → ".join(_pct(s) for s in df["share"])
        pie = (f'<div style="display:flex;justify-content:space-between;gap:10px;'
               f'border-top:1px solid {C["line"]};padding-top:11px">'
               f'<div class="fm-note">Participación del manifiesto</div>'
               f'<div class="fm-mono" style="font-size:12.5px;font-weight:600">'
               f'{esc(pasos)}</div></div>')
    _md(_bloque("Cómo se movió mes a mes",
                        f"{METRICAS[principal].etiqueta} por periodo",
                        _serie_html(df, principal), pie))


# ---------------------------------------------------------------------------
# Pantalla 4 — Tabla dinámica
# ---------------------------------------------------------------------------

def _pantalla_tabla(flujo: str, via: str, desde: str, hasta: str) -> None:
    cuadrante = {"flujo": [flujo], "via": [via]}
    clave_cuadrante = _clave(cuadrante)
    disponibles = _dimensiones(clave_cuadrante, desde, hasta)
    if not disponibles:
        st.warning("No hay guías con ese recorte. Amplía el periodo o cambia "
                   "de manifiesto en la fila de arriba.")
        return

    _md(
        '<div class="fm-kicker">Datasur · Manifiestos de carga · Perú</div>'
        '<h1 style="margin:4px 0 7px">Tabla dinámica</h1>'
        '<p class="fm-sub">Cuando la ficha no alcanza. Elige por qué agrupar y '
        'qué medir, y arma el cruce que necesites sobre las mismas guías.</p>')

    filtros = dict(cuadrante)
    heredado = st.session_state.get("mf_heredado")
    if heredado and heredado[0] in disponibles:
        rol_h, valor_h = heredado
        filtros[rol_h] = [valor_h]
        izq, der = st.columns([5, 1])
        with izq:
            _md(
                f'<div style="display:flex;align-items:center;gap:9px;'
                f'background:#EEF0FA;border-radius:8px;padding:9px 14px;'
                f'font-size:13px;color:{C["blue"]};margin:8px 0">'
                f'<span style="font-weight:600">Vienes de la ficha de '
                f'{esc(valor_h)},</span>'
                f'<span style="color:{C["muted"]}">se copió su filtro para que '
                f'no lo vuelvas a escribir. Quítalo y la tabla vuelve a todo '
                f'el manifiesto.</span></div>')
        with der:
            st.write("")
            st.button("Quitar filtro", key="mf_quitar_heredado",
                      use_container_width=True, on_click=_quitar_heredado)

    st.write("")
    medibles = _metricas(clave_cuadrante, desde, hasta)
    izq, centro, der = st.columns([2, 1.2, 2], gap="medium")
    with izq:
        filas = st.multiselect(
            f"Agrupar por (hasta {MAX_FILAS_PIVOTE})", disponibles,
            default=[d for d in ("transportista", "pais") if d in disponibles],
            key="mf_filas", format_func=lambda d: DIMENSIONES[d].etiqueta,
            max_selections=MAX_FILAS_PIVOTE,
            placeholder="Elige una dimensión")
        _md(
            '<div class="fm-note">27 campos en cinco familias: Actores, '
            'Logística, Producto, Operación y Tiempo. Se puede agrupar por '
            'cualquiera, no solo por naviera.</div>')
    with centro:
        cruce = [d for d in disponibles if d not in filas]
        columna = st.selectbox(
            "Abrir en columnas", [None] + cruce, key="mf_columna",
            format_func=lambda v: "Sin cruce" if v is None
            else DIMENSIONES[v].etiqueta)
    with der:
        metricas = st.multiselect(
            "Medir", medibles,
            default=[m for m in ("contenedores", "teus", "registros")
                     if m in medibles] or medibles[:1],
            key="mf_metricas", format_func=lambda m: METRICAS[m].etiqueta,
            placeholder="Elige una métrica")

    with st.expander("Filtrar por los valores de una dimensión"):
        f_izq, f_der = st.columns([1, 2])
        with f_izq:
            filtro_dim = st.selectbox(
                "Dimensión", [None] + disponibles, key="mf_filtro_dim",
                format_func=lambda v: "Ninguna" if v is None
                else DIMENSIONES[v].etiqueta)
        with f_der:
            if filtro_dim:
                opciones = _valores(filtro_dim, clave_cuadrante, desde, hasta)
                elegidos = st.multiselect("Valores", opciones,
                                          key="mf_filtro_val",
                                          placeholder="Elige uno o varios")
                if elegidos:
                    filtros[filtro_dim] = elegidos

    if not filas or not metricas:
        st.info("Elige al menos una dimensión para agrupar y una métrica.")
        return

    clave = _clave(filtros)
    # `registros` se pide siempre aunque no esté entre las métricas elegidas:
    # el pie de la tabla necesita cuántas guías hay detrás del resultado.
    totales = _totales(tuple(dict.fromkeys([*metricas, "registros"])),
                       clave, desde, hasta)
    st.write("")
    _md(kpis([
        (METRICAS[m].etiqueta, _valor(m, totales[etiqueta_metrica(m)]),
         C["orange"] if m in MONETARIAS else C["navy"], "total de la selección")
        for m in metricas[:4]
    ]))

    st.write("")
    _nota_cobertura(metricas, clave, desde, hasta)

    df = _pivote(tuple(filas), tuple(metricas), columna, clave, desde, hasta)
    if df.is_empty():
        st.warning("Ninguna guía cumple con esa combinación de filtros.")
        return

    nota = f"{miles(df.height)} filas"
    if df.height > TOPE_VISIBLE:
        nota += f" · se dibujan las {TOPE_VISIBLE} primeras"
    if df.height >= TOPE_TABLA:
        nota += (f" · recortado a las {TOPE_TABLA} primeras, así que la suma de "
                 f"la tabla es menor que el total de arriba")
    if columna:
        nota += (f" · columnas: los {len(df.columns) - len(filas) - 1} valores "
                 f"más frecuentes de {DIMENSIONES[columna].etiqueta}")
    _md(_tabla_html(df, filas, metricas, columna, totales,
                    f"{nota} · los nulos se agrupan como {SIN_DATO}"))

    st.write("")
    _acciones_tabla(totales)


def _acciones_tabla(totales: dict) -> None:
    """Las tres acciones del pie del diseño.

    Van deshabilitadas a propósito: quedaron fuera del alcance de esta fase y
    se dibujan para que el diseño esté completo, no para que funcionen.
    """
    guias = totales.get(etiqueta_metrica("registros"))
    etiquetas = [
        f"Ver estas {miles(guias)} guías una por una" if guias
        else "Ver las guías una por una",
        "Guardar este cuadro",
        "Descargar",
    ]
    columnas = st.columns([2, 1.2, 1, 3])
    for columna, etiqueta in zip(columnas, etiquetas):
        with columna:
            st.button(etiqueta, key=f"mf_accion_{etiqueta[:12]}",
                      use_container_width=True, disabled=True)
    with columnas[-1]:
        _md('<div class="fm-note" style="padding-top:9px">Las tres quedan para '
            'más adelante: no estaban en el alcance de esta fase.</div>')


def _metrica_de_columna(nombre: str, metricas: Sequence[str],
                        cruzada: bool) -> str:
    """Qué métrica representa una columna del resultado.

    En una tabla cruzada de una sola métrica las columnas se llaman por el
    valor cruzado (`2026-06`) y no llevan el nombre de la métrica: sale de la
    métrica única, o si no de la etiqueta que el título contenga.
    """
    if cruzada and len(metricas) == 1:
        return metricas[0]
    for m in metricas:
        if METRICAS[m].etiqueta in nombre:
            return m
    return metricas[0]


def _tabla_html(df: pl.DataFrame, filas: Sequence[str],
                metricas: Sequence[str], columna: str | None,
                totales: dict, nota: str) -> str:
    """La tabla del resultado, con la piel del diseño.

    Se dibuja en HTML y no con `st.dataframe` porque la grilla nativa se pinta
    sobre un canvas y toma el tema de `.streamlit/config.toml`, que es el
    oscuro del Motor ISE: dentro de este módulo quedaba negra sobre tarjetas
    claras. Es el mismo motivo por el que el freemium nunca la usó.
    """
    etiquetas_fila = [DIMENSIONES[f].etiqueta for f in filas]
    cruzada = columna is not None
    columnas = list(df.columns)

    encabezado = "".join(
        "<th>" + esc(c) + "</th>" if c in etiquetas_fila
        else '<th class="fm-r">' + esc(c) + "</th>"
        for c in columnas)

    cuerpo = []
    for r in df.head(TOPE_VISIBLE).iter_rows(named=True):
        celdas = []
        for c in columnas:
            if c in etiquetas_fila:
                celdas.append("<td>" + esc(r[c]) + "</td>")
                continue
            metrica = _metrica_de_columna(c, metricas, cruzada)
            celdas.append('<td class="fm-mono fm-r">'
                          + esc(_valor(metrica, r[c])) + "</td>")
        cuerpo.append("<tr>" + "".join(celdas) + "</tr>")

    # El total es el del recorte y no el de las filas dibujadas: con la tabla
    # recortada la suma de lo que se ve es menor, y la nota al pie lo aclara.
    if not cruzada:
        celdas = ["<td>Total de la selección</td>"]
        celdas += ["<td></td>"] * (len(etiquetas_fila) - 1)
        for c in columnas[len(etiquetas_fila):]:
            metrica = _metrica_de_columna(c, metricas, cruzada)
            celdas.append('<td class="fm-mono fm-r">'
                          + esc(_valor(metrica, totales.get(c))) + "</td>")
        cuerpo.append('<tr class="fm-total">' + "".join(celdas) + "</tr>")

    # El título nombra el cruce que se armó, como en el diseño: la tabla tiene
    # que decir qué está cruzando sin que haya que releer los selectores.
    titulo = " × ".join(etiquetas_fila)
    if cruzada:
        titulo += f" × {DIMENSIONES[columna].etiqueta}"
    cabecera = (f'<div style="display:flex;align-items:baseline;'
                f'justify-content:space-between;gap:14px;margin-bottom:12px">'
                f'<h2 class="fm-h2">{esc(titulo)}</h2>'
                f'<span class="fm-note">{esc(nota)}</span></div>')

    return ('<div class="fm-card" style="overflow-x:auto;padding:18px 22px">'
            + cabecera
            + '<table class="fm-t"><thead><tr>' + encabezado + "</tr></thead>"
            "<tbody>" + "".join(cuerpo) + "</tbody></table></div>")


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
        pct = _cobertura(metrica, clave, desde, hasta)
        if pct < 95:
            avisos.append(f"<b>{esc(METRICAS[metrica].etiqueta)}</b> existe en "
                          f"el {_pct(pct, 0)} de las guías de esta selección")
    if not avisos:
        return
    _md(f"""
      <div class="fm-card" style="border-left:3px solid {C['orange']};padding:12px 16px">
        <div class="fm-note" style="color:{C['muted']};font-size:13px">
          {' · '.join(avisos)}. El valor se declara en la DUA, y no todas las
          guías cruzan con una: el total es un piso, no el comercio completo.
          Peso, TEUs y contenedores sí están en todas.
        </div>
      </div>""")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render() -> None:
    """Dibuja el buscador de manifiestos."""
    css()
    _iniciar_estado()

    if not hay_datos():
        _md(
            '<div class="fm-kicker">Datasur · Manifiestos de carga · Perú</div>'
            '<h1 style="margin:2px 0 6px">Buscador de manifiestos</h1>')
        _sin_datos()
        return

    periodos = _periodos()

    with st.sidebar:
        _md(f"""
          <div style="display:flex;flex-direction:column;gap:2px;margin-bottom:22px">
            <div style="display:flex;align-items:baseline;font-size:24px;
                 font-weight:700;letter-spacing:-0.4px">
              <span style="color:{C['orange']}">D</span>
              <span style="color:#fff">atasur</span>
            </div>
            <div style="font-size:9.5px;letter-spacing:1.6px;text-transform:uppercase;
                 color:#8E9AD8;font-weight:600">Manifiestos de carga · Perú</div>
          </div>""")

        st.radio("Sección", list(PANTALLAS), key="mf_pantalla",
                 format_func=PANTALLAS.get, label_visibility="collapsed",
                 on_change=_cerrar_ficha)
        st.write("")
        desde = st.selectbox("Desde", periodos, index=0, key="mf_desde")
        hasta = st.selectbox("Hasta", periodos, index=len(periodos) - 1,
                             key="mf_hasta")
        _md("""
          <div style="border-top:1px solid #26347F;padding-top:16px;margin-top:18px;
               font-size:12px;line-height:1.5;color:#98A3DC">
            Una fila es <span style="color:#fff">una guía aérea o un conocimiento
            de embarque</span>, no una declaración. El valor de la DUA se reparte
            por peso entre sus guías.
          </div>""")

    if desde > hasta:
        st.warning(f"El periodo va de {desde} a {hasta}: no hay guías en ese "
                   f"rango. Invierte las fechas en la barra lateral.")
        return

    resumen = _resumen(desde, hasta)
    if resumen.is_empty():
        st.warning(f"No hay guías entre {desde} y {hasta}.")
        return

    flujo = st.session_state["mf_flujo"]
    via = st.session_state["mf_via"]
    # El cuadrante elegido puede no existir en el periodo elegido: junio 2026 no
    # tiene importación aérea. Se cae al primero con datos en vez de fallar.
    if resumen.filter((pl.col("flujo") == flujo)
                      & (pl.col("via") == via)).is_empty():
        primero = resumen.to_dicts()[0]
        flujo, via = primero["flujo"], primero["via"]
        st.session_state["mf_flujo"], st.session_state["mf_via"] = flujo, via

    ficha = st.session_state.get("mf_ficha")
    if ficha:
        _pills_cuadrante(resumen, flujo, via)
        st.write("")
        _ficha(ficha[0], ficha[1], flujo, via, desde, hasta)
        return

    pantalla = st.session_state["mf_pantalla"]
    if pantalla == "buscador":
        _pantalla_buscador(resumen, flujo, via, desde, hasta)
        return

    _pills_cuadrante(resumen, flujo, via)
    st.write("")
    if pantalla == "rankings":
        _pantalla_rankings(flujo, via, desde, hasta)
    else:
        _pantalla_tabla(flujo, via, desde, hasta)
