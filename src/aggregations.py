# aggregation functions for market analytics (Tab 1-3 del dashboard)
# Trabajan sobre el DataFrame raw (df_all.parquet), no sobre la tabla ISE.
import polars as pl

_HS_COL = "PARTIDA ARANCELARIA"
_ACTOR_COL = "IMPORTADOR"
_VALUE_COL = "US$ FOB"
_QUANTITY_COL = "CANTIDAD"
_ADUANA_COL = "ADUANA"
_COUNTRY_COL = "PAÍS DE ORIGEN"
_DAY_COL = "DÍA"
_MONTH_COL = "MES"
_YEAR_COL = "AÑO"

_SUPPLIER_COLS: dict[str, str] = {
    "PROVEEDOR":            "supplier_proveedor",
    "EXPORTADOR":           "supplier_exportador",
    "EMPRESA EXPORTADORA":  "supplier_empresa_exportadora",
    "EMBARCADOR":           "supplier_embarcador",
    "PROBABLE EMBARCADOR":  "supplier_probable_embarcador",
}


def _add_periodo(
    df: pl.DataFrame,
    day_col: str = _DAY_COL,
    month_col: str = _MONTH_COL,
    year_col: str = _YEAR_COL,
) -> pl.DataFrame:
    """Add a 'periodo' column (first day of month) from day/month/year columns."""
    return (
        df.with_columns([
            pl.col(day_col).cast(pl.Int32),
            pl.col(month_col).cast(pl.Int32),
            pl.col(year_col).cast(pl.Int32),
        ])
        .with_columns(
            pl.date(pl.col(year_col), pl.col(month_col), pl.col(day_col)).alias("_fecha")
        )
        .with_columns(pl.col("_fecha").dt.truncate("1mo").alias("periodo"))
        .drop("_fecha")
    )


def compute_market_share(
    df: pl.DataFrame,
    hs_col: str = _HS_COL,
    actor_col: str = _ACTOR_COL,
    quantity_col: str = _QUANTITY_COL,
    value_col: str = _VALUE_COL,
) -> pl.DataFrame:
    """Volume and FOB-value market share per actor per hs_code.

    Returns columns: hs_code, actor, volumen_total, participacion_pct,
                     valor_fob_total, participacion_fob_pct.
    Sorted by hs_code asc, volumen_total desc.
    """
    return (
        df.filter(pl.col(actor_col).is_not_null())
        .group_by([hs_col, actor_col])
        .agg([
            pl.col(quantity_col).sum().alias("volumen_total"),
            pl.col(value_col).sum().alias("valor_fob_total"),
        ])
        .rename({hs_col: "hs_code", actor_col: "actor"})
        .with_columns([
            (
                pl.col("volumen_total")
                / pl.col("volumen_total").sum().over("hs_code")
                * 100
            ).round(2).alias("participacion_pct"),
            (
                pl.col("valor_fob_total")
                / pl.col("valor_fob_total").sum().over("hs_code")
                * 100
            ).round(2).alias("participacion_fob_pct"),
        ])
        .sort(["hs_code", "volumen_total"], descending=[False, True])
    )


def compute_price_by_country(
    df: pl.DataFrame,
    hs_col: str = _HS_COL,
    country_col: str = _COUNTRY_COL,
    value_col: str = _VALUE_COL,
    quantity_col: str = _QUANTITY_COL,
) -> pl.DataFrame:
    """Weighted average FOB price (USD/unit) by country of acquisition per hs_code.

    Returns columns: hs_code, pais, volumen_total, valor_total, precio_promedio.
    Sorted by hs_code asc, volumen_total desc.
    """
    return (
        df.filter(
            pl.col(country_col).is_not_null()
            & (pl.col(quantity_col) > 0)
        )
        .group_by([hs_col, country_col])
        .agg([
            pl.col(quantity_col).sum().alias("volumen_total"),
            pl.col(value_col).sum().alias("valor_total"),
        ])
        .rename({hs_col: "hs_code", country_col: "pais"})
        .with_columns(
            (pl.col("valor_total") / pl.col("volumen_total"))
            .round(4)
            .alias("precio_promedio")
        )
        .sort(["hs_code", "volumen_total"], descending=[False, True])
    )


def compute_price_by_route(
    df: pl.DataFrame,
    hs_col: str = _HS_COL,
    aduana_col: str = _ADUANA_COL,
    value_col: str = _VALUE_COL,
    quantity_col: str = _QUANTITY_COL,
) -> pl.DataFrame:
    """Weighted average FOB price by customs entry point (aduana) per hs_code.

    Returns columns: hs_code, aduana, volumen_total, valor_total, precio_promedio.
    Sorted by hs_code asc, volumen_total desc.
    """
    return (
        df.filter(
            pl.col(aduana_col).is_not_null()
            & (pl.col(quantity_col) > 0)
        )
        .group_by([hs_col, aduana_col])
        .agg([
            pl.col(quantity_col).sum().alias("volumen_total"),
            pl.col(value_col).sum().alias("valor_total"),
        ])
        .rename({hs_col: "hs_code", aduana_col: "aduana"})
        .with_columns(
            (pl.col("valor_total") / pl.col("volumen_total"))
            .round(4)
            .alias("precio_promedio")
        )
        .sort(["hs_code", "volumen_total"], descending=[False, True])
    )


