import polars as pl
from src.pipeline import run_pipeline_multi
from src.database import load_results
from src.aggregations import run_aggregations

DB_PATH = "data/processed/econolens.duckdb"

df = pl.read_parquet("data/interim/df_all.parquet")
df = df.with_columns(pl.col("PARTIDA ARANCELARIA").cast(pl.String))

# --- Pipeline ISE ---
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
print(f"Total filas ISE:      {result.shape[0]}")
print(f"Guardado en:          {DB_PATH}")

# --- Tablas de agregación (market share, precios, rutas, spread, entidades) ---
# Reusa df (PARTIDA ARANCELARIA ya casteada a String) para que hs_code sea consistente con la tabla ISE.
print("\nCalculando tablas de agregación...")
run_aggregations(df, DB_PATH)
print("Tablas de agregación guardadas en DuckDB.")
print(f"  - market_share")
print(f"  - price_by_country")
print(f"  - price_by_route")
print(f"  - price_spread")
print(f"  - entities_over_time")
