import pytest
import polars as pl
from datetime import date

from src.database import save_results, load_results, load_dim_partida


def _make_results_df():
    return pl.DataFrame({
        "periodo": [
            date(2025, 1, 1), date(2025, 2, 1),
            date(2025, 1, 1), date(2025, 2, 1),
        ],
        "hs_code": ["2710200012", "2710200012", "2709000000", "2709000000"],
        "unidad_medida": ["M3", "M3", "M3", "M3"],
        "actor": ["VALERO", "VALERO", "MOBIL", "MOBIL"],
        "volumen": [100.0, 120.0, 80.0, 90.0],
        "precio": [600.0, 610.0, 500.0, 510.0],
        "var_pct_volumen_mensual": [None, 20.0, None, 12.5],
        "var_pct_precio_mensual": [None, 1.67, None, 2.0],
        "volatilidad_precio_6m": [None, None, None, None],
        "elasticidad_simple": [None, 11.98, None, 6.25],
        "shock_compuesto_flag": [0, 0, 0, 0],
        "ise_score": [0.0, 25.0, 0.0, 20.0],
        "ise_nivel": ["Bajo", "Bajo", "Bajo", "Bajo"],
    })


# --- save / load básico ---

def test_save_and_load_returns_same_data(tmp_path):
    db = tmp_path / "test.duckdb"
    df = _make_results_df()
    save_results(df, db)
    result = load_results(db)
    assert result.shape == df.shape


def test_save_with_replace_overwrites_table(tmp_path):
    db = tmp_path / "test.duckdb"
    df = _make_results_df()
    save_results(df, db, if_exists="replace")
    save_results(df, db, if_exists="replace")
    result = load_results(db)
    assert result.shape[0] == df.shape[0]


def test_save_with_append_adds_rows(tmp_path):
    db = tmp_path / "test.duckdb"
    df = _make_results_df()
    save_results(df, db, if_exists="replace")
    save_results(df, db, if_exists="append")
    result = load_results(db)
    assert result.shape[0] == df.shape[0] * 2


# --- filtros ---

def test_load_without_filters_returns_all(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_results_df(), db)
    result = load_results(db)
    assert result.shape[0] == 4


def test_load_with_hs_code_filter(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_results_df(), db)
    result = load_results(db, hs_code="2710200012")
    assert result.shape[0] == 2
    assert result["hs_code"].unique().to_list() == ["2710200012"]


def test_load_with_actor_filter(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_results_df(), db)
    result = load_results(db, actor="VALERO")
    assert result.shape[0] == 2
    assert result["actor"].unique().to_list() == ["VALERO"]


def test_load_with_from_period_filter(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_results_df(), db)
    result = load_results(db, from_period="2025-02-01")
    assert result.shape[0] == 2
    assert all(p >= date(2025, 2, 1) for p in result["periodo"].to_list())


def test_load_with_to_period_filter(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_results_df(), db)
    result = load_results(db, to_period="2025-01-01")
    assert result.shape[0] == 2
    assert all(p <= date(2025, 1, 1) for p in result["periodo"].to_list())


def test_load_with_date_range_filter(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_results_df(), db)
    result = load_results(db, from_period="2025-01-01", to_period="2025-01-01")
    assert result.shape[0] == 2
    assert all(p == date(2025, 1, 1) for p in result["periodo"].to_list())


# --- dim_partida ---

def _make_dim_df() -> pl.DataFrame:
    return pl.DataFrame({
        "seccion": ["I", "I", "II"],
        "desc_seccion": ["Animales vivos", "Animales vivos", "Productos del reino vegetal"],
        "capitulo": ["01", "01", "06"],
        "desc_capitulo": ["Animales vivos", "Animales vivos", "Plantas"],
        "partida_4d": ["0101", "0101", "0601"],
        "desc_partida": ["Caballos vivos", "Caballos vivos", "Bulbos"],
        "subpartida_6d": ["010110", "010121", "060110"],
        "desc_subpartida": ["De raza pura", "Caballos reproductores", "Bulbos"],
    })


def test_load_dim_partida_returns_empty_when_missing(tmp_path):
    db = tmp_path / "empty.duckdb"
    result = load_dim_partida(db)
    assert isinstance(result, pl.DataFrame)
    assert result.is_empty()


def test_load_dim_partida_returns_full_table(tmp_path):
    db = tmp_path / "test.duckdb"
    dim = _make_dim_df()
    save_results(dim, db, table="dim_partida")
    result = load_dim_partida(db)
    assert result.shape[0] == 3


def test_load_dim_partida_has_expected_columns(tmp_path):
    db = tmp_path / "test.duckdb"
    save_results(_make_dim_df(), db, table="dim_partida")
    result = load_dim_partida(db)
    expected = {
        "seccion", "desc_seccion", "capitulo", "desc_capitulo",
        "partida_4d", "desc_partida", "subpartida_6d", "desc_subpartida",
    }
    assert expected.issubset(set(result.columns))
