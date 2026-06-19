"""Tests para src/ingest.py — flujo de ingesta desde data/inbox/."""

import polars as pl
import pytest
import yaml
from pathlib import Path

from src.ingest import (
    apply_schema,
    ingest_inbox,
    load_config,
    resolve_columns,
    validate_required,
)


MINIMAL_SCHEMA = {
    "schema": {
        "required": [
            {"name": "PARTIDA ARANCELARIA", "aliases": ["HS_CODE", "PARTIDA"], "dtype": "string"},
            {"name": "US$ FOB", "aliases": ["FOB_USD", "VALOR_FOB"], "dtype": "float"},
            {"name": "MES", "aliases": ["MONTH"], "dtype": "int"},
        ],
        "optional": [
            {"name": "ADUANA", "aliases": ["CUSTOMS"], "dtype": "string"},
        ],
    }
}


def _write_config(tmp_path: Path, schema: dict) -> Path:
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.dump(schema, allow_unicode=True), encoding="utf-8")
    return config_path


def _new_parquet(tmp_path: Path, name: str = "nueva.parquet") -> Path:
    path = tmp_path / name
    pl.DataFrame({
        "PARTIDA ARANCELARIA": ["8517120000"],
        "US$ FOB": [500.0],
        "MES": [3],
    }).write_parquet(path)
    return path


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

def test_load_config_returns_schema_dict(tmp_path):
    config_path = _write_config(tmp_path, MINIMAL_SCHEMA)
    result = load_config(config_path)
    assert "schema" in result
    assert "required" in result["schema"]
    assert "optional" in result["schema"]


# ---------------------------------------------------------------------------
# resolve_columns
# ---------------------------------------------------------------------------

def test_resolve_columns_finds_exact_name():
    df = pl.DataFrame({"PARTIDA ARANCELARIA": ["8517"], "US$ FOB": [100.0], "MES": [1]})
    mapping = resolve_columns(df, MINIMAL_SCHEMA)
    assert mapping.get("PARTIDA ARANCELARIA") == "PARTIDA ARANCELARIA"


def test_resolve_columns_finds_by_alias():
    df = pl.DataFrame({"HS_CODE": ["8517"], "FOB_USD": [100.0], "MES": [1]})
    mapping = resolve_columns(df, MINIMAL_SCHEMA)
    assert mapping.get("HS_CODE") == "PARTIDA ARANCELARIA"
    assert mapping.get("FOB_USD") == "US$ FOB"


def test_resolve_columns_ignores_unknown_columns():
    df = pl.DataFrame({"PARTIDA ARANCELARIA": ["8517"], "COLUMNA_EXTRA": ["x"]})
    mapping = resolve_columns(df, MINIMAL_SCHEMA)
    assert "COLUMNA_EXTRA" not in mapping.values()


# ---------------------------------------------------------------------------
# validate_required
# ---------------------------------------------------------------------------

def test_validate_required_passes_when_all_present():
    df = pl.DataFrame({
        "PARTIDA ARANCELARIA": ["8517"],
        "US$ FOB": [100.0],
        "MES": [1],
    })
    validate_required(df, MINIMAL_SCHEMA)  # no debe lanzar excepción


def test_validate_required_raises_when_missing():
    df = pl.DataFrame({"PARTIDA ARANCELARIA": ["8517"]})
    with pytest.raises(ValueError, match="requeridas"):
        validate_required(df, MINIMAL_SCHEMA)


# ---------------------------------------------------------------------------
# apply_schema
# ---------------------------------------------------------------------------

def test_apply_schema_renames_alias_to_canonical():
    df = pl.DataFrame({"HS_CODE": ["8517"], "FOB_USD": [100.0], "MES": [1]})
    result = apply_schema(df, MINIMAL_SCHEMA)
    assert "PARTIDA ARANCELARIA" in result.columns
    assert "US$ FOB" in result.columns
    assert "HS_CODE" not in result.columns


def test_apply_schema_casts_dtypes():
    df = pl.DataFrame({
        "PARTIDA ARANCELARIA": ["8517"],
        "US$ FOB": ["100.5"],
        "MES": ["3"],
    })
    result = apply_schema(df, MINIMAL_SCHEMA)
    assert result["US$ FOB"].dtype == pl.Float64
    assert result["MES"].dtype == pl.Int64


# ---------------------------------------------------------------------------
# ingest_inbox
# ---------------------------------------------------------------------------

def test_ingest_inbox_appends_rows_to_existing_parquet(tmp_path):
    config_path = _write_config(tmp_path, MINIMAL_SCHEMA)
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    interim_path = tmp_path / "df_all.parquet"

    pl.DataFrame({
        "PARTIDA ARANCELARIA": ["1001000000"],
        "US$ FOB": [50.0],
        "MES": [1],
    }).write_parquet(interim_path)

    _new_parquet(inbox_dir)

    rows_added = ingest_inbox(inbox_dir, interim_path, config_path)
    result = pl.read_parquet(interim_path)

    assert rows_added == 1
    assert result.shape[0] == 2


def test_ingest_inbox_creates_parquet_when_not_exists(tmp_path):
    config_path = _write_config(tmp_path, MINIMAL_SCHEMA)
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    interim_path = tmp_path / "df_all.parquet"

    _new_parquet(inbox_dir)
    ingest_inbox(inbox_dir, interim_path, config_path)

    assert interim_path.exists()


def test_ingest_inbox_moves_processed_file_to_done(tmp_path):
    config_path = _write_config(tmp_path, MINIMAL_SCHEMA)
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    interim_path = tmp_path / "df_all.parquet"

    new_file = _new_parquet(inbox_dir)
    ingest_inbox(inbox_dir, interim_path, config_path)

    assert not new_file.exists()
    assert (inbox_dir / "done" / "nueva.parquet").exists()


def test_ingest_inbox_returns_zero_when_inbox_empty(tmp_path):
    config_path = _write_config(tmp_path, MINIMAL_SCHEMA)
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    interim_path = tmp_path / "df_all.parquet"

    rows_added = ingest_inbox(inbox_dir, interim_path, config_path)
    assert rows_added == 0
