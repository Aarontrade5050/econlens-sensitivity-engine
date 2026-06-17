# pipeline orchestration for running sensitivity analysis
import polars as pl

from src.arquetipos import ARCHETYPE_THRESHOLDS, get_archetype
from src.metrics import (
    build_hs_monthly_base,
    add_monthly_variation,
    add_rolling_price_volatility,
    add_simple_elasticity,
    add_shock_flag,
    add_ise_score,
)
from src.validation import validate_dataframe
from src.database import save_results


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
    required_cols = [hs_col, unit_col, value_col, quantity_col, day_col, month_col, year_col]
    if actor_col:
        required_cols.append(actor_col)
    validate_dataframe(df, required_cols, hs_code=hs_code, hs_col=hs_col)

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

    archetype = get_archetype(hs_code)
    thresholds = ARCHETYPE_THRESHOLDS[archetype]
    result = add_shock_flag(
        result,
        volume_threshold=thresholds["volume"],
        price_threshold=thresholds["price"],
    )
    result = add_ise_score(result)
    result = result.with_columns(pl.lit(archetype).alias("arquetipo_economico"))
    return result


def run_pipeline_multi(
    df: pl.DataFrame,
    hs_codes: list[str] | None = None,
    hs_col: str = "hs_code",
    unit_col: str = "unidad_medida",
    value_col: str = "valor",
    quantity_col: str = "cantidad",
    day_col: str = "DIA",
    month_col: str = "MES",
    year_col: str = "AÑO",
    actor_col: str | None = None,
    volatility_window: int = 6,
    db_path=None,
    if_exists: str = "replace",
) -> pl.DataFrame:
    if hs_codes is None:
        hs_codes = df[hs_col].unique().to_list()

    results = []
    for hs_code in hs_codes:
        try:
            result = run_pipeline(
                df, hs_code,
                hs_col=hs_col,
                unit_col=unit_col,
                value_col=value_col,
                quantity_col=quantity_col,
                day_col=day_col,
                month_col=month_col,
                year_col=year_col,
                actor_col=actor_col,
                volatility_window=volatility_window,
            )
            results.append(result)
        except ValueError:
            continue

    combined = pl.concat(results)

    if db_path is not None:
        save_results(combined, db_path, if_exists=if_exists)

    return combined
