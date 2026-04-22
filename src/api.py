# FastAPI application
import os
from fastapi import FastAPI, Depends, HTTPException

from src.database import load_results

app = FastAPI(title="EconoLens API")


def get_db_path() -> str:
    return os.getenv("ECONOLENS_DB_PATH", "data/processed/econolens.duckdb")


@app.get("/results")
def get_results(
    hs_code: str | None = None,
    actor: str | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
    db_path: str = Depends(get_db_path),
):
    df = load_results(db_path, hs_code=hs_code, actor=actor, from_period=from_period, to_period=to_period)
    return df.to_dicts()


@app.get("/results/{hs_code}/actores")
def get_results_by_hs_actores(
    hs_code: str,
    from_period: str | None = None,
    to_period: str | None = None,
    db_path: str = Depends(get_db_path),
):
    df = load_results(db_path, hs_code=hs_code, from_period=from_period, to_period=to_period)
    if df.is_empty():
        raise HTTPException(status_code=404, detail=f"hs_code '{hs_code}' no encontrado")
    return df.to_dicts()


@app.get("/results/{hs_code}")
def get_results_by_hs(
    hs_code: str,
    from_period: str | None = None,
    to_period: str | None = None,
    db_path: str = Depends(get_db_path),
):
    df = load_results(db_path, hs_code=hs_code, from_period=from_period, to_period=to_period)
    if df.is_empty():
        raise HTTPException(status_code=404, detail=f"hs_code '{hs_code}' no encontrado")
    return df.to_dicts()
