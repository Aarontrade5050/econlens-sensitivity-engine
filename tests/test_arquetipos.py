import polars as pl
import pytest

from src.arquetipos import clasificar_arquetipo, get_archetype
from src.cleaning import add_unit_adjusted_quantity


# -----------------------------------------------------------------------
# clasificar_arquetipo — clasificación por capítulo HS
# -----------------------------------------------------------------------

def test_capitulo_87_es_bien_duradero():
    """Autos (8703...) → BIEN_DURADERO."""
    df = pl.DataFrame({"hs_code": ["8703210010", "8703240090"]})
    result = clasificar_arquetipo(df)
    assert (result["arquetipo_economico"] == "BIEN_DURADERO").all()


def test_capitulo_10_es_commodity():
    """Trigo (1001...) → COMMODITY."""
    df = pl.DataFrame({"hs_code": ["1001110000", "1001910000"]})
    result = clasificar_arquetipo(df)
    assert (result["arquetipo_economico"] == "COMMODITY").all()


def test_capitulo_04_es_perecedero():
    """Lácteos (0401...) → PERECEDERO."""
    df = pl.DataFrame({"hs_code": ["0401100000", "0402211100"]})
    result = clasificar_arquetipo(df)
    assert (result["arquetipo_economico"] == "PERECEDERO").all()


def test_capitulo_desconocido_es_estandar():
    """Textiles (6101...), farmacéuticos (3004...) → ESTANDAR."""
    df = pl.DataFrame({"hs_code": ["6101200000", "3004902900"]})
    result = clasificar_arquetipo(df)
    assert (result["arquetipo_economico"] == "ESTANDAR").all()


# -----------------------------------------------------------------------
# add_unit_adjusted_quantity — guardián de unidades
# -----------------------------------------------------------------------

def _make_unit_df(arquetipo: str, unidad: str, cantidad: float, peso: float) -> pl.DataFrame:
    return pl.DataFrame({
        "arquetipo_economico": [arquetipo],
        "UNIDAD DE MEDIDA": [unidad],
        "CANTIDAD": [cantidad],
        "PESO NETO": [peso],
    })


def test_bien_duradero_con_unidad_U_usa_cantidad_fisica():
    """BIEN_DURADERO + U → cantidad_ajustada = CANTIDAD (precio por unidad física)."""
    df = _make_unit_df("BIEN_DURADERO", "U", cantidad=5.0, peso=15000.0)
    result = add_unit_adjusted_quantity(df)
    assert result["cantidad_ajustada"][0] == 5.0


def test_fallback_usa_peso_neto_cuando_unidad_no_es_U():
    """Cualquier otro caso → cantidad_ajustada = PESO NETO."""
    df = _make_unit_df("BIEN_DURADERO", "KG", cantidad=5.0, peso=15000.0)
    result = add_unit_adjusted_quantity(df)
    assert result["cantidad_ajustada"][0] == 15000.0
