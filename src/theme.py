"""Paleta, formateadores y CSS compartidos por los dashboards de Datasur.

Vive acá y no dentro de un dashboard para que los módulos que comparten
identidad visual —Comex Latam y el constructor de manifiestos— no puedan
desincronizarse: una sola definición del color y del formato de un número.

El tema es claro y no toma nada de `.streamlit/config.toml`, que define el
oscuro del Motor ISE.
"""

from __future__ import annotations

import html

import streamlit as st

# Paleta del diseño (Datasur).
C: dict[str, str] = {
    "bg": "#F5F6FA", "ink": "#171A2B", "navy": "#0E1A5C", "navy_soft": "#1B2A78",
    "orange": "#EF6C0B", "blue": "#1B32CE", "muted": "#5A6180", "faint": "#6C7599",
    "border": "#E1E4EF", "line": "#EDEFF6", "up": "#0E8A5F", "down": "#C9402F",
    "bar_prev": "#C7CEF0", "bar_cur": "#EF6C0B", "track": "#EDEFF6",
}


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

def usd(v: float | None) -> str:
    if v is None:
        return "s/d"
    if v >= 1e9:
        return f"${v / 1e9:.2f} B"
    if v >= 1e6:
        return f"${v / 1e6:.0f} M"
    if v >= 1e3:
        return f"${v / 1e3:.0f} k"
    return f"${v:.0f}"


def pct(v: float | None, dec: int = 1) -> str:
    """Sin año base no hay crecimiento que mostrar: 's/d', nunca 0%."""
    return "s/d" if v is None else f"{'+' if v >= 0 else ''}{v:.{dec}f}%"


def num(v: float | None, dec: int, sufijo: str = "", vacio: str = "s/d",
        prefijo: str = "") -> str:
    """Número formateado, o el texto de reemplazo si no hay dato.

    Se calcula aparte y no dentro del f-string de la plantilla: anidar f-strings
    con la misma comilla es error de sintaxis en Python 3.11, que es la versión
    que corre Streamlit Cloud.
    """
    return vacio if v is None else f"{prefijo}{v:.{dec}f}{sufijo}"


def miles(v: float | None, vacio: str = "s/d") -> str:
    """Entero con separador de miles: 132.600 TEUs se lee mejor que 132600."""
    if v is None:
        return vacio
    return f"{v:,.0f}".replace(",", ".")


def tone(v: float | None, umbral: float = 0.5) -> str:
    if v is None:
        return C["faint"]
    return C["up"] if v > umbral else C["down"] if v < -umbral else C["ink"]


def esc(s: object) -> str:
    return html.escape(str(s)) if s is not None else ""


def desc(s: str | None, n: int) -> str:
    """Descripción arancelaria recortada. Algunas partidas llegan sin
    descripción en todas las fuentes, así que puede ser nula."""
    if not s:
        return "Sin descripción"
    return esc(s[:n] + "…" if len(s) > n else s)


# ---------------------------------------------------------------------------
# Componentes
# ---------------------------------------------------------------------------

