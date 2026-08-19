"""Smoke tests de la vista freemium con el runner de Streamlit.

Ejercitan el render real de las cuatro pantallas: la mayoría de los errores de
esta capa son de datos (un nulo inesperado en una columna), no de lógica, y
solo aparecen al dibujar.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "src" / "dashboard.py"
ARTEFACTOS = Path(__file__).resolve().parents[1] / "resources" / "freemium"

pytestmark = pytest.mark.skipif(
    not (ARTEFACTOS / "country_yearly.parquet").exists(),
    reason="faltan los artefactos freemium: correr `python build_freemium.py`",
)


@pytest.fixture(scope="module")
def freemium() -> AppTest:
    """App ya dentro del módulo freemium."""
    at = AppTest.from_file(str(APP), default_timeout=300).run()
    at.button[0].click().run()
    return at


# ---------------------------------------------------------------------------
# Selector de módulo
# ---------------------------------------------------------------------------

def test_landing_offers_both_modules():
    at = AppTest.from_file(str(APP), default_timeout=300).run()

    assert not at.exception
    assert [b.label for b in at.button] == ["Entrar a Comex Latam", "Entrar al Motor ISE"]


def test_landing_does_not_ask_for_a_file_upfront():
    """El punto del rediseño: la app abre eligiendo análisis, no subiendo data."""
    at = AppTest.from_file(str(APP), default_timeout=300).run()

    assert not at.file_uploader


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pantalla", ["panorama", "producto", "concentracion", "registros"])
@pytest.mark.parametrize("pais", ["BR", "BO"])
def test_every_screen_renders(freemium: AppTest, pantalla: str, pais: str):
    """BO es el caso de borde: economía chica, con partidas sin descripción."""
    freemium.session_state["fm_country"] = pais
    freemium.session_state["fm_screen"] = pantalla
    freemium.run()

    assert not freemium.exception


@pytest.mark.parametrize("flow", ["impo", "expo"])
def test_small_country_renders_records_in_both_flows(freemium: AppTest, flow: str):
    """BO/expo/registros rompía: la descripción de la partida venía nula."""
    freemium.session_state["fm_country"] = "BO"
    freemium.session_state["fm_flow"] = flow
    freemium.session_state["fm_screen"] = "registros"
    freemium.run()

    assert not freemium.exception


@pytest.mark.parametrize("flow", ["impo", "expo"])
def test_both_flows_render(freemium: AppTest, flow: str):
    freemium.session_state["fm_screen"] = "producto"
    freemium.session_state["fm_flow"] = flow
    freemium.run()

    assert not freemium.exception


def test_country_without_base_year_renders(freemium: AppTest):
    """PA solo tiene 2025: toda la ruta de YoY nulo debe dibujarse igual."""
    freemium.session_state["fm_country"] = "PA"
    freemium.session_state["fm_screen"] = "panorama"
    freemium.run()

    assert not freemium.exception
    assert any("s/d" in m.value for m in freemium.markdown)


def test_freemium_never_renders_actor_identity(freemium: AppTest):
    """Los artefactos no traen actor; lo tachado debe ser un placeholder."""
    freemium.session_state["fm_country"] = "CL"
    freemium.session_state["fm_screen"] = "registros"
    freemium.run()

    import polars as pl
    registros = pl.read_parquet(ARTEFACTOS / "registros.parquet")
    assert "company" not in registros.columns
    assert "id_company" not in registros.columns


def test_every_country_in_the_data_has_a_display_name():
    """Un país nuevo sin nombre declarado se mostraría como 'PE' en vez de 'Perú'."""
    import polars as pl

    from src.dashboard_freemium import PAISES

    presentes = set(pl.read_parquet(ARTEFACTOS / "country_yearly.parquet")["country"])
    assert presentes <= set(PAISES), f"sin nombre: {sorted(presentes - set(PAISES))}"
