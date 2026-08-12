"""Vista freemium — Datasur Comex Latam.

Cuatro pantallas sobre data estadística agregada de 9 países LATAM: panorama
del país, detalle de una partida, concentración de mercado y registros.

No procesa nada por sesión: lee los artefactos que dejó `build_freemium.py`.
La identidad de los actores no está en esos artefactos — el tachado de la
pantalla de registros es decorativo, no un filtro de seguridad.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import polars as pl
import streamlit as st

FREEMIUM_DIR = Path(__file__).parent.parent / "resources" / "freemium"

# Paleta del diseño (Datasur Comex Latam).
C = {
    "bg": "#F5F6FA", "ink": "#171A2B", "navy": "#0E1A5C", "navy_soft": "#1B2A78",
    "orange": "#EF6C0B", "blue": "#1B32CE", "muted": "#5A6180", "faint": "#6C7599",
    "border": "#E1E4EF", "line": "#EDEFF6", "up": "#0E8A5F", "down": "#C9402F",
    "bar_prev": "#C7CEF0", "bar_cur": "#EF6C0B", "track": "#EDEFF6",
}

PAISES = {
    "AR": "Argentina", "BO": "Bolivia", "BR": "Brasil", "CL": "Chile",
    "CO": "Colombia", "HN": "Honduras", "MX": "México", "PA": "Panamá",
    "UY": "Uruguay",
}

PANTALLAS = {
    "panorama": "Panorama país",
    "producto": "Producto (HS)",
    "concentracion": "Concentración",
    "registros": "Registros y planes",
}

MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]

PLANES = [
    ("Agregados por mes, socio y HS 6d", "Sí", "Sí"),
    ("Crecimiento YoY y share por socio", "Sí", "Sí"),
    ("Concentración y socio dominante por partida", "Sí", "Sí"),
    ("Identidad de importadores y exportadores", "—", "Sí"),
    ("Índice de Sensibilidad Económica (ISE)", "—", "Sí"),
    ("Riesgo por actor y elasticidad precio-volumen", "—", "Sí"),
    ("Descarga transaccional y API", "—", "Sí"),
]


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

def _usd(v: float | None) -> str:
    if v is None:
        return "s/d"
    if v >= 1e9:
        return f"${v / 1e9:.2f} B"
    if v >= 1e6:
        return f"${v / 1e6:.0f} M"
    if v >= 1e3:
        return f"${v / 1e3:.0f} k"
    return f"${v:.0f}"


def _pct(v: float | None, dec: int = 1) -> str:
    """Sin año base no hay crecimiento que mostrar: 's/d', nunca 0%."""
    return "s/d" if v is None else f"{'+' if v >= 0 else ''}{v:.{dec}f}%"


def _num(v: float | None, dec: int, sufijo: str = "", vacio: str = "s/d") -> str:
    """Número formateado, o el texto de reemplazo si no hay dato.

    Se calcula aparte y no dentro del f-string de la plantilla: anidar f-strings
    con la misma comilla es error de sintaxis en Python 3.11, que es la versión
    que corre Streamlit Cloud.
    """
    return vacio if v is None else f"{v:.{dec}f}{sufijo}"


def _tone(v: float | None, umbral: float = 0.5) -> str:
    if v is None:
        return C["faint"]
    return C["up"] if v > umbral else C["down"] if v < -umbral else C["ink"]


def _esc(s: object) -> str:
    return html.escape(str(s)) if s is not None else ""


def _desc(s: str | None, n: int) -> str:
    """Descripción arancelaria recortada. Algunas partidas llegan sin
    descripción en todas las fuentes, así que puede ser nula."""
    if not s:
        return "Sin descripción"
    return _esc(s[:n] + "…" if len(s) > n else s)


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _tbl(nombre: str) -> pl.DataFrame:
    return pl.read_parquet(FREEMIUM_DIR / f"{nombre}.parquet")


def artefactos_disponibles() -> bool:
    return (FREEMIUM_DIR / "country_yearly.parquet").exists()


@st.cache_data(show_spinner=False)
def _anios() -> tuple[int, int]:
    """Año más reciente con datos y su año de comparación."""
    anios = sorted(_tbl("country_yearly")["anio"].unique().to_list())
    return anios[-1], anios[-1] - 1


@st.cache_data(show_spinner=False)
def _ultimo_periodo() -> date:
    return _tbl("monthly_country")["periodo"].max()


def _f(df: pl.DataFrame, **filtros) -> pl.DataFrame:
    expr = pl.lit(True)
    for col, val in filtros.items():
        expr = expr & (pl.col(col) == val)
    return df.filter(expr)


# ---------------------------------------------------------------------------
# Piezas visuales
# ---------------------------------------------------------------------------

def _css() -> None:
    st.markdown(f"""<style>
      @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

      [data-testid="stAppViewContainer"] > .main {{ background: {C['bg']}; }}
      [data-testid="stMain"] {{ background: {C['bg']}; }}
      [data-testid="stMain"] * {{ font-family: 'Source Sans 3', system-ui, sans-serif; color: {C['ink']}; }}
      [data-testid="stMain"] h1, [data-testid="stMain"] h2, [data-testid="stMain"] h3 {{ color: {C['navy']} !important; }}
      [data-testid="stMain"] .block-container {{ padding-top: 2.2rem; max-width: 1500px; }}

      section[data-testid="stSidebar"] {{ background: {C['navy']}; }}
      section[data-testid="stSidebar"] * {{ color: #C9D0F2; font-family: 'Source Sans 3', system-ui, sans-serif; }}
      section[data-testid="stSidebar"] label p {{ color: #7B88CC !important; font-size: 10px !important;
          letter-spacing: 1.4px; text-transform: uppercase; font-weight: 700 !important; }}

      /* Navegación lateral con aspecto de menú, no de radio */
      section[data-testid="stSidebar"] [role="radiogroup"] label {{
          padding: 9px 12px; border-radius: 7px; margin-bottom: 2px; width: 100%; }}
      section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: {C['navy_soft']}; }}
      section[data-testid="stSidebar"] [role="radiogroup"] label p {{
          color: #C9D0F2 !important; font-size: 14.5px !important; text-transform: none;
          letter-spacing: 0; font-weight: 500 !important; }}
      section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: {C['navy_soft']}; }}
      section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: #fff !important; }}
      section[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ background: transparent !important; }}

      section[data-testid="stSidebar"] [data-baseweb="select"] > div {{
          background: {C['navy_soft']}; border-color: #35459B; color: #fff; }}

      /* Toggle de flujo en el área clara */
      [data-testid="stMain"] [role="radiogroup"] {{ gap: 4px; }}
      [data-testid="stMain"] [role="radiogroup"] label {{
          background: #E7E9F3; padding: 6px 15px; border-radius: 6px; }}
      [data-testid="stMain"] [role="radiogroup"] label:has(input:checked) {{ background: {C['blue']}; }}
      [data-testid="stMain"] [role="radiogroup"] label:has(input:checked) p {{ color: #fff !important; font-weight: 600; }}
      [data-testid="stMain"] [role="radiogroup"] label > div:first-child {{ display: none; }}

      [data-testid="stMain"] [data-baseweb="select"] > div {{
          background: #fff; border-color: {C['border']}; }}

      .fm-card {{ background:#fff; border:1px solid {C['border']}; border-radius:12px; padding:20px 24px; }}
      .fm-mono {{ font-family:'JetBrains Mono', monospace; }}
      .fm-kicker {{ font-size:11px; letter-spacing:1.6px; text-transform:uppercase;
          color:{C['faint']}; font-weight:700; }}
      .fm-sub {{ font-size:14.5px; color:{C['muted']}; max-width:78ch; }}
      .fm-h2 {{ margin:0; font-size:16px; font-weight:700; color:{C['navy']}; }}
      .fm-note {{ font-size:12.5px; color:{C['faint']}; }}
      .fm-t {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
      .fm-t th {{ text-align:left; color:{C['faint']}; font-size:11px; letter-spacing:1.1px;
          text-transform:uppercase; font-weight:700; padding:0 8px 8px 0; }}
      .fm-t td {{ padding:10px 8px 10px 0; border-top:1px solid {C['line']}; }}
      .fm-t tr:hover td {{ background:#F7F8FD; }}
      .fm-r {{ text-align:right; }}
      .fm-lock {{ text-decoration:line-through; text-decoration-color:{C['orange']};
          text-decoration-thickness:1.5px; color:#A8AEC6; filter:blur(2.6px); user-select:none; }}
    </style>""", unsafe_allow_html=True)


def _barras(series: list[tuple[int, float, str]], alto: int, anio_cur: int) -> str:
    """Serie mensual como barras: año actual en naranja, anterior en azul claro."""
    maximo = max((v for _, v, _ in series), default=1) or 1
    barras = "".join(
        f'<div title="{_esc(lbl)}" style="flex:1;border-radius:2px 2px 0 0;min-height:2px;'
        f'height:{max(2, round(v / maximo * 100))}%;'
        f'background:{C["bar_cur"] if a == anio_cur else C["bar_prev"]}"></div>'
        for a, v, lbl in series
    )
    return (
        f'<div style="display:flex;align-items:flex-end;gap:2px;height:{alto}px;'
        f'border-bottom:1px solid #E7E9F3;padding-bottom:1px">{barras}</div>'
    )


def _socios(filas: list[dict], n: int) -> str:
    """Ranking de socios con barra de share y delta en puntos porcentuales."""
    filas = filas[:n]
    maximo = max((f["share_pct"] for f in filas), default=1) or 1
    out = []
    for f in filas:
        delta = f.get("delta_pp")
        txt = "s/d" if delta is None else f"{'+' if delta >= 0 else ''}{delta:.1f} pp"
        out.append(f"""
          <div style="display:flex;flex-direction:column;gap:5px">
            <div style="display:flex;justify-content:space-between;font-size:13.5px">
              <span style="font-weight:500">{_esc(f['partner'])}</span>
              <span style="display:flex;gap:10px;align-items:baseline">
                <span class="fm-mono" style="color:{C['muted']}">{f['share_pct']:.1f}%</span>
                <span class="fm-mono" style="font-weight:700;font-size:12.5px;color:{_tone(delta, 0.1)}">{txt}</span>
              </span>
            </div>
            <div style="height:7px;background:{C['track']};border-radius:4px;overflow:hidden">
              <div style="height:100%;background:{C['blue']};border-radius:4px;
                   width:{round(f['share_pct'] / maximo * 100)}%"></div>
            </div>
          </div>""")
    return f'<div style="display:flex;flex-direction:column;gap:13px">{"".join(out)}</div>'


def _kpis(items: list[tuple[str, str, str, str]]) -> str:
    """Fila de tarjetas KPI: (etiqueta, valor, color, nota)."""
    cards = "".join(f"""
      <div class="fm-card" style="display:flex;flex-direction:column;gap:7px">
        <div class="fm-kicker" style="letter-spacing:1.3px">{_esc(lbl)}</div>
        <div class="fm-mono" style="font-size:29px;font-weight:700;letter-spacing:-1px;
             line-height:1.05;color:{color}">{_esc(val)}</div>
        <div class="fm-note">{_esc(nota)}</div>
      </div>""" for lbl, val, color, nota in items)
    return (
        f'<div style="display:grid;grid-template-columns:repeat({len(items)},minmax(0,1fr));'
        f'gap:16px">{cards}</div>'
    )


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------

def _serie_pais(country: str, flow: str, cur: int) -> list[tuple[int, float, str]]:
    df = _f(_tbl("monthly_country"), country=country, flow=flow).sort("periodo")
    return [
        (r["periodo"].year, r["value"], f'{MESES[r["periodo"].month - 1]} {r["periodo"].year} · {_usd(r["value"])}')
        for r in df.iter_rows(named=True)
    ]


def _panorama(country: str, cur: int, prev: int) -> None:
    cy = _tbl("country_yearly")
    tarjetas = []
    for flow, titulo, base in (("impo", "Importaciones", "CIF"), ("expo", "Exportaciones", "FOB")):
        fila = _f(cy, country=country, flow=flow, anio=cur)
        if fila.is_empty():
            continue
        r = fila.to_dicts()[0]
        tarjetas.append(f"""
          <section class="fm-card" style="display:flex;flex-direction:column;gap:18px">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
              <div style="display:flex;align-items:center;gap:9px">
                <span style="width:10px;height:10px;border-radius:3px;
                     background:{C['orange'] if flow == 'expo' else C['blue']}"></span>
                <span style="font-size:15px;font-weight:700;color:{C['navy']}">{titulo}</span>
                <span class="fm-mono" style="font-size:11px;color:{C['faint']};
                     border:1px solid {C['border']};border-radius:4px;padding:2px 6px">{base}</span>
              </div>
              <span class="fm-note">{cur} vs {prev}</span>
            </div>
            <div style="display:flex;align-items:flex-end;gap:18px">
              <div style="display:flex;flex-direction:column;gap:2px">
                <div class="fm-kicker" style="letter-spacing:1.4px">Crecimiento YoY</div>
                <div class="fm-mono" style="font-size:46px;font-weight:700;line-height:1;
                     letter-spacing:-2px;color:{_tone(r['yoy_pct'])}">{_pct(r['yoy_pct'])}</div>
              </div>
              <div style="display:flex;flex-direction:column;gap:6px;padding-bottom:5px;
                   font-size:13.5px;color:{C['muted']}">
                <div>{cur} <span class="fm-mono" style="color:{C['ink']};font-weight:500">{_usd(r['value'])}</span></div>
                <div>{prev} <span class="fm-mono" style="color:{C['ink']};font-weight:500">{_usd(r['value_prev'])}</span></div>
              </div>
            </div>
            {_barras(_serie_pais(country, flow, cur), 72, cur)}
          </section>""")

    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px">'
        f'{"".join(tarjetas)}</div>', unsafe_allow_html=True)
    st.write("")

    flow = st.session_state["fm_flow"]
    izq, der = st.columns([1.45, 1])

    with izq:
        top = (_f(_tbl("hs_yearly"), country=country, flow=flow, anio=cur)
               .sort("value", descending=True).head(8))
        filas = "".join(
            f'<tr><td class="fm-mono" style="color:{C["blue"]};font-weight:500">{_esc(r["hs_code"])}</td>'
            f'<td>{_desc(r["desc_aran"], 60)}</td>'
            f'<td class="fm-mono fm-r">{_usd(r["value"])}</td>'
            f'<td class="fm-mono fm-r" style="font-weight:700;color:{_tone(r["yoy_pct"])}">{_pct(r["yoy_pct"])}</td></tr>'
            for r in top.iter_rows(named=True))
        st.markdown(f"""<div class="fm-card">
            <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px">
              <h2 class="fm-h2">Productos que mueven la aguja</h2>
              <span class="fm-note">Top 8 por valor</span>
            </div>
            <table class="fm-t"><thead><tr><th>HS 6d</th><th>Descripción</th>
              <th class="fm-r">{cur}</th><th class="fm-r">YoY</th></tr></thead>
              <tbody>{filas}</tbody></table></div>""", unsafe_allow_html=True)

    with der:
        socios = (_f(_tbl("partner_country"), country=country, flow=flow, anio=cur)
                  .sort("share_pct", descending=True).head(8).to_dicts())
        st.markdown(f"""<div class="fm-card">
            <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:16px">
              <h2 class="fm-h2">Socios principales</h2>
              <span class="fm-note">{'Importaciones' if flow == 'impo' else 'Exportaciones'}</span>
            </div>{_socios(socios, 8)}</div>""", unsafe_allow_html=True)


def _producto(country: str, flow: str, cur: int, prev: int) -> None:
    hs_df = (_f(_tbl("hs_yearly"), country=country, flow=flow, anio=cur)
             .sort("value", descending=True))
    relevantes = set(_f(_tbl("partner_share"), country=country, flow=flow, anio=cur)["hs_code"].unique())
    hs_df = hs_df.filter(pl.col("hs_code").is_in(relevantes))
    if hs_df.is_empty():
        st.info("No hay partidas con volumen suficiente para este país y flujo.")
        return

    opciones = hs_df["hs_code"].to_list()
    etiquetas = {
        r["hs_code"]: f'{r["hs_code"]} — {(r["desc_aran"] or "Sin descripción")[:70]}'
        for r in hs_df.iter_rows(named=True)
    }
    if st.session_state.get("fm_hs") not in opciones:
        st.session_state["fm_hs"] = opciones[0]
    hs = st.selectbox("Partida", opciones, key="fm_hs",
                      format_func=lambda h: etiquetas.get(h, h), label_visibility="collapsed")

    r = _f(hs_df, hs_code=hs).to_dicts()[0]
    conc = _f(_tbl("hhi"), country=country, flow=flow, hs_code=hs, anio=cur).to_dicts()
    conc = conc[0] if conc else {}

    n_socios = conc.get("n_socios")
    st.markdown(_kpis([
        ("Crecimiento YoY", _pct(r["yoy_pct"]), _tone(r["yoy_pct"]), f"{cur} contra {prev}, mismo flujo"),
        (f"Valor {cur}", _usd(r["value"]), C["ink"], "Base CIF" if flow == "impo" else "Base FOB"),
        ("Socio dominante", f'{conc.get("top_partner_pct", 0):.0f}%', C["ink"], conc.get("top_partner") or "s/d"),
        ("Se abastece de", "s/d" if n_socios is None else f"{n_socios:.1f} países",
         C["ink"], conc.get("categoria") or "sin socio identificado"),
    ]), unsafe_allow_html=True)
    st.write("")

    izq, der = st.columns(2)
    with izq:
        socios = (_f(_tbl("partner_share"), country=country, flow=flow, hs_code=hs, anio=cur)
                  .sort("share_pct", descending=True).head(8).to_dicts())
        st.markdown(f"""<div class="fm-card">
            <h2 class="fm-h2" style="margin-bottom:4px">Mezcla de socios</h2>
            <div class="fm-note" style="margin-bottom:16px">Share {cur} y variación en puntos
              porcentuales frente a {prev}</div>{_socios(socios, 8)}</div>""", unsafe_allow_html=True)

    with der:
        serie = _f(_tbl("monthly_hs"), country=country, flow=flow, hs_code=hs).sort("periodo")
        pts = [(x["periodo"].year, x["value"],
                f'{MESES[x["periodo"].month - 1]} {x["periodo"].year} · {_usd(x["value"])}')
               for x in serie.iter_rows(named=True)]
        st.markdown(f"""<div class="fm-card">
            <h2 class="fm-h2" style="margin-bottom:4px">Serie mensual</h2>
            <div class="fm-note" style="margin-bottom:16px">Valor mensual declarado.
              Naranja {cur}, azul {prev}.</div>{_barras(pts, 190, cur)}</div>""", unsafe_allow_html=True)

    st.write("")
    multi = (_f(_tbl("hs_yearly"), hs_code=hs, flow=flow, anio=cur)
             .join(_f(_tbl("hhi"), hs_code=hs, flow=flow, anio=cur),
                   on=["country", "flow", "hs_code", "anio"], how="left")
             .sort("value", descending=True))
    filas = []
    for x in multi.iter_rows(named=True):
        socios = _num(x["n_socios"], 1)
        top_pct = _num(x["top_partner_pct"], 0, sufijo="%", vacio="")
        fondo = "#F7F8FD" if x["country"] == country else "transparent"
        filas.append(
            f'<tr style="background:{fondo}">'
            f'<td style="font-weight:500">{_esc(PAISES.get(x["country"], x["country"]))}</td>'
            f'<td class="fm-mono fm-r">{_usd(x["value"])}</td>'
            f'<td class="fm-mono fm-r" style="color:{C["faint"]}">{_usd(x["value_prev"])}</td>'
            f'<td class="fm-mono fm-r" style="font-weight:700;color:{_tone(x["yoy_pct"])}">{_pct(x["yoy_pct"])}</td>'
            f'<td class="fm-mono fm-r">{socios}</td>'
            f'<td style="color:{C["muted"]}">{_esc(x["top_partner"] or "s/d")} '
            f'<span class="fm-mono" style="color:#8A91AD">{top_pct}</span></td></tr>')
    filas = "".join(filas)
    st.markdown(f"""<div class="fm-card">
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px">
          <h2 class="fm-h2">Este producto en los demás países</h2>
          <span class="fm-note">{'Importaciones' if flow == 'impo' else 'Exportaciones'} · orden por valor {cur}</span>
        </div>
        <table class="fm-t"><thead><tr><th>País</th><th class="fm-r">{cur}</th>
          <th class="fm-r">{prev}</th><th class="fm-r">YoY</th><th class="fm-r">Socios</th>
          <th>Socio dominante</th></tr></thead><tbody>{filas}</tbody></table></div>""",
        unsafe_allow_html=True)


def _concentracion(country: str, flow: str, cur: int, prev: int) -> None:
    from src.metrics_freemium import concentracion_relevante

    rel = (concentracion_relevante(_tbl("hhi").lazy(), _tbl("hs_yearly").lazy())
           .filter((pl.col("country") == country) & (pl.col("flow") == flow) & (pl.col("anio") == cur))
           .collect())
    if rel.is_empty():
        st.info("No hay partidas con volumen suficiente para este país y flujo.")
        return

    perdieron = rel.filter(pl.col("delta_socios") < -0.5).height
    dominante = rel.filter(pl.col("categoria") == "1 socio dominante").height
    st.markdown(_kpis([
        ("Partidas analizadas", f"{rel.height:,}", C["ink"], f"con más de USD 50 M en {cur}"),
        ("Socios en mediana", f'{rel["n_socios"].median():.1f}', C["ink"], "equivalente de países proveedores"),
        ("Perdieron socios", f"{perdieron:,}", C["down"] if perdieron else C["ink"],
         f"menos diversificadas que en {prev}"),
        ("Un socio dominante", f"{dominante:,}", C["ink"], "dependen de un único origen"),
    ]), unsafe_allow_html=True)
    st.write("")

    filas = []
    for x in rel.head(15).iter_rows(named=True):
        d = x["delta_socios"]
        d_txt = "s/d" if d is None else f"{'+' if d >= 0 else ''}{d:.1f}"
        ancho = min(100, round(x["n_socios"] / 10 * 100))
        filas.append(
            f'<tr><td class="fm-mono" style="color:{C["blue"]};font-weight:500">{_esc(x["hs_code"])}</td>'
            f'<td>{_desc(x["desc_aran"], 58)}</td>'
            f'<td class="fm-mono fm-r">{_usd(x["value"])}</td>'
            f'<td style="width:150px"><div style="display:flex;align-items:center;gap:9px">'
            f'<div style="flex:1;height:8px;background:{C["track"]};border-radius:4px;overflow:hidden">'
            f'<div style="height:100%;border-radius:4px;background:{C["blue"]};width:{ancho}%"></div></div>'
            f'<span class="fm-mono" style="font-size:12.5px;width:30px;text-align:right">{x["n_socios"]:.1f}</span>'
            f'</div></td>'
            f'<td class="fm-mono fm-r" style="font-weight:700;color:{_tone(d, 0.2)}">{d_txt}</td>'
            f'<td style="color:{C["muted"]}">{_esc(x["top_partner"] or "s/d")}</td></tr>')

    st.markdown(f"""<div class="fm-card">
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px">
          <h2 class="fm-h2">Dónde se está sustituyendo el origen</h2>
          <span class="fm-note">{PAISES.get(country, country)} · {'Importaciones' if flow == 'impo' else 'Exportaciones'}</span>
        </div>
        <div class="fm-note" style="margin-bottom:18px;max-width:82ch">
          La concentración se expresa como el número equivalente de países que abastecen la
          partida. Ordenado por cuántos socios perdió frente a {prev}: arriba, las partidas
          que más concentraron su origen en un año.
        </div>
        <table class="fm-t"><thead><tr><th>HS 6d</th><th>Descripción</th>
          <th class="fm-r">Valor {cur}</th><th>Se abastece de</th><th class="fm-r">Δ socios</th>
          <th>Socio dominante</th></tr></thead><tbody>{"".join(filas)}</tbody></table></div>""",
        unsafe_allow_html=True)
    st.write("")

    st.markdown(f"""
      <section style="border:1px dashed #F0A76A;background:#FEF6EF;border-radius:12px;padding:20px 24px;
           display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap">
        <div style="display:flex;flex-direction:column;gap:5px;max-width:74ch">
          <div style="font-size:15px;font-weight:700;color:{C['navy']}">¿Por qué cambió la concentración de esta partida?</div>
          <div style="font-size:13.5px;color:{C['muted']}">La descomposición por actor, el Índice de
            Sensibilidad Económica (ISE) y la elasticidad precio-volumen requieren la base transaccional completa.</div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="fm-mono" style="font-size:12px;color:#A5701F">PREMIUM</span>
          <div style="background:{C['orange']};color:#fff;font-weight:700;font-size:14px;
               padding:11px 20px;border-radius:24px">Ver en EconoLens Pro</div>
        </div>
      </section>""", unsafe_allow_html=True)


def _registros(country: str, flow: str, cur: int) -> None:
    hs = st.session_state.get("fm_hs")
    regs = _f(_tbl("registros"), country=country, flow=flow)
    if hs:
        regs = _f(regs, hs_code=hs)
    if regs.is_empty():
        regs = _f(_tbl("registros"), country=country, flow=flow)
    if regs.is_empty():
        st.info("No hay registros para este país y flujo.")
        return

    total = regs.height
    muestra = regs.sort("periodo", descending=True).head(12)
    desc = _f(_tbl("hs_yearly"), country=country, flow=flow, hs_code=muestra["hs_code"][0], anio=cur)
    desc_txt = desc["desc_aran"][0] if not desc.is_empty() else ""

    filas = "".join(
        f'<tr><td class="fm-mono" style="color:{C["muted"]}">{x["periodo"]:%Y-%m}</td>'
        f'<td style="font-weight:500">{_esc(x["partner"])}</td>'
        f'<td class="fm-mono" style="color:{C["blue"]}">{_esc(x["hs_code"])}</td>'
        f'<td class="fm-mono fm-r">{_usd(x["value"])}</td>'
        f'<td class="fm-mono fm-r" style="color:{C["muted"]}">{x["share_mes"]:.1f}%</td>'
        f'<td><span class="fm-mono fm-lock">IMPORTADORA GLOBAL SAC</span></td>'
        f'<td><span class="fm-mono fm-lock">20{100000000 + x["periodo"].month * 7654321}</span></td></tr>'
        for x in muestra.iter_rows(named=True))

    st.markdown(f"""<div class="fm-card" style="padding:0;overflow:hidden">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;
             padding:18px 24px;border-bottom:1px solid {C['line']};flex-wrap:wrap">
          <div style="display:flex;flex-direction:column;gap:3px">
            <h2 class="fm-h2">Registros agregados</h2>
            <div class="fm-note">{PAISES.get(country, country)} ·
              {'Importaciones' if flow == 'impo' else 'Exportaciones'} · {_esc(hs or '')} {_esc(desc_txt[:60])}</div>
          </div>
          <div class="fm-note">Columnas de actor disponibles solo en premium</div>
        </div>
        <div style="padding:0 24px">
          <table class="fm-t"><thead><tr><th>Periodo</th><th>Socio</th><th>HS 6d</th>
            <th class="fm-r">Valor USD</th><th class="fm-r">Share mes</th><th>Actor</th>
            <th>ID fiscal</th></tr></thead><tbody>{filas}</tbody></table>
        </div>
        <div style="padding:16px 24px;background:#FAFBFE;border-top:1px solid {C['line']};
             display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap">
          <div class="fm-note">Mostrando 12 de <span class="fm-mono" style="color:{C['ink']}">{total:,}</span>
            registros. El freemium agrega por mes y socio.</div>
          <div style="display:flex;align-items:center;gap:10px">
            <span class="fm-mono" style="font-size:12px;color:#A5701F">PREMIUM</span>
            <div style="background:{C['orange']};color:#fff;font-weight:700;font-size:14px;
                 padding:10px 18px;border-radius:24px">Desbloquear actores</div>
          </div>
        </div></div>""", unsafe_allow_html=True)
    st.write("")

    izq, der = st.columns(2)
    with izq:
        filas_plan = "".join(
            f'<div style="display:grid;grid-template-columns:minmax(0,1fr) 74px 74px;gap:10px;'
            f'align-items:center;padding:10px 0;border-top:1px solid {C["line"]};font-size:13.5px">'
            f'<div>{_esc(f)}</div>'
            f'<div class="fm-mono" style="text-align:center;color:{C["muted"]}">{free}</div>'
            f'<div class="fm-mono" style="text-align:center;color:{C["orange"]};font-weight:700">{pro}</div></div>'
            for f, free, pro in PLANES)
        st.markdown(f'<div class="fm-card"><h2 class="fm-h2" style="margin-bottom:14px">'
                    f'Qué incluye cada plan</h2>{filas_plan}</div>', unsafe_allow_html=True)

    with der:
        st.markdown(f"""<div style="background:{C['navy']};border-radius:12px;padding:24px;
             display:flex;flex-direction:column;gap:14px;justify-content:center;height:100%">
            <div class="fm-kicker" style="color:#8E9AD8">Metodología</div>
            <div style="font-size:14.5px;line-height:1.6;color:#DDE2F7">Las importaciones se declaran
              en CIF y las exportaciones en FOB. Los dos flujos se muestran lado a lado y nunca se
              suman en un mismo total; las comparaciones interanuales se hacen siempre dentro del
              mismo flujo y la misma base de valoración.</div>
            <div style="font-size:14.5px;line-height:1.6;color:#DDE2F7">Cuando un país no tiene aún
              el año base cargado, el crecimiento se muestra como <span class="fm-mono">s/d</span>
              en vez de cero. El valor sin socio declarado se agrupa como
              <span class="fm-mono">No declarado</span> y se excluye del cálculo de concentración.</div>
          </div>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def render() -> None:
    """Dibuja la vista freemium completa."""
    _css()

    if not artefactos_disponibles():
        st.error(
            "No se encontraron los artefactos de la capa freemium en `resources/freemium/`. "
            "Generalos con `python build_freemium.py`."
        )
        return

    cur, prev = _anios()
    paises = sorted(_tbl("country_yearly")["country"].unique().to_list())

    with st.sidebar:
        st.markdown(f"""
          <div style="display:flex;flex-direction:column;gap:2px;margin-bottom:22px">
            <div style="display:flex;align-items:baseline;font-size:24px;font-weight:700;letter-spacing:-0.4px">
              <span style="color:{C['orange']}">E</span><span style="color:#fff">conoLens</span>
            </div>
            <div style="font-size:9.5px;letter-spacing:1.6px;text-transform:uppercase;
                 color:#8E9AD8;font-weight:600">Comex Latam · Freemium</div>
          </div>""", unsafe_allow_html=True)

        pantalla = st.radio("Sección", list(PANTALLAS), key="fm_screen",
                            format_func=PANTALLAS.get, label_visibility="collapsed")
        st.write("")
        country = st.selectbox("País", paises, key="fm_country",
                               format_func=lambda c: PAISES.get(c, c))
        st.write("")
        st.markdown(f"""
          <div style="border-top:1px solid #26347F;padding-top:16px;font-size:12px;
               line-height:1.5;color:#98A3DC">
            Nota metodológica: <span style="color:#fff">importaciones en CIF</span>,
            <span style="color:#fff">exportaciones en FOB</span>. No se mezclan en un mismo total.
          </div>
          <div class="fm-mono" style="font-size:11.5px;color:#7B88CC;margin-top:10px">
            {prev}–{cur} · HS 6 dígitos · {len(paises)} países
          </div>""", unsafe_allow_html=True)

    if "fm_flow" not in st.session_state:
        st.session_state["fm_flow"] = "impo"

    titulos = {
        "panorama": ("Panorama de comercio exterior",
                     "Crecimiento interanual del valor declarado, con importaciones y exportaciones "
                     "lado a lado. Cada flujo se compara solo contra sí mismo."),
        "producto": ("Detalle de partida",
                     "Una subpartida de 6 dígitos: quién la abastece, cómo evolucionó mes a mes y "
                     "cómo se ve en los demás países."),
        "concentracion": ("Concentración de mercado",
                          "Qué partidas dependen de pocos orígenes y cuáles están repartidas, "
                          "ordenadas por cuánto cambiaron en el último año."),
        "registros": ("Registros y planes",
                      "Los agregados por mes y socio son abiertos. La identidad de los actores y "
                      "sus métricas derivadas viven en premium."),
    }
    titulo, sub = titulos[pantalla]

    izq, der = st.columns([3, 1])
    with izq:
        st.markdown(
            f'<div class="fm-kicker">{_esc(PAISES.get(country, country))}</div>'
            f'<h1 style="margin:2px 0 6px;font-size:30px;line-height:1.15;font-weight:700;'
            f'letter-spacing:-0.7px;color:{C["navy"]}">{titulo}</h1>'
            f'<div class="fm-sub">{sub}</div>', unsafe_allow_html=True)
    with der:
        if pantalla != "panorama":
            st.radio("Flujo", ["impo", "expo"], key="fm_flow", horizontal=True,
                     format_func=lambda f: "Importaciones" if f == "impo" else "Exportaciones",
                     label_visibility="collapsed")
        st.markdown(f'<div class="fm-note" style="text-align:right">Dato al '
                    f'<span class="fm-mono" style="color:{C["ink"]}">'
                    f'{MESES[_ultimo_periodo().month - 1]} {_ultimo_periodo().year}</span></div>',
                    unsafe_allow_html=True)

    st.write("")
    flow = st.session_state["fm_flow"]

    if pantalla == "panorama":
        _panorama(country, cur, prev)
    elif pantalla == "producto":
        _producto(country, flow, cur, prev)
    elif pantalla == "concentracion":
        _concentracion(country, flow, cur, prev)
    else:
        _registros(country, flow, cur)
