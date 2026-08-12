"""Precómputo de la capa freemium.

Recorre data/freemium/ (20M+ filas transaccionales) y produce las tablas que
consume el dashboard, ya agregadas. El dashboard no procesa nada por sesión:
solo lee estos artefactos, que son lo bastante livianos para versionarse y
desplegarse en Streamlit Cloud.

Salidas en resources/freemium/:
    base/{PAIS}.parquet   detalle periodo × flujo × hs6 × socio (por país)
    country_yearly        valor anual y YoY por país y flujo
    hs_yearly             valor anual y YoY por partida
    partner_share         participación de cada socio y delta en pp
    hhi                   concentración por partida
    monthly_country       serie mensual por país y flujo
    monthly_hs            serie mensual por partida

Uso: python build_freemium.py
"""

import logging
from pathlib import Path

import polars as pl

from src.cleaning_freemium import load_partner_config, normalize_partner
from src.database import save_results
from src.ingest_freemium import (
    aggregate_freemium,
    load_freemium_source,
    scan_freemium_tree,
)
from src.metrics_freemium import (
    compute_country_yearly,
    compute_hhi,
    compute_hs_yearly,
    compute_monthly_by_country,
    compute_monthly_by_hs,
    compute_partner_by_country,
    compute_partner_share,
    compute_registros,
)

FREEMIUM_DIR = Path("data/freemium")
CONFIG_PATH = Path("config_freemium.yml")
PARTNER_CONFIG_PATH = Path("resources/partner_aliases.yml")
OUT_DIR = Path("resources/freemium")
DB_PATH = "data/processed/econolens.duckdb"

# Tablas que solo dependen de la base.
DERIVED = {
    "country_yearly": compute_country_yearly,
    "hs_yearly": compute_hs_yearly,
    "partner_country": compute_partner_by_country,
    "hhi": compute_hhi,
    "monthly_country": compute_monthly_by_country,
    "monthly_hs": compute_monthly_by_hs,
}

# Tablas acotadas a las partidas relevantes: necesitan hs_yearly ya calculada.
DERIVED_RELEVANTES = {
    "partner_share": compute_partner_share,
    "registros": compute_registros,
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _mb(path: Path) -> float:
    return path.stat().st_size / 1024**2


def build_base() -> pl.DataFrame:
    """Lee el árbol de parquets, normaliza socios y agrega en una sola pasada."""
    sources = scan_freemium_tree(FREEMIUM_DIR)
    if not sources:
        raise SystemExit(f"No se encontraron parquets en {FREEMIUM_DIR}/")

    logger.info("Fuentes detectadas: %d", len(sources))
    for country in sorted({s.country for s in sources}):
        detalle = sorted(f"{s.flow[:4]}{s.year}" for s in sources if s.country == country)
        logger.info("  %s → %s", country, " ".join(detalle))

    # La normalización de socios va antes del group_by: si no, cada grafía del
    # mismo país ("U.S.A", "Estados Unidos") queda como una fila distinta.
    partner_config = load_partner_config(PARTNER_CONFIG_PATH)
    frames = [
        normalize_partner(load_freemium_source(s, CONFIG_PATH), partner_config)
        for s in sources
    ]
    logger.info("Agregando (lazy)...")
    return aggregate_freemium(frames)


def write_base_partitioned(base: pl.DataFrame) -> None:
    """Escribe la base particionada por país.

    Particionar permite que el dashboard lea con scan_parquet solo el país
    seleccionado en vez de cargar los 7M de filas completos.
    """
    base_dir = OUT_DIR / "base"
    base_dir.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for country in base["country"].unique().sort():
        path = base_dir / f"{country}.parquet"
        base.filter(pl.col("country") == country).write_parquet(path, compression="zstd")
        total += _mb(path)
    logger.info("base particionada: %d países, %.1f MB", base["country"].n_unique(), total)


def _write(df: pl.DataFrame, name: str) -> None:
    path = OUT_DIR / f"{name}.parquet"
    df.write_parquet(path, compression="zstd")
    save_results(df, DB_PATH, table=f"freemium_{name}", if_exists="replace")
    logger.info("  %-16s %9s filas  %5.1f MB", name, f"{df.height:,}", _mb(path))


def write_derived(base_lf: pl.LazyFrame) -> None:
    """Calcula y escribe las tablas derivadas, en parquet y en DuckDB."""
    for name, fn in DERIVED.items():
        _write(fn(base_lf).collect(), name)

    hs_yearly = pl.scan_parquet(OUT_DIR / "hs_yearly.parquet")
    for name, fn in DERIVED_RELEVANTES.items():
        _write(fn(base_lf, hs_yearly).collect(), name)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base = build_base()
    logger.info("Base agregada: %s filas × %s columnas", f"{base.height:,}", base.width)

    write_base_partitioned(base)

    # Se relee desde disco para no mantener los 7M de filas en memoria mientras
    # se calculan las seis tablas derivadas.
    del base
    base_lf = pl.scan_parquet(OUT_DIR / "base" / "*.parquet")

    logger.info("Tablas derivadas:")
    write_derived(base_lf)

    cobertura = (
        base_lf.group_by(["country", "flow"])
        .agg([
            pl.col("periodo").dt.year().unique().sort().alias("años"),
            (pl.col("value").sum() / 1e9).round(1).alias("miles_M_USD"),
        ])
        .sort(["country", "flow"])
        .collect()
    )
    logger.info("Cobertura:\n%s", cobertura)


if __name__ == "__main__":
    main()
