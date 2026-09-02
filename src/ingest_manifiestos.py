"""Ingesta de manifiestos de carga del Perú (impo/expo × aéreo/marítimo).

Flujo:
    data/data-manifiestos/*_{im|ex}_{aereo|maritimo}_*.csv
        → derivar flujo y vía del NOMBRE del archivo
        → renombrar al schema canónico con el mapeo por formato
          (config_manifiestos.yml)
        → completar con nulos las columnas que ese formato no trae
        → derivar periodo y fecha de DIA/MES/AÑO

Los cuatro formatos salen con el mismo esquema, así que se concatenan sin
`how="diagonal"`. El recorrido es lazy: cada mes son ~93k filas × 55 columnas y
solo se materializa lo que el build necesita escribir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from src.ingest import _DTYPE_MAP, load_config

# Lo que el nombre del archivo sí dice de forma consistente. El periodo NO:
# tres formatos escriben `..._2026_7.csv` y ex_aereo escribe `..._072026_7.csv`,
# así que se deriva de las columnas DIA/MES/AÑO.
_FLUJO_POR_TOKEN: dict[str, str] = {"im": "impo", "ex": "expo"}
_VIAS: tuple[str, ...] = ("maritimo", "aereo")

_PATRON_FORMATO = re.compile(
    rf"_(?P<flujo>im|ex)_(?P<via>{'|'.join(_VIAS)})_", re.IGNORECASE
)

# Columnas que no vienen de la fuente: se calculan al cargar.
CAMPOS_DERIVADOS: tuple[str, ...] = ("flujo", "via", "periodo", "fecha")


@dataclass(frozen=True)
class Campo:
    """Un campo del schema canónico.

    `nivel` distingue el dato propio de cada guía (`fila`) del que pertenece a
    la declaración y viene repetido en todas sus filas (`dua`). Los de nivel
    `dua` no se pueden sumar tal cual: ver `src.cleaning_manifiestos`.
    """

    name: str
    dtype: str
    nivel: str
    requerido: bool = False

    @property
    def polars_dtype(self) -> type[pl.DataType]:
        return _DTYPE_MAP.get(self.dtype, pl.String)

    def castear(self, expr: pl.Expr) -> pl.Expr:
        """Lleva la columna cruda (siempre texto) a su tipo canónico.

        Los enteros pasan por Float64: no todos los meses los escriben igual y
        castear `"2.0"` directo a Int64 devuelve nulo. Mayo escribe los TEUs
        así, y las importaciones marítimas de ese mes sumaban 0 TEUs mientras
        junio y julio sumaban ~130.000.
        """
        if self.polars_dtype == pl.Int64:
            return expr.cast(pl.Float64, strict=False).cast(pl.Int64, strict=False)
        return expr.cast(self.polars_dtype, strict=False)


@dataclass(frozen=True)
class ManifiestoSource:
    """Un CSV de manifiestos, con su contexto derivado del nombre."""

    path: Path
    flujo: str
    via: str

    @property
    def formato(self) -> str:
        return f"{self.flujo}_{self.via}"


def parse_formato(nombre: str) -> tuple[str, str] | None:
    """Deriva (flujo, vía) del nombre de archivo, o None si no lo reconoce.

    Tolera mayúsculas y cualquier forma de escribir el periodo alrededor.
    """
    match = _PATRON_FORMATO.search(nombre)
    if match is None:
        return None
    return (
        _FLUJO_POR_TOKEN[match.group("flujo").lower()],
        match.group("via").lower(),
    )


def scan_manifiestos_dir(root: Path | str) -> list[ManifiestoSource]:
    """Recorre un directorio de CSV de manifiestos.

    Los archivos cuyo nombre no declara flujo y vía se ignoran en silencio: la
    cobertura real se deriva de lo que existe en disco.
    """
    root = Path(root)
    if not root.is_dir():
        return []

    fuentes: list[ManifiestoSource] = []
    for path in sorted(root.glob("*.csv")):
        formato = parse_formato(path.name)
        if formato is None:
            continue
        fuentes.append(ManifiestoSource(path=path, flujo=formato[0], via=formato[1]))
    return fuentes


def campos_canonicos(config_path: Path | str) -> dict[str, Campo]:
    """Devuelve el schema canónico declarado en config_manifiestos.yml."""
    cfg: dict[str, Any] = load_config(config_path)
    return {
        c["name"]: Campo(
            name=c["name"],
            dtype=c.get("dtype", "string"),
            nivel=c.get("nivel", "fila"),
            requerido=bool(c.get("requerido", False)),
        )
        for c in cfg.get("campos", [])
    }


def _mapeo_del_formato(cfg: dict[str, Any], formato: str) -> dict[str, str]:
    mapeo = cfg.get("formatos", {}).get(formato)
    if mapeo is None:
        declarados = sorted(cfg.get("formatos", {}))
        raise ValueError(
            f"Formato '{formato}' no declarado en la configuración. "
            f"Formatos disponibles: {declarados}"
        )
    return mapeo


def load_manifiesto_source(
    source: ManifiestoSource,
    config_path: Path | str,
) -> pl.LazyFrame:
    """Abre un CSV de manifiestos ya normalizado al schema canónico.

    Todo se lee como texto y se castea después: las columnas numéricas de la
    fuente traen sufijos de Excel (`="80440.0"`) y ceros iniciales que un
    inferidor de tipos destruiría.
    """
    cfg: dict[str, Any] = load_config(config_path)
    campos = campos_canonicos(config_path)
    mapeo = _mapeo_del_formato(cfg, source.formato)
    lectura = cfg.get("lectura", {})

    lf = pl.scan_csv(
        source.path,
        separator=lectura.get("separator", ";"),
        encoding=lectura.get("encoding", "utf8"),
        infer_schema_length=0,
        truncate_ragged_lines=True,
        ignore_errors=True,
    )
    presentes = set(lf.collect_schema().names())

    faltan = [
        c.name
        for c in campos.values()
        if c.requerido and mapeo.get(c.name) not in presentes
    ]
    if faltan:
        raise ValueError(
            f"Columnas requeridas no encontradas en {source.path.name}: "
            f"{sorted(faltan)}"
        )

    proyeccion: list[pl.Expr] = []
    for campo in campos.values():
        origen = mapeo.get(campo.name)
        if origen in presentes:
            proyeccion.append(campo.castear(pl.col(origen)).alias(campo.name))
        else:
            # El formato no trae este campo: existe igual, vacío, para que los
            # cuatro compartan esquema y se puedan concatenar.
            proyeccion.append(pl.lit(None, dtype=campo.polars_dtype).alias(campo.name))

    lf = lf.select(proyeccion)

    fecha = pl.date(pl.col("anio"), pl.col("mes"), pl.col("dia"))
    return lf.with_columns(
        pl.lit(source.flujo, dtype=pl.String).alias("flujo"),
        pl.lit(source.via, dtype=pl.String).alias("via"),
        fecha.dt.strftime("%Y-%m").alias("periodo"),
        fecha.alias("fecha"),
    )
