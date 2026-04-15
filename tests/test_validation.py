import pytest
import polars as pl

from src.validation import validate_dataframe


def _make_valid_df():
    return pl.DataFrame({
        "PARTIDA ARANCELARIA": ["2710200012", "2710200012"],
        "UNIDAD DE MEDIDA": ["M3", "M3"],
        "US$ FOB": [100.0, 200.0],
        "CANTIDAD": [50.0, 100.0],
        "DÍA": [1, 2],
        "MES": [1, 2],
        "AÑO": [2025, 2025],
    })


REQUIRED_COLS = ["PARTIDA ARANCELARIA", "UNIDAD DE MEDIDA", "US$ FOB", "CANTIDAD", "DÍA", "MES", "AÑO"]


def test_passes_with_valid_dataframe():
    df = _make_valid_df()
    validate_dataframe(df, REQUIRED_COLS, hs_code="2710200012", hs_col="PARTIDA ARANCELARIA")


def test_raises_when_required_column_is_missing():
    df = _make_valid_df().drop("CANTIDAD")
    with pytest.raises(ValueError, match="CANTIDAD"):
        validate_dataframe(df, REQUIRED_COLS, hs_code="2710200012", hs_col="PARTIDA ARANCELARIA")


def test_raises_when_numeric_column_is_all_null():
    df = _make_valid_df().with_columns(
        pl.lit(None).cast(pl.Float64).alias("CANTIDAD")
    )
    with pytest.raises(ValueError, match="CANTIDAD"):
        validate_dataframe(df, REQUIRED_COLS, hs_code="2710200012", hs_col="PARTIDA ARANCELARIA")


def test_raises_when_hs_code_not_found():
    df = _make_valid_df()
    with pytest.raises(ValueError, match="9999999999"):
        validate_dataframe(df, REQUIRED_COLS, hs_code="9999999999", hs_col="PARTIDA ARANCELARIA")
