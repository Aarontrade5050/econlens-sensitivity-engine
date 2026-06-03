# Light normalization layer for raw SUNAT data.
# Applied once before the ISE pipeline and aggregations.
import polars as pl


def _clean_name_expr(col: pl.Expr) -> pl.Expr:
    """Vectorized Polars expression to normalize a company name.

    Rules applied in order:
    1. Strip leading/trailing whitespace and outer quotes.
    2. Collapse multiple internal spaces to one.
    3. Take the part before the first '/' (removes truncated aliases like
       'CIA. MOLINERA DEL CENTRO S.A./CIA. MOLINERA DEL CENTRO S').
    4. Re-strip after the split.
    5. Fix encoding artifacts where SUNAT exported Ñ/Ó as '?'.
    6. Fix stray space insertions (e.g. 'SUCURSA L' → 'SUCURSAL').
    """
    return (
        col
        .str.strip_chars()
        .str.strip_chars("\"'")
        .str.replace_all(r"\s{2,}", " ", literal=False)
        .str.split("/").list.first()
        .str.strip_chars()
        .str.replace_all("COMPA?IA",  "COMPAÑÍA",  literal=True)
        .str.replace_all("COMPA??IA", "COMPAÑÍA",  literal=True)
        .str.replace_all("AN?NIMA",   "ANÓNIMA",   literal=True)
        .str.replace_all("VI?A",      "VIÑA",      literal=True)
        .str.replace_all("SUCURSA L ", "SUCURSAL ", literal=True)
    )


def _is_valid_name_expr(col: pl.Expr) -> pl.Expr:
    """True when a name is non-null and contains at least one letter."""
    return (
        col.is_not_null()
        & (col.str.len_chars() > 2)
        & col.str.contains(r"[A-Za-z]", literal=False)
    )


def clean_raw_df(
    df: pl.DataFrame,
    actor_col: str = "IMPORTADOR",
    unit_col: str = "UNIDAD DE MEDIDA",
) -> pl.DataFrame:
    """Normalize importer names and unit-of-measure values in the raw DataFrame.

    All transformations are vectorized Polars expressions — no Python-level loops.

    Actor cleaning:
    - Strip whitespace and outer quotes.
    - Collapse multiple internal spaces.
    - Take the canonical name before '/' (removes truncated duplicates).
    - Fix known encoding artifacts (Ñ→?, Ó→?, common in SUNAT exports).
    - Set garbage entries to null (e.g. '::::::').

    Unit cleaning:
    - 'U 3' → 'U'  (stray digit in unit code)
    - '2U'  → 'U'  (stray digit prefix)

    Returns:
        The input DataFrame with IMPORTADOR and UNIDAD DE MEDIDA cleaned in place.
    """
    _UNIT_FIXES = {"U 3": "U", "2U": "U"}

    return (
        df
        .with_columns(
            _clean_name_expr(pl.col(actor_col)).alias(actor_col)
        )
        .with_columns(
            pl.when(_is_valid_name_expr(pl.col(actor_col)))
            .then(pl.col(actor_col))
            .otherwise(None)
            .alias(actor_col)
        )
        .with_columns(
            pl.col(unit_col).replace(_UNIT_FIXES).alias(unit_col)
        )
    )
