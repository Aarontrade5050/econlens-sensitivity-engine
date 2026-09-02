"""Smoke tests del constructor de tablas con el runner de Streamlit.

Ejercitan el render real. Los errores de esta capa son de datos —un nulo
inesperado, una columna que un formato no trae— y no aparecen leyendo el
código ni corriendo tests unitarios.

`expo_aereo` es el caso de borde de este módulo, el equivalente a Bolivia en
freemium: no declara país ni puerto de destino y solo el 6% de sus guías trae
FOB. Todo cambio se prueba también contra él.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.dashboard_manifiestos as dm

APP = Path(__file__).resolve().parents[1] / "src" / "dashboard.py"
LAKE = Path(__file__).resolve().parents[1] / "data" / "manifiestos"

pytestmark = pytest.mark.skipif(
    not (LAKE.is_dir() and any(LAKE.rglob("*.parquet"))),
    reason="falta el lake de manifiestos: correr `python build_manifiestos.py`",
)

ENTRAR = "Entrar al Constructor"


def _abrir() -> AppTest:
    """App ya dentro del módulo de manifiestos."""
    at = AppTest.from_file(str(APP), default_timeout=300).run()
    boton = next(b for b in at.button if b.label == ENTRAR)
    return boton.click().run()


def _armar(**estado) -> AppTest:
    """Entra al módulo y fija la selección del constructor.

    Los widgets usan `format_func`, así que el estado se fija con el valor
    interno (`"transportista"`), no con la etiqueta que se ve en pantalla.
    """
    at = _abrir()
    for clave, valor in estado.items():
        at.session_state[clave] = valor
    return at.run()


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def test_el_landing_ofrece_el_constructor():
    at = AppTest.from_file(str(APP), default_timeout=300).run()

    assert ENTRAR in [b.label for b in at.button]


def test_entrar_al_constructor_no_revienta():
    at = _abrir()

    assert not at.exception
    assert at.session_state["view_mode"] == "manifiestos"


def test_arranca_con_una_tabla_dibujada():
    """Sin tocar nada ya se ve un cuadro, no un formulario vacío."""
    at = _abrir()

    assert not at.exception
    assert at.dataframe


# ---------------------------------------------------------------------------
# Presets — el camino que va a usar la mayoría
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta", [p.etiqueta for p in dm.PRESETS])
def test_cada_preset_renderiza(etiqueta):
    at = _abrir()
    next(b for b in at.button if b.label == etiqueta).click().run()

    assert not at.exception
    assert at.dataframe


def test_el_preset_de_teus_por_naviera_da_el_cuadro_esperado():
    """Es el caso de uso observado: TEUs y FEUs por naviera."""
    at = _abrir()
    next(b for b in at.button if b.label == "TEUs y FEUs por naviera").click().run()

    df = at.dataframe[0].value
    assert list(df.columns)[:4] == [
        "Naviera / Aerolínea", "TEUs", "Contenedores 40' (FEU)", "Guías / BL",
    ]
    assert len(df) > 0
    assert df["TEUs"].sum() > 0


# ---------------------------------------------------------------------------
# Construcción manual
# ---------------------------------------------------------------------------

def test_tres_dimensiones_y_tres_metricas():
    """El criterio de éxito del checkpoint: 3 dimensiones y 3 métricas reales."""
    at = _armar(
        mf_filas=["pais", "partida_4d", "canal"],
        mf_metricas=["cif_usd", "peso_kg", "registros"],
        mf_flujo="impo",
    )

    assert not at.exception
    df = at.dataframe[0].value
    assert list(df.columns) == [
        "País", "Partida (4 díg.)", "Canal", "CIF (USD)", "Peso (kg)", "Guías / BL",
    ]
    assert len(df) > 0


def test_la_tabla_cruzada_abre_los_periodos_en_columnas():
    at = _armar(mf_filas=["transportista"], mf_metricas=["teus"],
                mf_columna="periodo", mf_via="maritimo")

    assert not at.exception
    columnas = list(at.dataframe[0].value.columns)
    assert columnas[0] == "Naviera / Aerolínea"
    assert "Total" in columnas
    assert any(c.startswith("2026-") for c in columnas)


def test_filtrar_por_los_valores_de_una_dimension():
    at = _armar(mf_filas=["partida_4d"], mf_metricas=["registros"],
                mf_flujo="impo", mf_via="maritimo",
                mf_filtro_dim="transportista", mf_filtro_val=["MAE-MAERSK"])

    assert not at.exception
    assert len(at.dataframe[0].value) > 0


def test_sin_dimensiones_pide_elegir_en_vez_de_fallar():
    at = _armar(mf_filas=[], mf_metricas=["teus"])

    assert not at.exception
    assert at.info
    assert not at.dataframe


def test_un_rango_de_periodos_invertido_avisa_en_vez_de_fallar():
    """Nada impide elegir un `desde` posterior al `hasta`: no puede reventar."""
    at = _armar(mf_filas=["transportista"], mf_metricas=["teus"],
                mf_desde="2026-07", mf_hasta="2026-05")

    assert not at.exception
    assert at.warning


# ---------------------------------------------------------------------------
# expo_aereo — el caso de borde
# ---------------------------------------------------------------------------

def test_exportacion_aerea_renderiza():
    at = _armar(mf_flujo="expo", mf_via="aereo",
                mf_filas=["transportista"], mf_metricas=["peso_kg", "registros"])

    assert not at.exception
    assert len(at.dataframe[0].value) > 0


def test_exportacion_aerea_no_ofrece_pais_ni_puerto():
    """No los declara: ofrecerlos sería ofrecer una tabla de un solo `(sin dato)`."""
    at = _armar(mf_flujo="expo", mf_via="aereo")

    disponibles = dm._dimensiones(
        (("flujo", ("expo",)), ("via", ("aereo",))),
        at.session_state["mf_desde"], at.session_state["mf_hasta"],
    )
    assert "pais" not in disponibles
    assert "puerto_desembarque" not in disponibles
    assert "transportista" in disponibles


def test_exportacion_aerea_con_fob_avisa_la_cobertura():
    """Su FOB cubre ~6% de las guías: el total no es la exportación del país."""
    at = _armar(mf_flujo="expo", mf_via="aereo",
                mf_filas=["transportista"], mf_metricas=["fob_usd"])

    assert not at.exception
    texto = " ".join(m.value for m in at.markdown)
    assert "existe en el" in texto


def test_importacion_maritima_no_avisa_cobertura_de_peso():
    """El aviso es para el valor; el peso está en todas las guías."""
    at = _armar(mf_flujo="impo", mf_via="maritimo",
                mf_filas=["transportista"], mf_metricas=["peso_kg", "teus"])

    texto = " ".join(m.value for m in at.markdown)
    assert "existe en el" not in texto


# ---------------------------------------------------------------------------
# Estado vacío (el caso de Streamlit Cloud, sin lake)
# ---------------------------------------------------------------------------

def test_sin_lake_muestra_el_estado_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "LAKE", tmp_path / "sin-lake")

    at = _abrir()

    assert not at.exception
    assert not at.dataframe
    texto = " ".join(m.value for m in at.markdown)
    assert "build_manifiestos.py" in texto


def test_hay_datos_detecta_el_lake():
    assert dm.hay_datos(LAKE)


def test_hay_datos_es_falso_sin_parquets(tmp_path):
    assert not dm.hay_datos(tmp_path)


# ---------------------------------------------------------------------------
# Formato de columnas
# ---------------------------------------------------------------------------

def _formato(nombre: str, metricas: list[str], cruzada: bool) -> str:
    """`st.column_config.NumberColumn` es un dict, no un objeto."""
    return dm._formato_columna(nombre, metricas, cruzada)["type_config"]["format"]


def test_las_columnas_de_valor_se_formatean_como_dinero():
    assert "$" in _formato("CIF (USD)", ["cif_usd"], False)
    assert "$" not in _formato("TEUs", ["teus"], False)


def test_la_tabla_cruzada_de_una_metrica_hereda_su_formato():
    """Las columnas se llaman `2026-06`, no `CIF (USD)`: el formato es de la métrica."""
    assert "$" in _formato("2026-06", ["cif_usd"], True)
    assert "$" not in _formato("2026-06", ["teus"], True)
