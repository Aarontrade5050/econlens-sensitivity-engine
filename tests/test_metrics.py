import pytest
import polars as pl
from datetime import date

from src.metrics import (
    build_hs_monthly_base,
    add_monthly_variation,
    add_rolling_price_volatility,
)


def approx_list(values, **kwargs):
    """Compara listas de floats con tolerancia, preservando None."""
    return [pytest.approx(v, **kwargs) if v is not None else None for v in values]


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


def test_add_monthly_variation_calculates_volume_and_price_changes():
    df = pl.DataFrame({
        "periodo": [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)],
        "hs_code": ["2710200012", "2710200012", "2710200012"],
        "unidad_medida": ["L", "L", "L"],
        "volumen": [100.0, 120.0, 90.0],
        "precio": [2.0, 2.5, 2.0],
    })

    result = add_monthly_variation(df)

    assert result["var_pct_volumen_mensual"].to_list() == approx_list([None, 20.0, -25.0])
    assert result["var_pct_precio_mensual"].to_list() == approx_list([None, 25.0, -20.0])


def test_add_monthly_variation_keeps_units_isolated():
    df = pl.DataFrame({
        "periodo": [
            date(2025, 1, 1),
            date(2025, 2, 1),
            date(2025, 1, 1),
            date(2025, 2, 1),
        ],
        "hs_code": ["2710200012", "2710200012", "2710200012", "2710200012"],
        "unidad_medida": ["L", "L", "KG", "KG"],
        "volumen": [100.0, 120.0, 10.0, 20.0],
        "precio": [2.0, 2.5, 5.0, 4.0],
    }).sort(["hs_code", "unidad_medida", "periodo"])

    result = add_monthly_variation(df)

    assert result["var_pct_volumen_mensual"].to_list() == approx_list([None, 100.0, None, 20.0])
    assert result["var_pct_precio_mensual"].to_list() == approx_list([None, -20.0, None, 25.0])


def test_add_monthly_variation_respects_time_order():
    df = pl.DataFrame({
        "periodo": [date(2025, 3, 1), date(2025, 1, 1), date(2025, 2, 1)],
        "hs_code": ["2710200012", "2710200012", "2710200012"],
        "unidad_medida": ["L", "L", "L"],
        "volumen": [90.0, 100.0, 120.0],
        "precio": [2.0, 2.0, 2.5],
    })

    result = add_monthly_variation(df)

    assert result["periodo"].to_list() == [
        date(2025, 1, 1),
        date(2025, 2, 1),
        date(2025, 3, 1),
    ]
    assert result["var_pct_volumen_mensual"].to_list() == approx_list([None, 20.0, -25.0])
    assert result["var_pct_precio_mensual"].to_list() == approx_list([None, 25.0, -20.0])

def test_add_rolling_price_volatility_adds_nulls_before_full_window():
    df = pl.DataFrame({
        "periodo": [
            date(2025, 1, 1),
            date(2025, 2, 1),
            date(2025, 3, 1),
        ],
        "hs_code": ["2710200012"] * 3,
        "unidad_medida": ["L"] * 3,
        "var_pct_precio_mensual": [None, 10.0, 20.0],
    })

    result = add_rolling_price_volatility(df, window=3)

    assert result["volatilidad_precio_3m"].to_list() == [None, None, None]

def test_add_rolling_price_volatility_computes_std_after_window_is_complete():
    df = pl.DataFrame({
        "periodo": [
            date(2025, 1, 1),
            date(2025, 2, 1),
            date(2025, 3, 1),
            date(2025, 4, 1),
        ],
        "hs_code": ["2710200012"] * 4,
        "unidad_medida": ["L"] * 4,
        "var_pct_precio_mensual": [1.0, 2.0, 3.0, 4.0],
    })

    result = add_rolling_price_volatility(df, window=3)

    values = result["volatilidad_precio_3m"].to_list()

    assert values[0] is None
    assert values[1] is None
    assert values[2] is not None
    assert values[3] is not None

def test_add_rolling_price_volatility_keeps_units_isolated():
    df = pl.DataFrame({
        "periodo": [
            date(2025, 1, 1),
            date(2025, 2, 1),
            date(2025, 3, 1),
            date(2025, 1, 1),
            date(2025, 2, 1),
            date(2025, 3, 1),
        ],
        "hs_code": ["2710200012"] * 6,
        "unidad_medida": ["KG", "KG", "KG", "L", "L", "L"],
        "var_pct_precio_mensual": [1.0, 1.0, 1.0, 1.0, 2.0, 3.0],
    }).sort(["hs_code", "unidad_medida", "periodo"])

    result = add_rolling_price_volatility(df, window=3)

    values = result["volatilidad_precio_3m"].to_list()

    assert values[2] == 0.0
    assert values[5] is not None

def test_add_rolling_price_volatility_raises_error_for_invalid_window():
    df = pl.DataFrame({
        "periodo": [date(2025, 1, 1)],
        "hs_code": ["2710200012"],
        "unidad_medida": ["L"],
        "var_pct_precio_mensual": [1.0],
    })

    with pytest.raises(ValueError, match="Window must be at least 2."):
        add_rolling_price_volatility(df, window=1)