"""Precómputo del módulo de manifiestos: CSV crudos → lake parquet particionado.

    data/data-manifiestos/*_{im|ex}_{aereo|maritimo}_*.csv
        → derivar flujo y vía del nombre del archivo
        → normalizar al schema canónico (config_manifiestos.yml)
        → prorratear el valor de la DUA, rellenar los códigos arancelarios,
          unificar grafías
        → data/manifiestos/periodo=YYYY-MM/flujo=.../via=.../datos.parquet

No es incremental: reconstruye desde cero lo que encuentre en disco. Agregar un
mes es soltar sus CSV en data/data-manifiestos/ y volver a correr esto.

    python build_manifiestos.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from src.cleaning_manifiestos import clean_manifiestos
from src.ingest_manifiestos import load_manifiesto_source, scan_manifiestos_dir

RAIZ = Path(__file__).parent
CRUDOS = RAIZ / "data" / "data-manifiestos"
LAKE = RAIZ / "data" / "manifiestos"
CONFIG = RAIZ / "config_manifiestos.yml"

# El path ya declara estas tres: guardarlas también en el archivo las
# duplicaría al leer con hive_partitioning.
CLAVES_PARTICION = ("periodo", "flujo", "via")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("build_manifiestos")


def vaciar_lake(lake: Path) -> int:
    """Borra los parquet del lake sin borrar sus carpetas.

    El repo vive dentro de OneDrive, que mantiene los directorios abiertos
    mientras sincroniza: `shutil.rmtree` falla ahí con `PermissionError` y deja
    el lake a medio borrar. Borrar solo archivos no toca ese candado. Las
    carpetas que quedan vacías se intentan quitar y, si no se puede, no
    molestan: la lectura hace glob sobre archivos.
    """
    if not lake.exists():
        return 0

    borrados = 0
    for parquet in lake.rglob("*.parquet"):
        parquet.unlink()
        borrados += 1

    for carpeta in sorted(lake.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if carpeta.is_dir():
            try:
                carpeta.rmdir()
            except OSError:
                pass

    return borrados


def construir(crudos: Path = CRUDOS, lake: Path = LAKE, config: Path = CONFIG) -> int:
    """Reconstruye el lake completo. Devuelve el total de filas escritas."""
    fuentes = scan_manifiestos_dir(crudos)
    if not fuentes:
        log.warning("No hay CSV reconocibles en %s", crudos)
        return 0

    log.info("%d archivos encontrados en %s", len(fuentes), crudos)

    if vaciar_lake(lake):
        log.info("Lake anterior descartado")

    total = 0
    for fuente in fuentes:
        lf = load_manifiesto_source(fuente, config)
        df = clean_manifiestos(lf).collect()

        for (periodo,), bloque in df.partition_by(
            "periodo", as_dict=True, include_key=True
        ).items():
            destino = (
                lake
                / f"periodo={periodo}"
                / f"flujo={fuente.flujo}"
                / f"via={fuente.via}"
            )
            destino.mkdir(parents=True, exist_ok=True)
            bloque.drop(CLAVES_PARTICION).write_parquet(
                destino / "datos.parquet", compression="zstd"
            )
            total += bloque.height
            log.info(
                "%-14s %s → %6d filas", fuente.formato, periodo, bloque.height
            )

    log.info("Lake reconstruido en %s — %d filas", lake, total)
    return total


def resumen(lake: Path = LAKE) -> pl.DataFrame:
    """Filas y totales por periodo, flujo y vía — para verificar el build."""
    lf = pl.scan_parquet(lake / "**" / "*.parquet", hive_partitioning=True)
    return (
        lf.group_by("periodo", "flujo", "via")
        .agg(
            pl.len().alias("filas"),
            pl.col("fob_usd").sum().alias("fob_usd"),
            pl.col("cif_usd").sum().alias("cif_usd"),
            pl.col("peso_kg").sum().alias("peso_kg"),
            pl.col("teus").sum().alias("teus"),
        )
        .sort("periodo", "flujo", "via")
        .collect()
    )


if __name__ == "__main__":
    if construir():
        with pl.Config(tbl_rows=40, tbl_width_chars=140):
            log.info("Resumen del lake:\n%s", resumen())
