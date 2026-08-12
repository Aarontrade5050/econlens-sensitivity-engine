"""Ingesta de nuevos parquets desde data/inbox/ al dataset combinado interim.

Flujo:
    data/inbox/*.parquet
        → resolver columnas por nombre canónico o alias (config.yml)
        → renombrar y castear tipos
        → validar columnas requeridas
        → concat con data/interim/df_all.parquet
        → mover archivos procesados a data/inbox/done/
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import polars as pl
import yaml


_DTYPE_MAP: dict[str, type[pl.DataType]] = {
    "string": pl.String,
    "float": pl.Float64,
    "int": pl.Int64,
    "date": pl.Date,
}


def load_config(config_path: Path | str) -> dict[str, Any]:
    """Load and return the column schema from a YAML config file."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_columns(df: pl.DataFrame, schema: dict[str, Any]) -> dict[str, str]:
    """Return {source_column: canonical_name} for every column found in df.

    Matches by exact canonical name first, then by alias.
    Columns not defined in schema are not included.
    """
    df_cols = set(df.columns)
    all_fields: list[dict] = (
        schema.get("schema", {}).get("required", [])
        + schema.get("schema", {}).get("optional", [])
    )
    mapping: dict[str, str] = {}
    for field in all_fields:
        canonical: str = field["name"]
        candidates = [canonical] + field.get("aliases", [])
        for candidate in candidates:
            if candidate in df_cols:
                mapping[candidate] = canonical
                break
    return mapping


def validate_required(df: pl.DataFrame, schema: dict[str, Any]) -> None:
    """Raise ValueError listing any required canonical columns missing from df."""
    required = {f["name"] for f in schema.get("schema", {}).get("required", [])}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Columnas requeridas no encontradas en el dataset: {sorted(missing)}"
        )


def apply_schema(df: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    """Rename alias columns to canonical names and cast to expected dtypes."""
    mapping = resolve_columns(df, schema)

    rename_map = {src: tgt for src, tgt in mapping.items() if src != tgt}
    if rename_map:
        df = df.rename(rename_map)

    all_fields: list[dict] = (
        schema.get("schema", {}).get("required", [])
        + schema.get("schema", {}).get("optional", [])
    )
    casts = []
    for field in all_fields:
        canonical = field["name"]
        dtype = _DTYPE_MAP.get(field.get("dtype", "string"))
        if canonical in df.columns and dtype is not None:
            if df[canonical].dtype != dtype:
                casts.append(pl.col(canonical).cast(dtype, strict=False))

    if casts:
        df = df.with_columns(casts)

    return df


def ingest_inbox(
    inbox_dir: Path | str,
    interim_path: Path | str,
    config_path: Path | str,
) -> int:
    """Process all parquets in inbox_dir and merge into interim_path.

    Processed files are moved to inbox_dir/done/.

    Returns:
        Number of new rows added to the dataset.
    """
    inbox_dir = Path(inbox_dir)
    interim_path = Path(interim_path)
    done_dir = inbox_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)

    new_files = sorted(inbox_dir.glob("*.parquet"))
    if not new_files:
        return 0

    schema = load_config(config_path)

    frames: list[pl.DataFrame] = []
    for parquet_file in new_files:
        df = pl.read_parquet(parquet_file)
        df = apply_schema(df, schema)
        validate_required(df, schema)
        frames.append(df)

    new_data = pl.concat(frames, how="diagonal")
    rows_added = new_data.shape[0]

    if interim_path.exists():
        existing = pl.read_parquet(interim_path)
        # Align new_data dtypes to the existing parquet schema
        casts = []
        for col, dtype in existing.schema.items():
            if col in new_data.columns and new_data[col].dtype != dtype:
                casts.append(pl.col(col).cast(dtype, strict=False))
        if casts:
            new_data = new_data.with_columns(casts)
        combined = pl.concat([existing, new_data], how="diagonal")
    else:
        combined = new_data

    interim_path.parent.mkdir(parents=True, exist_ok=True)
    combined.write_parquet(interim_path)

    for parquet_file in new_files:
        shutil.move(str(parquet_file), done_dir / parquet_file.name)

    return rows_added
