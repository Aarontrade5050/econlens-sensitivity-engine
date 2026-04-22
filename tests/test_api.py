import pytest
import polars as pl
from datetime import date
from fastapi.testclient import TestClient

from src.database import save_results


def _make_test_df():
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


@pytest.fixture
def client(tmp_path):
    from src.api import app, get_db_path

    db = tmp_path / "test.duckdb"
    save_results(_make_test_df(), db)

    app.dependency_overrides[get_db_path] = lambda: str(db)
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- GET /results ---

def test_get_results_returns_200(client):
    response = client.get("/results")
    assert response.status_code == 200


def test_get_results_returns_all_rows(client):
    response = client.get("/results")
    assert len(response.json()) == 4


def test_get_results_with_hs_code_filter(client):
    response = client.get("/results?hs_code=2710200012")
    data = response.json()
    assert len(data) == 2
    assert all(r["hs_code"] == "2710200012" for r in data)


def test_get_results_with_actor_filter(client):
    response = client.get("/results?actor=VALERO")
    data = response.json()
    assert len(data) == 2
    assert all(r["actor"] == "VALERO" for r in data)


def test_get_results_with_date_range_filter(client):
    response = client.get("/results?from_period=2025-02-01&to_period=2025-02-01")
    data = response.json()
    assert len(data) == 2
    assert all(r["periodo"] == "2025-02-01" for r in data)


# --- GET /results/{hs_code} ---

def test_get_results_by_hs_code_returns_200(client):
    response = client.get("/results/2710200012")
    assert response.status_code == 200


def test_get_results_by_hs_code_returns_correct_rows(client):
    response = client.get("/results/2710200012")
    data = response.json()
    assert len(data) == 2
    assert all(r["hs_code"] == "2710200012" for r in data)


def test_get_results_by_hs_code_not_found_returns_404(client):
    response = client.get("/results/9999999999")
    assert response.status_code == 404


# --- GET /results/{hs_code}/actores ---

def test_get_results_by_hs_code_actores_returns_200(client):
    response = client.get("/results/2710200012/actores")
    assert response.status_code == 200


def test_get_results_by_hs_code_actores_returns_actor_column(client):
    response = client.get("/results/2710200012/actores")
    data = response.json()
    assert len(data) > 0
    assert "actor" in data[0]
