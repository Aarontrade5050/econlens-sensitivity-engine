import polars as pl
from src.pipeline import run_pipeline_multi
from src.database import load_results

DB_PATH = "data/processed/econolens.duckdb"

df = pl.read_parquet("data/interim/df_all.parquet")
df = df.with_columns(pl.col("PARTIDA ARANCELARIA").cast(pl.String))

result = run_pipeline_multi(
    df,
    hs_codes=None,
    hs_col="PARTIDA ARANCELARIA",
    unit_col="UNIDAD DE MEDIDA",
    value_col="US$ FOB",
    quantity_col="CANTIDAD",
    day_col="DÍA",
    month_col="MES",
    year_col="AÑO",
    actor_col="IMPORTADOR",
    db_path=DB_PATH,
    if_exists="replace",
)

print(f"Productos procesados: {result['hs_code'].n_unique()}")
print(f"Actores procesados:   {result['actor'].n_unique()}")
print(f"Total filas:          {result.shape[0]}")
print(f"Guardado en:          {DB_PATH}")
print()

# Ejemplo de consulta desde la base de datos
diesel = load_results(DB_PATH, hs_code="2710200012")
print(f"Diesel (2710200012) — {diesel.shape[0]} filas")
print(diesel.sort(["actor", "periodo"]).select([
    "periodo", "actor", "ise_score", "ise_nivel", "shock_compuesto_flag"
]).to_pandas().to_string())
