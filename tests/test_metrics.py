import pytest
import polars as pl
from datetime import date

from src.metrics import (
    build_hs_monthly_base,
    add_monthly_variation,
    add_rolling_price_volatility,
    add_simple_elasticity,
    add_shock_flag,
    add_ise_score
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

def test_add_simple_elasticity_basic():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [None, 20.0, -25.0],
        "var_pct_precio_mensual": [None, 25.0, -20.0],
    })

    result = add_simple_elasticity(df)

    assert result["elasticidad_simple"].to_list() == [None, 0.8, 1.25]

def test_add_simple_elasticity_handles_zero_price_change():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [10.0],
        "var_pct_precio_mensual": [0.0],
    })

    result = add_simple_elasticity(df)

    assert result["elasticidad_simple"].to_list() == [None]

def test_add_simple_elasticity_handles_nulls():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [None],
        "var_pct_precio_mensual": [10.0],
    })

    result = add_simple_elasticity(df)

    assert result["elasticidad_simple"].to_list() == [None]

def test_add_shock_flag_marks_shock_when_volume_and_price_are_extreme():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [25.0],
        "var_pct_precio_mensual": [6.0],
        "volatilidad_precio_6m": [3.0],
        "elasticidad_simple": [1.5],
    })

    result = add_shock_flag(df)

    assert result["shock_compuesto_flag"].to_list() == [1]

def test_add_shock_flag_marks_shock_when_volume_and_elasticity_are_extreme():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [30.0],
        "var_pct_precio_mensual": [2.0],
        "volatilidad_precio_6m": [2.5],
        "elasticidad_simple": [2.5],
    })

    result = add_shock_flag(df)

    assert result["shock_compuesto_flag"].to_list() == [1]

def test_add_shock_flag_marks_shock_when_price_and_volatility_are_extreme():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [5.0],
        "var_pct_precio_mensual": [6.5],
        "volatilidad_precio_6m": [4.5],
        "elasticidad_simple": [1.0],
    })

    result = add_shock_flag(df)

    assert result["shock_compuesto_flag"].to_list() == [1]

def test_add_shock_flag_returns_zero_when_conditions_are_not_met():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [10.0],
        "var_pct_precio_mensual": [2.0],
        "volatilidad_precio_6m": [3.0],
        "elasticidad_simple": [1.0],
    })

    result = add_shock_flag(df)

    assert result["shock_compuesto_flag"].to_list() == [0]

def test_add_shock_flag_handles_null_volatility_and_elasticity():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [10.0],
        "var_pct_precio_mensual": [2.0],
        "volatilidad_precio_6m": [None],
        "elasticidad_simple": [None],
    })

    result = add_shock_flag(df)

    assert result["shock_compuesto_flag"].to_list() == [0]

def test_add_shock_flag_raises_error_when_required_columns_are_missing():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [10.0],
        "var_pct_precio_mensual": [2.0],
    })

    with pytest.raises(
        ValueError,
        match="Missing required columns for shock detection",
    ):
        add_shock_flag(df)

def test_add_ise_score_creates_score_and_level():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [20.0],
        "var_pct_precio_mensual": [5.0],
        "volatilidad_precio_6m": [4.0],
        "elasticidad_simple": [1.2],
    })

    result = add_ise_score(df)

    assert "ise_score" in result.columns
    assert "ise_nivel" in result.columns
    assert 0 <= result["ise_score"][0] <= 100
    assert result["ise_nivel"][0] in {"Bajo", "Medio", "Alto"}


def test_add_ise_score_handles_nulls_as_zero():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [None],
        "var_pct_precio_mensual": [None],
        "volatilidad_precio_6m": [None],
        "elasticidad_simple": [None],
    })

    result = add_ise_score(df)

    assert result["ise_score"].to_list() == [0.0]
    assert result["ise_nivel"].to_list() == ["Bajo"]


def test_add_ise_score_uses_absolute_values():
    df_negative = pl.DataFrame({
        "var_pct_volumen_mensual": [-20.0],
        "var_pct_precio_mensual": [-5.0],
        "volatilidad_precio_6m": [4.0],
        "elasticidad_simple": [-1.2],
    })

    df_positive = pl.DataFrame({
        "var_pct_volumen_mensual": [20.0],
        "var_pct_precio_mensual": [5.0],
        "volatilidad_precio_6m": [4.0],
        "elasticidad_simple": [1.2],
    })

    result_negative = add_ise_score(df_negative)
    result_positive = add_ise_score(df_positive)

    assert result_negative["ise_score"].to_list() == result_positive["ise_score"].to_list()
    assert result_negative["ise_nivel"].to_list() == result_positive["ise_nivel"].to_list()


def test_ise_score_is_between_0_and_100():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [50.0],
        "var_pct_precio_mensual": [10.0],
        "volatilidad_precio_6m": [5.0],
        "elasticidad_simple": [3.0],
    })

    result = add_ise_score(df)

    score = result["ise_score"][0]

    assert 0 <= score <= 100


def test_add_ise_score_classifies_low_medium_high():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [1.0, 20.0, 80.0],
        "var_pct_precio_mensual": [1.0, 5.0, 10.0],
        "volatilidad_precio_6m": [1.0, 4.0, 8.0],
        "elasticidad_simple": [0.5, 2.0, 10.0],
    })

    result = add_ise_score(df)

    levels = result["ise_nivel"].to_list()

    assert levels[0] == "Bajo"
    assert levels[1] in {"Medio", "Alto"}
    assert levels[2] == "Alto"


def test_add_ise_score_caps_at_100():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [1000.0],
        "var_pct_precio_mensual": [100.0],
        "volatilidad_precio_6m": [50.0],
        "elasticidad_simple": [100.0],
    })

    result = add_ise_score(df)

    assert result["ise_score"][0] == 100.0
    assert result["ise_nivel"][0] == "Alto"


def test_add_ise_score_raises_error_when_required_columns_are_missing():
    df = pl.DataFrame({
        "var_pct_volumen_mensual": [10.0],
        "var_pct_precio_mensual": [2.0],
    })

    with pytest.raises(
        ValueError,
        match="Missing required columns for ISE score calculation",
    ):
        add_ise_score(df)