def compute_price_spread(
    df: pl.DataFrame,
    hs_col: str = _HS_COL,
    actor_col: str = _ACTOR_COL,
    value_col: str = _VALUE_COL,
    quantity_col: str = _QUANTITY_COL,
) -> pl.DataFrame:
    """Min/max unit price and spread percentage by actor per hs_code.

    Unit price is computed per shipment row as value / quantity.
    Returns columns: hs_code, actor, precio_min, precio_max, spread_pct.
    Sorted by hs_code asc, spread_pct desc.
    """
    return (
        df.filter(
            pl.col(actor_col).is_not_null()
            & (pl.col(quantity_col) > 0)
        )
        .with_columns(
            (pl.col(value_col) / pl.col(quantity_col)).alias("_unit_price")
        )
        .group_by([hs_col, actor_col])
        .agg([
            pl.col("_unit_price").min().round(4).alias("precio_min"),
            pl.col("_unit_price").max().round(4).alias("precio_max"),
        ])
        .rename({hs_col: "hs_code", actor_col: "actor"})
        .with_columns(
            pl.when(pl.col("precio_min") > 0)
            .then(
                ((pl.col("precio_max") - pl.col("precio_min")) / pl.col("precio_min") * 100)
                .round(2)
            )
            .otherwise(None)
            .alias("spread_pct")
        )
        .sort(["hs_code", "spread_pct"], descending=[False, True])
    )


def compute_entities_over_time(
    df: pl.DataFrame,
    hs_col: str = _HS_COL,
    actor_col: str = _ACTOR_COL,
    day_col: str = _DAY_COL,
    month_col: str = _MONTH_COL,
    year_col: str = _YEAR_COL,
) -> pl.DataFrame:
    """Count of distinct active importers per period per hs_code.

    Returns columns: hs_code, periodo, n_actores.
    Sorted by hs_code asc, periodo asc.
    """
    return (
        _add_periodo(df, day_col, month_col, year_col)
        .filter(pl.col(actor_col).is_not_null())
        .group_by([hs_col, "periodo"])
        .agg(pl.col(actor_col).n_unique().alias("n_actores"))
        .rename({hs_col: "hs_code"})
        .sort(["hs_code", "periodo"])
    )


def compute_supplier_matrix(
    df: pl.DataFrame,
    supplier_col: str,
    hs_col: str = _HS_COL,
    actor_col: str = _ACTOR_COL,
    value_col: str = _VALUE_COL,
    quantity_col: str = _QUANTITY_COL,
) -> pl.DataFrame:
    """B2B supplier-importer relationship matrix per hs_code.

    Returns columns: hs_code, proveedor, actor, valor_fob_total, volumen_total, participacion_pct.
    Sorted by hs_code asc, valor_fob_total desc.
    """
    return (
        df.filter(
            pl.col(supplier_col).is_not_null()
            & pl.col(actor_col).is_not_null()
        )
        .group_by([hs_col, supplier_col, actor_col])
        .agg([
            pl.col(value_col).sum().alias("valor_fob_total"),
            pl.col(quantity_col).sum().alias("volumen_total"),
        ])
        .rename({hs_col: "hs_code", supplier_col: "proveedor", actor_col: "actor"})
        .with_columns(
            (
                pl.col("valor_fob_total")
                / pl.col("valor_fob_total").sum().over("hs_code")
                * 100
            ).round(2).alias("participacion_pct")
        )
        .sort(["hs_code", "valor_fob_total"], descending=[False, True])
    )


def run_aggregations(
    df: pl.DataFrame,
    db_path,
    hs_col: str = _HS_COL,
    actor_col: str = _ACTOR_COL,
    value_col: str = _VALUE_COL,
    quantity_col: str = _QUANTITY_COL,
    aduana_col: str = _ADUANA_COL,
    country_col: str = _COUNTRY_COL,
    day_col: str = _DAY_COL,
    month_col: str = _MONTH_COL,
    year_col: str = _YEAR_COL,
) -> None:
    """Compute all aggregation tables and save them to DuckDB.

    Core tables: market_share, price_by_country, price_by_route,
    price_spread, entities_over_time.
    Supplier tables (one per available column): supplier_proveedor,
    supplier_exportador, supplier_empresa_exportadora, supplier_embarcador,
    supplier_probable_embarcador.
    """
    from src.database import save_results

    tables = {
        "market_share": compute_market_share(df, hs_col, actor_col, quantity_col, value_col),
        "price_by_country": compute_price_by_country(df, hs_col, country_col, value_col, quantity_col),
        "price_by_route": compute_price_by_route(df, hs_col, aduana_col, value_col, quantity_col),
        "price_spread": compute_price_spread(df, hs_col, actor_col, value_col, quantity_col),
        "entities_over_time": compute_entities_over_time(df, hs_col, actor_col, day_col, month_col, year_col),
    }

    for table_name, table_df in tables.items():
        save_results(table_df, db_path, table=table_name, if_exists="replace")

    for supplier_col, table_name in _SUPPLIER_COLS.items():
        if supplier_col in df.columns:
            supplier_df = compute_supplier_matrix(df, supplier_col, hs_col, actor_col, value_col, quantity_col)
            save_results(supplier_df, db_path, table=table_name, if_exists="replace")
