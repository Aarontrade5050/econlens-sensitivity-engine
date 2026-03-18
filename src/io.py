"""I/O utilities for reading and writing datasets.

This module focuses on efficient conversion of Excel data into Parquet using Polars.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import polars as pl


def _xlsx_files_in_directory(path: Path) -> list[Path]:
    """List all Excel files in a directory."""

    return sorted(path.glob("*.xls*"))


def convert_raw_xlsx_to_parquet(
    raw_dir: Path | str,
    interim_dir: Path | str,
    *,
    output_filename: str = "all.parquet",
    overwrite: bool = False,
    write_individual_parquet: bool = True,
) -> Path:
    """Convert all XLSX/XLS files in `raw_dir` to Parquet and concatenate.

    This function is intended to be efficient for large datasets by leveraging
    Polars lazy execution (`pl.scan_excel` / `pl.scan_parquet`) and by writing
    intermediate results to disk.

    Args:
        raw_dir: Directory containing raw Excel files.
        interim_dir: Directory where Parquet files will be written.
        output_filename: Filename to use for the combined Parquet output.
        overwrite: If True, overwrite any existing combined output file.
        write_individual_parquet: If True, write each input Excel file as an
            individual Parquet file (useful for caching / incremental workflows).

    Returns:
        Path to the combined Parquet file.
    """

    raw_dir = Path(raw_dir)
    interim_dir = Path(interim_dir)
    interim_dir.mkdir(parents=True, exist_ok=True)

    raw_files = _xlsx_files_in_directory(raw_dir)
    if not raw_files:
        raise FileNotFoundError(f"No Excel files found in {raw_dir!s}")

    parquet_files: list[Path] = []
    for raw_file in raw_files:
        parquet_file = interim_dir / f"{raw_file.stem}.parquet"
        parquet_files.append(parquet_file)

        if write_individual_parquet and (not parquet_file.exists() or overwrite):
            # Read lazily and write out as parquet to preserve memory.
            # Polars automatically infers schema and types.
            df = pl.read_excel(raw_file)
            df.write_parquet(parquet_file)

    combined_path = interim_dir / output_filename
    if combined_path.exists() and not overwrite:
        return combined_path

    # Concatenate all intermediate parquet files using lazy execution.
    lazy_frames: list[pl.LazyFrame] = [pl.scan_parquet(p) for p in parquet_files]
    combined = pl.concat(lazy_frames, rechunk=True).collect()
    combined.write_parquet(combined_path)

    return combined_path
