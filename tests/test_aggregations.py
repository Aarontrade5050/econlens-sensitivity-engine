import polars as pl
import pytest
from src.aggregations import (
    compute_entities_over_time,
    compute_market_share,
    compute_price_by_country,
    compute_price_by_route,
    compute_price_spread,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def raw_df() -> pl.DataFrame:
    """Minimal raw DataFrame mimicking df_all.parquet columns."""
    return pl.DataFrame({
        "PARTIDA ARANCELARIA": ["1001", "1001", "1001", "1001", "2002", "2002"],
        "IMPORTADOR": ["EmpresaA", "EmpresaA", "EmpresaB", "EmpresaB", "EmpresaC", "EmpresaC"],
        "US$ FOB": [100.0, 200.0, 150.0, 50.0, 300.0, 120.0],
        "CANTIDAD": [1000.0, 2000.0, 500.0, 500.0, 3000.0, 600.0],
        "ADUANA": ["MARITIMA DEL CALLAO", "PAITA", "MARITIMA DEL CALLAO", "PAITA", "MARITIMA DEL CALLAO", "ILO"],
        "PAÍS DE ADQUISICIÓN": ["CANADA", "ESTADOS UNIDOS", "CANADA", "ARGENTINA", "ESTADOS UNIDOS", "BRASIL"],
        "DÍA": [1, 15, 5, 20, 3, 25],
        "MES": [1, 1, 1, 2, 1, 2],
        "AÑO": [2025, 2025, 2025, 2025, 2025, 2025],
    })


# ---------------------------------------------------------------------------
# compute_market_share
# ---------------------------------------------------------------------------

def test_market_share_returns_expected_columns(raw_df):
    result = compute_market_share(raw_df, hs_col="PARTIDA ARANCELARIA", actor_col="IMPORTADOR", quantity_col="CANTIDAD")
    assert {"hs_code", "actor", "volumen_total", "participacion_pct"}.issubset(set(result.columns))


def test_market_share_pct_sums_to_100_per_hs(raw_df):
    result = compute_market_share(raw_df, hs_col="PARTIDA ARANCELARIA", actor_col="IMPORTADOR", quantity_col="CANTIDAD")
    totals = result.group_by("hs_code").agg(pl.col("participacion_pct").sum().round(1))
    for row in totals.to_dicts():
        assert abs(row["participacion_pct"] - 100.0) < 0.1


def test_market_share_sorted_descending_by_volume(raw_df):
    result = compute_market_share(raw_df, hs_col="PARTIDA ARANCELARIA", actor_col="IMPORTADOR", quantity_col="CANTIDAD")
    hs1 = result.filter(pl.col("hs_code") == "1001")["volumen_total"].to_list()
    assert hs1 == sorted(hs1, reverse=True)


# ---------------------------------------------------------------------------
# compute_price_by_country
# ---------------------------------------------------------------------------

def test_price_by_country_columns(raw_df):
    result = compute_price_by_country(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        country_col="PAÍS DE ADQUISICIÓN",
        value_col="US$ FOB",
        quantity_col="CANTIDAD",
    )
    assert {"hs_code", "pais", "volumen_total", "valor_total", "precio_promedio"}.issubset(set(result.columns))


def test_price_by_country_precio_is_value_over_quantity(raw_df):
    result = compute_price_by_country(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        country_col="PAÍS DE ADQUISICIÓN",
        value_col="US$ FOB",
        quantity_col="CANTIDAD",
    )
    for row in result.to_dicts():
        expected = round(row["valor_total"] / row["volumen_total"], 4)
        assert abs(row["precio_promedio"] - expected) < 1e-3


# ---------------------------------------------------------------------------
# compute_price_by_route
# ---------------------------------------------------------------------------

def test_price_by_route_columns(raw_df):
    result = compute_price_by_route(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        aduana_col="ADUANA",
        value_col="US$ FOB",
        quantity_col="CANTIDAD",
    )
    assert {"hs_code", "aduana", "volumen_total", "valor_total", "precio_promedio"}.issubset(set(result.columns))


def test_price_by_route_excludes_zero_quantity(raw_df):
    df_with_zero = raw_df.with_columns(pl.lit(0.0).alias("CANTIDAD"))
    result = compute_price_by_route(
        df_with_zero,
        hs_col="PARTIDA ARANCELARIA",
        aduana_col="ADUANA",
        value_col="US$ FOB",
        quantity_col="CANTIDAD",
    )
    assert result.is_empty()


# ---------------------------------------------------------------------------
# compute_price_spread
# ---------------------------------------------------------------------------

def test_price_spread_columns(raw_df):
    result = compute_price_spread(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        actor_col="IMPORTADOR",
        value_col="US$ FOB",
        quantity_col="CANTIDAD",
    )
    assert {"hs_code", "actor", "precio_min", "precio_max", "spread_pct"}.issubset(set(result.columns))


def test_price_spread_max_gte_min(raw_df):
    result = compute_price_spread(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        actor_col="IMPORTADOR",
        value_col="US$ FOB",
        quantity_col="CANTIDAD",
    )
    for row in result.to_dicts():
        assert row["precio_max"] >= row["precio_min"]


# ---------------------------------------------------------------------------
# compute_entities_over_time
# ---------------------------------------------------------------------------

def test_entities_over_time_columns(raw_df):
    result = compute_entities_over_time(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        actor_col="IMPORTADOR",
        day_col="DÍA",
        month_col="MES",
        year_col="AÑO",
    )
    assert {"hs_code", "periodo", "n_actores"}.issubset(set(result.columns))


def test_entities_over_time_counts_distinct_actors(raw_df):
    result = compute_entities_over_time(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        actor_col="IMPORTADOR",
        day_col="DÍA",
        month_col="MES",
        year_col="AÑO",
    )
    # hs_code=1001, jan 2025: EmpresaA and EmpresaB both have shipments → 2 actores
    row = result.filter(
        (pl.col("hs_code") == "1001") & (pl.col("periodo").dt.month() == 1)
    ).row(0, named=True)
    assert row["n_actores"] == 2


def test_entities_over_time_sorted_by_periodo(raw_df):
    result = compute_entities_over_time(
        raw_df,
        hs_col="PARTIDA ARANCELARIA",
        actor_col="IMPORTADOR",
        day_col="DÍA",
        month_col="MES",
        year_col="AÑO",
    )
    hs1_periods = result.filter(pl.col("hs_code") == "1001")["periodo"].to_list()
    assert hs1_periods == sorted(hs1_periods)
