# metric calculations (volatility, elasticity, etc.)
import polars as pl


def build_hs_monthly_base(
    df: pl.DataFrame,
    hs_code: str,
    hs_col: str = "hs_code",
    unit_col: str = "unidad_medida",
    value_col: str = "valor",
    quantity_col: str = "cantidad",
    day_col: str = "DIA",
    month_col: str = "MES",
    year_col: str = "AÑO",
) -> pl.DataFrame:
    return (
        df
        .filter(pl.col(hs_col) == hs_code)
        .filter(pl.col(unit_col).is_not_null())
        .with_columns([
            pl.col(day_col).cast(pl.Int32),
            pl.col(month_col).cast(pl.Int32),
            pl.col(year_col).cast(pl.Int32),
        ])
        .with_columns(
            pl.date(
                pl.col(year_col),
                pl.col(month_col),
                pl.col(day_col),
            ).alias("fecha")
        )
        .with_columns(
            pl.col("fecha").dt.truncate("1mo").alias("periodo")
        )
        .group_by(["periodo", hs_col, unit_col])
        .agg([
            pl.col(value_col).sum().alias("valor_total"),
            pl.col(quantity_col).sum().alias("volumen_total"),
        ])
        .with_columns(
            pl.when(pl.col("volumen_total") > 0)
            .then(pl.col("valor_total") / pl.col("volumen_total"))
            .otherwise(None)
            .alias("precio")
        )
        .select([
            "periodo",
            pl.col(hs_col).alias("hs_code"),
            pl.col(unit_col).alias("unidad_medida"),
            pl.col("volumen_total").alias("volumen"),
            "precio",
        ])
        .sort(["periodo", "unidad_medida"])
    )