import polars as pl
from src.pipeline import run_pipeline_multi
from src.database import load_results, save_results
from src.aggregations import run_aggregations
from src.cleaning import clean_raw_df

DB_PATH = "data/processed/econolens.duckdb"
HS_EXCEL = "data/raw/HS2022_Jerarquia_Completa.xlsx"

df = pl.read_parquet("data/interim/df_all.parquet")
df = df.with_columns(pl.col("PARTIDA ARANCELARIA").cast(pl.String))

# --- Limpieza de nombres y unidades (antes del pipeline) ---
df = clean_raw_df(df)

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

# --- Dimensión arancelaria HS (dim_partida) ---
print("\nCargando jerarquía arancelaria HS...")
dim = pl.read_excel(HS_EXCEL)
dim = dim.rename({
    "Sección": "seccion",
    "Desc. Sección": "desc_seccion",
    "Capítulo": "capitulo",
    "Desc. Capítulo": "desc_capitulo",
    "Partida (4d)": "partida_4d",
    "Desc. Partida": "desc_partida",
    "Subpartida (6d)": "subpartida_6d",
    "Desc. Subpartida": "desc_subpartida",
})
save_results(dim, DB_PATH, table="dim_partida", if_exists="replace")
print(f"dim_partida guardada: {dim.shape[0]} filas × {dim.shape[1]} columnas.")
