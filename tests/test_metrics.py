import pytest
import polars as pl
from datetime import date

from src.metrics import build_hs_monthly_base


def test_returns_one_row_per_month_and_unit():
    df = pl.DataFrame({
        "DIA": [10, 20, 5, 8],
        "MES": [1, 1, 2, 2],
        "AÑO": [2025, 2025, 2025, 2025],
        "hs_code": ["2710200012", "2710200012", "2710200012", "2710200012"],
        "unidad_medida": ["L", "L", "L", "KG"],
        "valor": [100.0, 300.0, 200.0, 50.0],
        "cantidad": [50.0, 150.0, 100.0, 10.0],
    })

    result = build_hs_monthly_base(df, "2710200012")

    expected = pl.DataFrame({
        "periodo": [date(2025, 1, 1), date(2025, 2, 1), date(2025, 2, 1)],
        "hs_code": ["2710200012", "2710200012", "2710200012"],
        "unidad_medida": ["L", "KG", "L"],
        "volumen": [200.0, 10.0, 100.0],
        "precio": [2.0, 5.0, 2.0],
    }).sort(["periodo", "unidad_medida"])

    assert result.sort(["periodo", "unidad_medida"]).equals(expected)


def test_filters_only_selected_hs():
    df = pl.DataFrame({
        "DIA": [10, 15],
        "MES": [1, 1],
        "AÑO": [2025, 2025],
        "hs_code": ["2710200012", "7204490000"],
        "unidad_medida": ["L", "KG"],
        "valor": [100.0, 999.0],
        "cantidad": [50.0, 1.0],
    })

    result = build_hs_monthly_base(df, "2710200012")

    expected = pl.DataFrame({
        "periodo": [date(2025, 1, 1)],
        "hs_code": ["2710200012"],
        "unidad_medida": ["L"],
        "volumen": [50.0],
        "precio": [2.0],
    })

    assert result.equals(expected)


def test_keeps_units_separate_for_same_hs_and_month():
    df = pl.DataFrame({
        "DIA": [10, 11, 12],
        "MES": [1, 1, 1],
        "AÑO": [2025, 2025, 2025],
        "hs_code": ["2710200012", "2710200012", "2710200012"],
        "unidad_medida": ["L", "KG", "L"],
        "valor": [100.0, 40.0, 300.0],
        "cantidad": [50.0, 8.0, 150.0],
    })

    result = build_hs_monthly_base(df, "2710200012").sort(["periodo", "unidad_medida"])

    assert result["unidad_medida"].to_list() == ["KG", "L"]
    assert result["volumen"].to_list() == [8.0, 200.0]
    assert result["precio"].to_list() == [5.0, 2.0]


def test_returns_null_price_when_volume_is_zero():
    df = pl.DataFrame({
        "DIA": [10],
        "MES": [1],
        "AÑO": [2025],
        "hs_code": ["2710200012"],
        "unidad_medida": ["L"],
        "valor": [100.0],
        "cantidad": [0.0],
    })

    result = build_hs_monthly_base(df, "2710200012")

    assert result["volumen"].to_list() == [0.0]
    assert result["precio"].to_list() == [None]


def test_drops_rows_with_null_unit_before_aggregation():
    df = pl.DataFrame({
        "DIA": [10, 20],
        "MES": [1, 1],
        "AÑO": [2025, 2025],
        "hs_code": ["2710200012", "2710200012"],
        "unidad_medida": ["L", None],
        "valor": [100.0, 300.0],
        "cantidad": [50.0, 150.0],
    })

    result = build_hs_monthly_base(df, "2710200012")

    expected = pl.DataFrame({
        "periodo": [date(2025, 1, 1)],
        "hs_code": ["2710200012"],
        "unidad_medida": ["L"],
        "volumen": [50.0],
        "precio": [2.0],
    })

    assert result.equals(expected)