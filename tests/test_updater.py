import json
import pytest
import polars as pl
from pathlib import Path
from datetime import date

from src.updater import load_manifest, save_manifest, find_new_files, run_pipeline_auto


def _make_raw_parquet(directory: Path, filename: str, months: list[int]) -> Path:
    """Crea un parquet de datos crudos para testing."""
    rows = [
        {
            "DIA": 1, "MES": month, "AÑO": 2025,
            "hs_code": "2710200012",
            "unidad_medida": "L",
            "valor": float(100 * month),
            "cantidad": 50.0,
            "IMPORTADOR": "EMPRESA_A",
        }
        for month in months
    ]
    path = directory / filename
    pl.DataFrame(rows).write_parquet(path)
    return path


# --- manifest ---

def test_load_manifest_returns_empty_set_when_file_missing(tmp_path):
    result = load_manifest(tmp_path / "manifest.json")
    assert result == set()


def test_load_manifest_returns_saved_files(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(["archivo_a.xlsx", "archivo_b.xlsx"]))
    result = load_manifest(manifest)
    assert result == {"archivo_a.xlsx", "archivo_b.xlsx"}


def test_save_manifest_creates_file(tmp_path):
    manifest = tmp_path / "manifest.json"
    save_manifest(manifest, {"archivo_a.xlsx", "archivo_b.xlsx"})
    content = json.loads(manifest.read_text())
    assert set(content) == {"archivo_a.xlsx", "archivo_b.xlsx"}


def test_save_manifest_overwrites_existing(tmp_path):
    manifest = tmp_path / "manifest.json"
    save_manifest(manifest, {"viejo.xlsx"})
    save_manifest(manifest, {"nuevo.xlsx"})
    content = json.loads(manifest.read_text())
    assert set(content) == {"nuevo.xlsx"}


# --- find_new_files ---

def test_find_new_files_returns_only_unprocessed(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "archivo_a.parquet").touch()
    (raw_dir / "archivo_b.parquet").touch()
    manifest = {"archivo_a.parquet"}
    result = find_new_files(raw_dir, manifest)
    assert len(result) == 1
    assert result[0].name == "archivo_b.parquet"


def test_find_new_files_returns_empty_when_all_processed(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "archivo_a.parquet").touch()
    manifest = {"archivo_a.parquet"}
    result = find_new_files(raw_dir, manifest)
    assert result == []


# --- run_pipeline_auto ---

def test_run_pipeline_auto_processes_new_files_and_updates_db(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _make_raw_parquet(raw_dir, "enero.parquet", months=list(range(1, 9)))

    db_path = tmp_path / "test.duckdb"
    manifest_path = tmp_path / "manifest.json"

    count = run_pipeline_auto(
        raw_dir=raw_dir,
        db_path=db_path,
        manifest_path=manifest_path,
        file_reader=pl.read_parquet,
    )

    assert count == 1
    assert db_path.exists()


def test_run_pipeline_auto_updates_manifest_after_processing(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _make_raw_parquet(raw_dir, "enero.parquet", months=list(range(1, 9)))

    manifest_path = tmp_path / "manifest.json"

    run_pipeline_auto(
        raw_dir=raw_dir,
        db_path=tmp_path / "test.duckdb",
        manifest_path=manifest_path,
        file_reader=pl.read_parquet,
    )

    manifest = load_manifest(manifest_path)
    assert "enero.parquet" in manifest


def test_run_pipeline_auto_skips_already_processed_files(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _make_raw_parquet(raw_dir, "enero.parquet", months=list(range(1, 9)))

    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"enero.parquet"})

    count = run_pipeline_auto(
        raw_dir=raw_dir,
        db_path=tmp_path / "test.duckdb",
        manifest_path=manifest_path,
        file_reader=pl.read_parquet,
    )

    assert count == 0


def test_run_pipeline_auto_returns_count_of_processed_files(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _make_raw_parquet(raw_dir, "enero.parquet", months=list(range(1, 5)))
    _make_raw_parquet(raw_dir, "febrero.parquet", months=list(range(5, 9)))

    count = run_pipeline_auto(
        raw_dir=raw_dir,
        db_path=tmp_path / "test.duckdb",
        manifest_path=tmp_path / "manifest.json",
        file_reader=pl.read_parquet,
    )

    assert count == 2
