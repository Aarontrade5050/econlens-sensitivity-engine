"""Ingesta de la capa freemium: data estadística agregada multi-país.

Flujo:
    data/freemium/{PAIS}/{IM|EX}/{AÑO}.parquet
        → derivar país y flujo de la ruta
        → resolver columnas por alias (config_freemium.yml)
        → normalizar hs_code a 6 dígitos con ceros a la izquierda
        → agregar a periodo × país × flujo × hs_code × partner

Todo el recorrido es lazy: la fuente supera los 20M de filas y nunca se
materializa completa, solo el agregado final.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from src.ingest import _DTYPE_MAP, load_config, resolve_columns, validate_required

_FLOW_BY_FOLDER: dict[str, str] = {"IM": "impo", "EX": "expo"}
_BASIS_BY_FLOW: dict[str, str] = {"impo": "CIF", "expo": "FOB"}

_GROUP_KEYS: list[str] = [
    "periodo",
    "country",
    "flow",
    "base_valor",
    "hs_code",
    "partner",
]

HS_LENGTH = 6


@dataclass(frozen=True)
class FreemiumSource:
    """Un parquet de la capa freemium, con su contexto derivado de la ruta."""

    path: Path
    country: str
    flow: str
    year: int


def scan_freemium_tree(root: Path | str) -> list[FreemiumSource]:
    """Recorre data/freemium/{PAIS}/{IM|EX}/{AÑO}.parquet.

    Las carpetas de flujo desconocidas y los archivos con nombre no numérico se
    ignoran en silencio: la cobertura real se deriva de lo que existe en disco.
    """
    root = Path(root)
    if not root.is_dir():
        return []

    sources: list[FreemiumSource] = []
    for path in sorted(root.glob("*/*/*.parquet")):
        flow = _FLOW_BY_FOLDER.get(path.parent.name.upper())
        if flow is None or not path.stem.isdigit():
            continue
        sources.append(
            FreemiumSource(
                path=path,
                country=path.parent.parent.name.upper(),
                flow=flow,
                year=int(path.stem),
            )
        )
    return sources


def _largo_nacional(lf: pl.LazyFrame, hs_col: str) -> int:
    """Largo del código nacional de esta fuente: el más frecuente de la columna.

    Se usa la moda y no el máximo porque hay fuentes con outliers más largos
    (BO/impo/2025 tiene códigos de 12 dígitos sobre una base de 11) que
    redefinirían el largo y desplazarían todos los códigos del archivo.
    """
    d = (
        lf.select(pl.col(hs_col).cast(pl.String).str.len_chars().alias("n"))
        .drop_nulls()
        .group_by("n")
        .agg(pl.len().alias("f"))
        .sort(["f", "n"], descending=[True, True])
        .head(1)
        .collect()
    )
    return int(d["n"][0]) if d.height else HS_LENGTH


def normalize_hs6(
    lf: pl.LazyFrame,
    hs_col: str = "hs_code",
    largo_nacional: int | None = None,
) -> pl.LazyFrame:
    """Lleva hs_code a String de 6 dígitos.

    Las fuentes entregan el código como Int64, lo que borra el cero inicial de
    los capítulos 01-09. Cuando el código nacional es más largo que 6 dígitos,
    ese cero perdido no se puede reponer rellenando a 6: hay que reponerlo
    respecto del largo del código nacional de la fuente. Argentina usa NCM de
    11 dígitos, así que `01039200191` (porcinos) llega como 10 dígitos y
    truncar los primeros 6 daba `103920`, que es cereales.

    Una fila a la que le falta exactamente un dígito respecto del largo
    nacional es una fila que perdió el cero; se le repone antes de truncar.
    Los códigos mucho más cortos son pseudo-partidas administrativas
    ("420000" = mercadería para consumo a bordo) y se dejan como están.
    """
    if largo_nacional is None:
        largo_nacional = _largo_nacional(lf, hs_col)

    crudo = pl.col(hs_col).cast(pl.String).str.strip_chars()
    completo = (
        pl.when(crudo.str.len_chars() == largo_nacional - 1)
        .then(pl.concat_str(pl.lit("0"), crudo))
        .otherwise(crudo)
    )

    return lf.with_columns(
        completo.str.pad_start(HS_LENGTH, "0").str.slice(0, HS_LENGTH).alias(hs_col)
    )


def load_freemium_source(
    source: FreemiumSource,
    config_path: Path | str,
) -> pl.LazyFrame:
    """Abre un parquet freemium ya normalizado al schema canónico.

    Solo sobreviven las columnas declaradas en config_freemium.yml, por lo que
    las columnas de actor (company, id_company) se descartan por construcción.
    """
    schema: dict[str, Any] = load_config(config_path)
    lf = pl.scan_parquet(source.path)

    probe = pl.DataFrame(schema=lf.collect_schema())
    mapping = resolve_columns(probe, schema)
    rename_map = {src: tgt for src, tgt in mapping.items() if src != tgt}

    lf = lf.rename(rename_map)
    validate_required(probe.rename(rename_map), schema)

    canonical = [f["name"] for f in schema["schema"]["required"]]
    lf = lf.select(canonical)

    casts = [
        pl.col(field["name"]).cast(_DTYPE_MAP[field["dtype"]], strict=False)
        for field in schema["schema"]["required"]
        if field["name"] != "hs_code"
    ]
    lf = normalize_hs6(lf.with_columns(casts))

    return lf.with_columns([
        pl.col("fecha").dt.truncate("1mo").alias("periodo"),
        pl.lit(source.country).alias("country"),
        pl.lit(source.flow).alias("flow"),
        pl.lit(_BASIS_BY_FLOW[source.flow]).alias("base_valor"),
    ])


def aggregate_freemium(frames: Iterable[pl.LazyFrame]) -> pl.DataFrame:
    """Agrega las fuentes a periodo × país × flujo × hs_code × partner.

    base_valor forma parte de la clave: CIF y FOB nunca se suman en un mismo
    total. La descripción arancelaria se conserva como la primera no nula del
    grupo, ya que varía en redacción entre registros del mismo código.
    """
    frames = list(frames)
    if not frames:
        return pl.DataFrame()

    return (
        pl.concat(frames, how="vertical")
        .group_by(_GROUP_KEYS)
        .agg([
            pl.col("value").sum().alias("value"),
            pl.col("desc_aran").drop_nulls().first().alias("desc_aran"),
        ])
        .sort(_GROUP_KEYS)
        .collect()
    )
