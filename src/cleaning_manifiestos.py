"""Normalización de manifiestos de carga antes de escribir el lake.

Tres arreglos, todos derivados de mirar los datos y no de una excepción:

1. **El valor de la DUA viene repetido.** Una declaración que consolida varias
   guías estampa su FOB/CIF total en cada fila. La DUA `10-235-2026-113318`
   cubre 22 guías aéreas y repite USD 4,28 M en las 22: sumar la columna da
   USD 94 M. Sin corregir, el FOB aéreo de julio 2026 se infla 47%.
2. **Los códigos arancelarios perdieron el cero inicial** al viajar como
   enteros: `604` es la partida 06.04 (follaje), no la 604. Es el mismo
   problema que `normalize_hs6` resuelve en la capa freemium.
3. **La misma entidad se escribe distinto entre formatos**: `UX- AIR EUROPA`
   en importación y `UX - AIR EUROPA` en exportación; el almacén lleva código
   numérico en marítimo y no en aéreo. Sin unificar, un pivote las parte en
   dos filas.

Todo es lazy y vectorizado: sin UDFs de Python.
"""

from __future__ import annotations

from typing import Sequence

import polars as pl

# Valores que la fuente usa para decir "no hay dato". Se vuelven nulos para que
# el pivote los junte en una sola fila "(sin dato)" en vez de inventar
# categorías que compiten entre sí.
_PLACEHOLDERS: tuple[str, ...] = (
    "NO DISPONIBLE",
    "NO DISPONIBLE – LEY 29733",
    "NO DISPONIBLE - LEY 29733",
    "NO DECLARADO",
    "NO DECLARADOS",
    "S/N",
    "SIN DATO",
    "-",
    "--",
    "---",
    ".",
    "0",
)

# Prefijo de código administrativo: `3306-ALMACENES MUNDO S.A.`. Solo numérico,
# para no tocar `MAE-MAERSK`, donde el prefijo es el código de la naviera y sí
# forma parte de la identidad.
_PREFIJO_NUMERICO = r"^\s*\d+\s*-\s*"

# Código de transportista al inicio: `UX- AIR EUROPA` / `11 - TAMPA CARGO`.
# Se conserva el código y se normaliza el separador a un guion sin espacios.
_CODIGO_TRANSPORTISTA = r"^([A-Za-z0-9]{1,4})\s*-\s+"

HS_PARTIDA = 4
HS_SUBPARTIDA = 6
HS_CAPITULO = 2
HS_SECCION = 2

# Columnas monetarias: pertenecen a la declaración, no a la guía.
COLUMNAS_DUA: tuple[str, ...] = ("fob_usd", "cif_usd", "flete_usd", "seguro_usd")

# Dimensiones de texto libre que se limpian siempre.
COLUMNAS_TEXTO: tuple[str, ...] = (
    "actor", "contraparte", "pais", "puerto_embarque", "puerto_desembarque",
    "transportista", "nave_vuelo", "agencia_carga", "agente_aduana",
    "agente_portuario", "almacen", "aduana", "canal", "incoterm", "tipo_carga",
    "desc_producto", "desc_partida", "desc_capitulo", "desc_seccion",
)

# Dimensiones que arrastran un código administrativo al frente.
COLUMNAS_CON_PREFIJO: tuple[str, ...] = ("almacen", "agente_portuario")


def limpiar_texto(expr: pl.Expr) -> pl.Expr:
    """Recorta, colapsa espacios internos y vuelve nulos los marcadores vacíos.

    La fuente trae saltos de línea al final de algunos nombres de naviera y
    dobles espacios en los de almacén, que de otro modo generan dos categorías
    para la misma entidad.
    """
    limpio = (
        expr.cast(pl.String)
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
    )
    return (
        pl.when(limpio.str.to_uppercase().is_in(_PLACEHOLDERS) | (limpio == ""))
        .then(None)
        .otherwise(limpio)
        .alias(expr.meta.output_name())
    )


def quitar_prefijo_codigo(expr: pl.Expr) -> pl.Expr:
    """Saca el código numérico del frente: `3306-ALMACENES MUNDO` → el nombre.

    Marítimo escribe el código y aéreo no, así que sin esto el mismo almacén
    aparece dos veces. Cuando después del código no queda nombre (`6914-`), no
    hay entidad que nombrar y el valor pasa a nulo.
    """
    sin_prefijo = expr.cast(pl.String).str.replace(_PREFIJO_NUMERICO, "")
    return limpiar_texto(sin_prefijo.alias(expr.meta.output_name()))


