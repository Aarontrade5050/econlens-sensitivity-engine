import pytest
import polars as pl

from src.pipeline import run_pipeline


def _make_raw_df(actors=None):
    """8 meses de datos de importación para testing."""
    importers = actors or ["EMPRESA_A"]
    rows = []
    for imp in importers:
        for month in range(1, 9):
            rows.append({
                "DIA": 1,
                "MES": month,
                "AÑO": 2025,
                "hs_code": "2710200012",
                "unidad_medida": "L",
                "valor": float(100 * month),
                "cantidad": 50.0,
                "IMPORTADOR": imp,
            })
    return pl.DataFrame(rows)


EXPECTED_COLUMNS = {
    "periodo", "hs_code", "unidad_medida", "volumen", "precio",
    "var_pct_volumen_mensual", "var_pct_precio_mensual",
    "volatilidad_precio_6m", "elasticidad_simple",
    "shock_compuesto_flag", "ise_score", "ise_nivel",
}


# --- nivel mercado ---

def test_run_pipeline_returns_all_expected_columns():
    df = _make_raw_df()
    result = run_pipeline(df, hs_code="2710200012")
    assert EXPECTED_COLUMNS.issubset(set(result.columns))


def test_run_pipeline_returns_one_row_per_month():
    df = _make_raw_df()
    result = run_pipeline(df, hs_code="2710200012")
    assert result.shape[0] == 8


def test_run_pipeline_raises_when_hs_code_not_found():
    df = _make_raw_df()
    with pytest.raises(ValueError):
        run_pipeline(df, hs_code="9999999999")


# --- nivel actor ---

def test_run_pipeline_with_actor_col_includes_actor_column():
    df = _make_raw_df(actors=["PETROPERU", "REPSOL"])
    result = run_pipeline(df, hs_code="2710200012", actor_col="IMPORTADOR")
    assert "actor" in result.columns


def test_run_pipeline_with_actor_col_returns_one_row_per_actor_per_month():
    df = _make_raw_df(actors=["PETROPERU", "REPSOL"])
    result = run_pipeline(df, hs_code="2710200012", actor_col="IMPORTADOR")
    assert result.shape[0] == 16  # 2 actores x 8 meses


def test_run_pipeline_with_actor_col_keeps_actors_isolated():
    df = _make_raw_df(actors=["PETROPERU", "REPSOL"])
    result = run_pipeline(df, hs_code="2710200012", actor_col="IMPORTADOR")

    result_sorted = result.sort(["actor", "periodo"])
    petroperu_first = result_sorted.filter(pl.col("actor") == "PETROPERU").head(1)
    repsol_first = result_sorted.filter(pl.col("actor") == "REPSOL").head(1)

    # El primer mes de cada actor no tiene mes anterior → variación debe ser None
    assert petroperu_first["var_pct_volumen_mensual"][0] is None
    assert repsol_first["var_pct_volumen_mensual"][0] is None
