# pipeline orchestration for running sensitivity analysis
import polars as pl

from src.metrics import (
    build_hs_monthly_base,
    add_monthly_variation,
    add_rolling_price_volatility,
    add_simple_elasticity,
    add_shock_flag,
    add_ise_score,
)


def run_pipeline(
    df: pl.DataFrame,
    hs_code: str,
    hs_col: str = "hs_code",
    unit_col: str = "unidad_medida",
    value_col: str = "valor",
    quantity_col: str = "cantidad",
    day_col: str = "DIA",
    month_col: str = "MES",
    year_col: str = "AÑO",
    actor_col: str | None = None,
    volatility_window: int = 6,
) -> pl.DataFrame:
    group_keys = (["actor"] if actor_col else []) + ["hs_code", "unidad_medida"]

    result = build_hs_monthly_base(
        df, hs_code,
        hs_col=hs_col,
        unit_col=unit_col,
        value_col=value_col,
        quantity_col=quantity_col,
        day_col=day_col,
        month_col=month_col,
        year_col=year_col,
        actor_col=actor_col,
    )
    result = add_monthly_variation(result, group_keys=group_keys)
    result = add_rolling_price_volatility(result, window=volatility_window, group_keys=group_keys)
    result = add_simple_elasticity(result)
    result = add_shock_flag(result)
    result = add_ise_score(result)
    return result
