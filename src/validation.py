# validation routines for input data
import polars as pl


def validate_dataframe(
    df: pl.DataFrame,
    required_cols: list[str],
    hs_code: str,
    hs_col: str,
) -> None:
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Columnas faltantes: {missing}")

    numeric_cols = [col for col in required_cols if df[col].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)]
    for col in numeric_cols:
        if df[col].is_null().all():
            raise ValueError(f"La columna '{col}' está completamente vacía (todos null)")

    if df.filter(pl.col(hs_col) == hs_code).is_empty():
        raise ValueError(f"hs_code '{hs_code}' no encontrado en la columna '{hs_col}'")
