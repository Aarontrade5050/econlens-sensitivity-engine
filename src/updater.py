# automated pipeline updater
import json
import polars as pl
from pathlib import Path

from src.pipeline import run_pipeline_multi
from src.database import save_results


def load_manifest(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    return set(json.loads(manifest_path.read_text()))


def save_manifest(manifest_path: Path, files: set[str]) -> None:
    manifest_path.write_text(json.dumps(list(files)))


def find_new_files(raw_dir: Path, manifest: set[str]) -> list[Path]:
    return [f for f in sorted(raw_dir.iterdir()) if f.name not in manifest]


def run_pipeline_auto(
    raw_dir: Path,
    db_path: Path,
    manifest_path: Path,
    file_reader=None,
    hs_col: str = "hs_code",
    unit_col: str = "unidad_medida",
    value_col: str = "valor",
    quantity_col: str = "cantidad",
    day_col: str = "DIA",
    month_col: str = "MES",
    year_col: str = "AÑO",
    actor_col: str | None = None,
) -> int:
    if file_reader is None:
        file_reader = _read_xlsx

    manifest = load_manifest(manifest_path)
    new_files = find_new_files(raw_dir, manifest)

    if not new_files:
        return 0

    frames = [file_reader(f) for f in new_files]
    df = pl.concat(frames, how="diagonal")

    result = run_pipeline_multi(
        df,
        hs_col=hs_col,
        unit_col=unit_col,
        value_col=value_col,
        quantity_col=quantity_col,
        day_col=day_col,
        month_col=month_col,
        year_col=year_col,
        actor_col=actor_col,
    )
    save_results(result, db_path, if_exists="append")

    save_manifest(manifest_path, manifest | {f.name for f in new_files})
    return len(new_files)


def _read_xlsx(path: Path) -> pl.DataFrame:
    import pandas as pd
    df_pd = pd.read_excel(path)
    return pl.from_pandas(df_pd)
