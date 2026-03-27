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
    """Filtra el DataFrame por un código HS, construye una fecha a partir de las
    columnas de día/mes/año, agrega los datos a nivel mensual por código HS y
    unidad de medida, y calcula el precio unitario promedio (valor_total /
    volumen_total). Excluye filas sin unidad de medida.

    Args:
        df: DataFrame de origen con los datos de importación/exportación.
        hs_code: Código HS por el que se filtrará.
        hs_col: Nombre de la columna de código HS.
        unit_col: Nombre de la columna de unidad de medida.
        value_col: Nombre de la columna de valor monetario.
        quantity_col: Nombre de la columna de cantidad/volumen.
        day_col: Nombre de la columna de día.
        month_col: Nombre de la columna de mes.
        year_col: Nombre de la columna de año.

    Returns:
        DataFrame con columnas: periodo, hs_code, unidad_medida, volumen, precio.
        Ordenado por periodo y unidad_medida.
    """
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

def add_monthly_variation(df: pl.DataFrame) -> pl.DataFrame:
    """Agrega columnas de variación porcentual mensual de volumen y precio a un
    DataFrame previamente construido con `build_hs_monthly_base`. El cálculo se
    realiza por grupo (hs_code, unidad_medida) usando ventanas sobre la serie
    ordenada por periodo.

    Args:
        df: DataFrame con columnas periodo, hs_code, unidad_medida, volumen y
            precio. Normalmente el resultado de `build_hs_monthly_base`.

    Returns:
        El mismo DataFrame con dos columnas adicionales:
        - var_pct_volumen_mensual: variación porcentual del volumen respecto al
          mes anterior dentro del mismo grupo.
        - var_pct_precio_mensual: variación porcentual del precio respecto al
          mes anterior dentro del mismo grupo.

    Raises:
        ValueError: Si el DataFrame de entrada está vacío.
    """
    if df.is_empty():
        raise ValueError("Input DataFrame is empty.")

    return (
        df.sort(["hs_code", "unidad_medida", "periodo"])
        .with_columns(
            [
                (
                    (pl.col("volumen") / pl.col("volumen").shift(1) - 1) * 100
                )
                .over(["hs_code", "unidad_medida"])
                .alias("var_pct_volumen_mensual"),
                (
                    (pl.col("precio") / pl.col("precio").shift(1) - 1) * 100
                )
                .over(["hs_code", "unidad_medida"])
                .alias("var_pct_precio_mensual"),
            ]
        )
    )


def add_rolling_price_volatility(
    df: pl.DataFrame,
    window: int = 6,
) -> pl.DataFrame:
    if df.is_empty():
        raise ValueError("Input DataFrame is empty.")

    if window < 2:
        raise ValueError("Window must be at least 2.")

    return (
        df.sort(["hs_code", "unidad_medida", "periodo"])
        .with_columns(
            pl.col("var_pct_precio_mensual")
            .rolling_std(window_size=window, min_samples=window)
            .over(["hs_code", "unidad_medida"])
            .alias(f"volatilidad_precio_{window}m")
        )
    )

def add_simple_elasticity(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        raise ValueError("Input DataFrame is empty.")

    return (
        df.with_columns(
            pl.when(
                (pl.col('var_pct_precio_mensual') != 0) &
                (pl.col('var_pct_volumen_mensual').is_not_null()) &
                (pl.col('var_pct_precio_mensual').is_not_null())
            )
            .then(
                pl.col('var_pct_volumen_mensual') / pl.col('var_pct_precio_mensual')
            )
            .otherwise(None)
            .alias('elasticidad_simple')
        )
    )

def add_shock_flag(
    df: pl.DataFrame,
    volume_threshold: float = 20.0,
    price_threshold: float = 5.0,
    volatility_threshold: float = 4.0,
    elasticity_threshold: float = 2.0,
) -> pl.DataFrame:
    if df.is_empty():
        raise ValueError("Input DataFrame is empty.")

    required_cols = [
        "var_pct_volumen_mensual",
        "var_pct_precio_mensual",
        "volatilidad_precio_6m",
        "elasticidad_simple",
    ]

    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Missing required columns for shock detection: {missing_cols}"
        )

    volume_shock = pl.col("var_pct_volumen_mensual").abs() >= volume_threshold
    price_shock = pl.col("var_pct_precio_mensual").abs() >= price_threshold
    volatility_shock = (
        pl.col("volatilidad_precio_6m").is_not_null()
        & (pl.col("volatilidad_precio_6m").cast(pl.Float64) >= volatility_threshold)
    )
    elasticity_shock = (
        pl.col("elasticidad_simple").is_not_null()
        & (pl.col("elasticidad_simple").cast(pl.Float64).abs() >= elasticity_threshold)
    )

    shock_rule = (
        (volume_shock & price_shock)
        | (volume_shock & elasticity_shock)
        | (price_shock & volatility_shock)
    )

    return df.with_columns(
        pl.when(shock_rule)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("shock_compuesto_flag")
    )


def add_ise_score(df: pl.DataFrame) -> pl.DataFrame:
    """
    Add a normalized economic sensitivity score (ISE) in a 0-100 scale.

    The score combines:
    - absolute monthly volume variation
    - absolute monthly price variation
    - rolling price volatility
    - absolute simple elasticity

    A log1p transformation is applied to reduce the impact of extreme values.
    The final score is capped and normalized to a 0-100 range.

    Parameters
    ----------
    df : pl.DataFrame
        Input dataframe with required metric columns.

    Returns
    -------
    pl.DataFrame
        Dataframe with:
        - ise_score
        - ise_nivel
    """
    if df.is_empty():
        raise ValueError("Input DataFrame is empty.")

    required_cols = [
        "var_pct_volumen_mensual",
        "var_pct_precio_mensual",
        "volatilidad_precio_6m",
        "elasticidad_simple",
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Missing required columns for ISE score calculation: {missing_cols}"
        )

    ise_raw = (
        pl.col("var_pct_volumen_mensual")
        .cast(pl.Float64)
        .abs()
        .fill_null(0.0)
        .log1p()
        + pl.col("var_pct_precio_mensual")
        .cast(pl.Float64)
        .abs()
        .fill_null(0.0)
        .log1p()
        + pl.col("volatilidad_precio_6m")
        .cast(pl.Float64)
        .fill_null(0.0)
        .log1p()
        + pl.col("elasticidad_simple")
        .cast(pl.Float64)
        .abs()
        .fill_null(0.0)
        .log1p()
    )

    max_expected = 10.0

    ise_score_expr = (
        pl.when(ise_raw > max_expected)
        .then(pl.lit(max_expected))
        .otherwise(ise_raw)
        / max_expected
        * 100
    )

    return (
        df.with_columns(ise_score_expr.alias("ise_score"))
        .with_columns(
            pl.when(pl.col("ise_score") < 33)
            .then(pl.lit("Bajo"))
            .when(pl.col("ise_score") < 66)
            .then(pl.lit("Medio"))
            .otherwise(pl.lit("Alto"))
            .alias("ise_nivel")
        )
    )