def kpis(items: list[tuple[str, str, str, str]]) -> str:
    """Fila de tarjetas KPI: (etiqueta, valor, color, nota)."""
    cards = "".join(f"""
      <div class="fm-card" style="display:flex;flex-direction:column;gap:7px">
        <div class="fm-kicker" style="letter-spacing:1.3px">{esc(lbl)}</div>
        <div class="fm-mono" style="font-size:29px;font-weight:700;letter-spacing:-1px;
             line-height:1.05;color:{color}">{esc(val)}</div>
        <div class="fm-note">{esc(nota)}</div>
      </div>""" for lbl, val, color, nota in items)
    return (
        f'<div style="display:grid;grid-template-columns:repeat({len(items)},minmax(0,1fr));'
        f'gap:16px">{cards}</div>'
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def css() -> None:
    """Aplica el tema claro de Datasur a la página."""
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
      section[data-testid="stSidebar"] [data-baseweb="tag"] {{ background: {C['blue']} !important; }}
      section[data-testid="stSidebar"] [data-baseweb="tag"] span {{ color: #fff !important; }}

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
      /* `.fm-t th` es más específico que `.fm-r`, así que sin esta regla los
         encabezados quedan a la izquierda y las celdas a la derecha. */
      .fm-t th.fm-r {{ text-align:right; }}
      .fm-lock {{ text-decoration:line-through; text-decoration-color:{C['orange']};
          text-decoration-thickness:1.5px; color:#A8AEC6; filter:blur(2.6px); user-select:none; }}

      [data-testid="stMain"] [data-testid="stExpander"] details {{
          background:#fff; border:1px solid {C['border']}; border-radius:10px; }}
      [data-testid="stMain"] [data-testid="stExpander"] summary p {{
          font-size:13.5px; font-weight:600; color:{C['navy']} !important; }}

      /* Botones: la regla `[data-testid="stMain"] *` de arriba les pinta el
         texto de tinta oscura sobre el gris de Streamlit, que se lee mal y no
         es de la paleta. Acá toman el mismo lenguaje que las tarjetas. */
      [data-testid="stMain"] .stButton > button {{
          background:#fff; border:1px solid {C['border']}; border-radius:8px;
          padding:8px 15px; box-shadow:none; }}
      [data-testid="stMain"] .stButton > button p {{
          color:{C['navy']} !important; font-size:13.5px !important;
          font-weight:600 !important; }}
      [data-testid="stMain"] .stButton > button:hover:not(:disabled) {{
          background:{C['navy']}; border-color:{C['navy']}; }}
      [data-testid="stMain"] .stButton > button:hover:not(:disabled) p {{
          color:#fff !important; }}
      /* El deshabilitado marca la opción vigente —el manifiesto que ya estás
         mirando—, así que va relleno y no apagado. */
      [data-testid="stMain"] .stButton > button:disabled {{
          background:{C['navy']}; border-color:{C['navy']}; opacity:1; }}
      [data-testid="stMain"] .stButton > button:disabled p {{ color:#fff !important; }}

      /* Campo de búsqueda: sin el borde propio de baseweb, que es gris */
      [data-testid="stMain"] .stTextInput div[data-baseweb="input"] {{
          background:transparent; border:none; }}
      [data-testid="stMain"] .stTextInput input {{
          background:#FCFCFE; border:1.5px solid {C['bar_prev']}; border-radius:9px;
          padding:13px 16px; font-size:16px; color:{C['ink']}; }}
      [data-testid="stMain"] .stTextInput input:focus {{
          border-color:{C['blue']}; background:#fff; }}
      [data-testid="stMain"] .stTextInput input::placeholder {{
          color:#8A91AE; font-size:15.5px; }}

      /* Etiquetas de un multiselect en el área clara: azul de la paleta, no el
         rojo que Streamlit trae por defecto */
      [data-testid="stMain"] [data-baseweb="tag"] {{
          background:{C['blue']} !important; border-radius:5px; }}
      [data-testid="stMain"] [data-baseweb="tag"] span {{ color:#fff !important; }}
      [data-testid="stMain"] [data-baseweb="tag"] svg {{ fill:#fff; }}
      /* El rótulo de un selector va como kicker. Solo el de los selectores: la
         misma regla sobre `label p` a secas deja el texto de una casilla de
         verificación en versalitas de 11px y la vuelve ilegible. */
      [data-testid="stMain"] .stSelectbox label p,
      [data-testid="stMain"] .stMultiSelect label p,
      [data-testid="stMain"] .stTextInput label p {{
          font-size:11px !important; letter-spacing:1.6px; text-transform:uppercase;
          font-weight:700 !important; color:{C['faint']} !important; }}
      [data-testid="stMain"] .stCheckbox label p {{
          font-size:13.5px !important; font-weight:500 !important;
          color:{C['ink']} !important; }}

      /* Tarjeta que envuelve bloques de Streamlit —columnas, botones—, donde
         un `st.markdown` no alcanza porque no puede contener otros widgets.
         Se engancha con `st.container(key="fmcard-…")`, que deja la clase
         `st-key-fmcard-…` en el DOM. */
      [data-testid="stMain"] [class*="st-key-fmcard"] {{
          background:#fff; border:1px solid {C['border']}; border-radius:12px;
          padding:18px 22px; }}

      /* Fila de una tabla que lleva a una ficha */
      .fm-t tr.fm-click td {{ cursor:pointer; }}
      .fm-bar {{ height:7px; background:{C['track']}; border-radius:4px; overflow:hidden; }}
      .fm-bar > div {{ height:100%; border-radius:4px; background:{C['blue']}; }}
      .fm-total td {{ border-top:2px solid {C['border']} !important; font-weight:700;
          color:{C['navy']}; }}
    </style>""", unsafe_allow_html=True)
