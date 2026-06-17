# Economic archetype classifier for HS tariff codes.
# Archetypes drive dynamic shock thresholds in the ISE pipeline.
import polars as pl

_COMMODITY_CHAPTERS: frozenset[str] = frozenset({"10", "11", "25", "26", "27"})
_BIEN_DURADERO_CHAPTERS: frozenset[str] = frozenset({"84", "85", "87"})
_PERECEDERO_CHAPTERS: frozenset[str] = frozenset({"02", "04", "07", "08"})

# Shock thresholds per archetype: (volume_pct, price_pct).
# BIEN_DURADERO uses high volume tolerance because durable goods arrive in batches.
# PERECEDERO uses MoM with tighter thresholds (YoY intended when multi-year data
# is available).
ARCHETYPE_THRESHOLDS: dict[str, dict[str, float]] = {
    "COMMODITY":     {"volume": 15.0, "price": 5.0},
    "BIEN_DURADERO": {"volume": 80.0, "price": 15.0},
    "PERECEDERO":    {"volume": 25.0, "price": 10.0},
    "ESTANDAR":      {"volume": 20.0, "price": 10.0},
}


def clasificar_arquetipo(
    df: pl.DataFrame,
    hs_col: str = "hs_code",
) -> pl.DataFrame:
    """Add 'arquetipo_economico' column based on the first two digits (chapter) of
    the HS tariff code.

    Archetypes:
        COMMODITY     — chapters 10, 11, 25, 26, 27 (grains, fuels, minerals)
        BIEN_DURADERO — chapters 84, 85, 87 (machinery, electronics, vehicles)
        PERECEDERO    — chapters 02, 04, 07, 08 (meat, dairy, vegetables, fruit)
        ESTANDAR      — any other chapter (default)

    Args:
        df: DataFrame containing the HS code column.
        hs_col: Name of the HS code column (must be String dtype).

    Returns:
        df with an additional 'arquetipo_economico' column (String).
    """
    capitulo = pl.col(hs_col).str.slice(0, 2)
    return df.with_columns(
        pl.when(capitulo.is_in(list(_COMMODITY_CHAPTERS)))
        .then(pl.lit("COMMODITY"))
        .when(capitulo.is_in(list(_BIEN_DURADERO_CHAPTERS)))
        .then(pl.lit("BIEN_DURADERO"))
        .when(capitulo.is_in(list(_PERECEDERO_CHAPTERS)))
        .then(pl.lit("PERECEDERO"))
        .otherwise(pl.lit("ESTANDAR"))
        .alias("arquetipo_economico")
    )


def get_archetype(hs_code: str) -> str:
    """Return the archetype name for a single HS code string.

    Used by the pipeline to look up thresholds per product.
    """
    capitulo = hs_code[:2]
    if capitulo in _COMMODITY_CHAPTERS:
        return "COMMODITY"
    if capitulo in _BIEN_DURADERO_CHAPTERS:
        return "BIEN_DURADERO"
    if capitulo in _PERECEDERO_CHAPTERS:
        return "PERECEDERO"
    return "ESTANDAR"
