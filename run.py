import polars as pl
from src.pipeline import run_pipeline

df = pl.read_parquet("data/interim/df_all.parquet")
df = df.with_columns(pl.col("PARTIDA ARANCELARIA").cast(pl.String))

result = run_pipeline(
    df,
    hs_code="2710200012",
    hs_col="PARTIDA ARANCELARIA",
    unit_col="UNIDAD DE MEDIDA",
    value_col="US$ FOB",
    quantity_col="CANTIDAD",
    day_col="DÍA",
    month_col="MES",
    year_col="AÑO",
    actor_col="IMPORTADOR",
)

result.write_csv("data/processed/sample_output_actor.csv")

print(
    result
    .sort(["actor", "periodo"])
    .select([
        "periodo", "actor", "volumen", "precio",
        "var_pct_volumen_mensual", "shock_compuesto_flag", "ise_score", "ise_nivel",
    ])
    .to_pandas()
    .to_string()
)

print(f"\nShape: {result.shape}")
print(f"Actores: {result['actor'].n_unique()}")
print("Guardado en: data/processed/sample_output_actor.csv")