def normalizar_transportista(expr: pl.Expr) -> pl.Expr:
    """Unifica las grafías de una misma naviera o aerolínea.

    Importación y exportación escriben distinto el separador del código
    (`UX- AIR EUROPA` vs `UX - AIR EUROPA`) y el punto final del nombre
    (`5Y-ATLAS AIR INC` vs `5Y-ATLAS AIR INC.`). Sin esto, un pivote por
    transportista parte la misma empresa en dos filas. El código se conserva:
    es parte de cómo se la identifica.

    El recorte del punto final se aplica solo acá y no a todas las dimensiones
    de texto: en un nombre de empresa `S.A.` es la grafía correcta.
    """
    return limpiar_texto(
        expr.cast(pl.String)
        .str.replace(_CODIGO_TRANSPORTISTA, "${1}-")
        .str.strip_chars_end(" .")
        .alias(expr.meta.output_name())
    )


def _rellenar_hs(columna: str, largo: int) -> pl.Expr:
    """Repone el cero inicial que se perdió al viajar el código como entero."""
    return (
        pl.col(columna)
        .cast(pl.String)
        .str.strip_chars()
        .str.replace(r"\.0+$", "")
        .str.pad_start(largo, "0")
        .alias(columna)
    )


def normalize_hs(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Normaliza los códigos arancelarios y describe la lista de partidas.

    `partidas` es una lista separada por comas: una guía puede declarar muchas
    subpartidas y su valor no está desglosado por ninguna. Por eso la grilla se
    queda a nivel de documento y se publican `n_partidas` y `multi_partida`,
    que permiten aislar los casos de una sola partida cuando se quiere cruzar
    valor contra arancel sin ambigüedad.
    """
    partidas = (
        pl.col("partidas")
        .cast(pl.String)
        # `="80440.0"` — envoltorio de fórmula que deja Excel al exportar
        .str.replace_all(r'[="]', "")
        .str.strip_chars()
    )
    lista = (
        partidas.str.split(",")
        .list.eval(
            pl.element()
            .str.strip_chars()
            .str.replace(r"\.0+$", "")
            .str.pad_start(HS_SUBPARTIDA, "0")
        )
    )

    return lf.with_columns(
        _rellenar_hs("partida_4d", HS_PARTIDA),
        _rellenar_hs("capitulo", HS_CAPITULO),
        _rellenar_hs("seccion", HS_SECCION),
        lista.list.join(",").alias("partidas"),
        lista.list.len().fill_null(0).cast(pl.Int64).alias("n_partidas"),
    ).with_columns(
        (pl.col("n_partidas") > 1).alias("multi_partida"),
    )


def prorratear_valor_dua(
    lf: pl.LazyFrame,
    columnas: Sequence[str] = COLUMNAS_DUA,
    peso: str = "peso_kg",
    dua: str = "dua",
) -> pl.LazyFrame:
    """Reparte por peso el valor que la declaración repite en todas sus filas.

    La clave de reparto es la DUA junto con el propio valor declarado: una
    misma DUA puede traer más de un valor, y agrupar solo por DUA los fundiría.
    Después de esto cualquier suma, en cualquier agrupación, da el total
    declarado.

    Las filas sin DUA quedan intactas: no hay declaración que repartir, y
    agruparlas por el nulo las mezclaría a todas en un solo reparto.
    """
    presentes = [c for c in columnas if c in lf.collect_schema().names()]
    if not presentes:
        return lf

    kilos = pl.col(peso).cast(pl.Float64).fill_null(0.0)

    reparto: list[pl.Expr] = []
    for columna in presentes:
        clave = [dua, columna]
        total_peso = kilos.sum().over(clave)
        filas = pl.len().over(clave)
        reparto.append(
            pl.when(pl.col(dua).is_null())
            .then(pl.col(columna))
            .when(total_peso > 0)
            .then(pl.col(columna) * kilos / total_peso)
            # Sin peso declarado no hay proporción posible: partes iguales.
            .otherwise(pl.col(columna) / filas)
            .alias(columna)
        )

    return lf.with_columns(reparto)


def clean_manifiestos(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Deja un LazyFrame de manifiestos listo para escribir al lake.

    Orden: primero el prorrateo (necesita el peso crudo), después la
    normalización de texto y códigos.
    """
    columnas = set(lf.collect_schema().names())

    lf = prorratear_valor_dua(lf)
    lf = normalize_hs(lf)

    texto = [
        limpiar_texto(pl.col(c))
        for c in COLUMNAS_TEXTO
        if c in columnas and c not in COLUMNAS_CON_PREFIJO and c != "transportista"
    ]
    texto += [
        quitar_prefijo_codigo(pl.col(c)) for c in COLUMNAS_CON_PREFIJO if c in columnas
    ]
    if "transportista" in columnas:
        texto.append(normalizar_transportista(pl.col("transportista")))

    return lf.with_columns(texto) if texto else lf
