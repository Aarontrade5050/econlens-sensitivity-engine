"""Métricas de la capa freemium, calculadas solo sobre el valor declarado.

La fuente estadística no trae cantidad ni unidad de medida, así que no existe
precio unitario y por lo tanto tampoco volatilidad de precio, elasticidad ni
ISE: esas métricas viven en el motor premium. Lo que sí se puede medir con
valor es crecimiento interanual, participación de cada socio y concentración
de mercado (HHI).

Todas las funciones toman y devuelven LazyFrame para que el recorrido sobre la
base agregada (7M+ filas) se resuelva en una sola pasada.
"""

from __future__ import annotations

from typing import Sequence

import polars as pl

# Socios que no son un proveedor real y no deben contar como concentración.
# Coinciden con `etiquetas` en resources/partner_aliases.yml.
NO_IDENTIFICADOS: tuple[str, ...] = ("No declarado", "Zona franca / régimen especial")

# La concentración se publica como número efectivo de socios (10.000 / HHI),
# no como HHI crudo. A 6 dígitos el HHI mediano es 5.259, muy por encima del
# umbral antimonopolio clásico de 2.500: esos cortes vienen de medir empresas
# dentro de un mercado y aquí se miden países proveedores de un producto, así
# que dejarían el 84% de las partidas en "alta". El equivalente en número de
# socios se lee solo ("se abastece de 1,5 países") y no necesita umbral externo.
HHI_BASE = 10_000

# Cortes sobre el número efectivo de socios. Sobre las partidas relevantes
# reparten 17 / 31 / 33 / 19 %, un espectro utilizable.
SOCIOS_DOMINANTE = 1.5
SOCIOS_POCOS = 3.0
SOCIOS_VARIOS = 6.0

# Piso de valor anual para considerar una partida relevante. Las partidas por
# debajo son 16% del universo pero solo 0.78% del comercio, y casi todas tienen
# un único socio por puro azar de muestreo.
VALOR_MINIMO_RELEVANTE = 50_000_000.0


def _with_anio(lf: pl.LazyFrame) -> pl.LazyFrame:
    return lf.with_columns(pl.col("periodo").dt.year().alias("anio"))


def _add_yoy(lf: pl.LazyFrame, keys: Sequence[str]) -> pl.LazyFrame:
    """Añade value_prev y yoy_pct comparando contra el mismo grupo del año anterior.

    yoy_pct queda nulo cuando falta el año base o cuando este es cero: mostrar
    0% o infinito sería inventar una lectura que el dato no soporta.
    """
    prev = pl.col("value").shift(1).over(keys, order_by="anio")
    contiguo = (pl.col("anio") - pl.col("anio").shift(1).over(keys, order_by="anio")) == 1

    return lf.with_columns(
        pl.when(contiguo).then(prev).alias("value_prev")
    ).with_columns(
        pl.when(pl.col("value_prev") > 0)
        .then((pl.col("value") / pl.col("value_prev") - 1) * 100)
        .alias("yoy_pct")
    )


def _sum_by(lf: pl.LazyFrame, keys: Sequence[str]) -> pl.LazyFrame:
    return lf.group_by(keys).agg(pl.col("value").sum()).sort(keys)


def compute_country_yearly(base: pl.LazyFrame) -> pl.LazyFrame:
    """Valor anual y crecimiento interanual por país y flujo.

    Alimenta las tarjetas de Importaciones/Exportaciones del panorama.
    """
    keys = ["country", "flow"]
    anual = _sum_by(_with_anio(base), [*keys, "anio"])
    return _add_yoy(anual, keys)


def compute_hs_yearly(base: pl.LazyFrame) -> pl.LazyFrame:
    """Valor anual y crecimiento interanual por partida de 6 dígitos.

    Alimenta "Productos que mueven la aguja" y la tabla multi-país.
    """
    keys = ["country", "flow", "hs_code"]
    anual = (
        _with_anio(base)
        .group_by([*keys, "anio"])
        .agg([
            pl.col("value").sum(),
            pl.col("desc_aran").drop_nulls().first().alias("desc_aran"),
        ])
        .sort([*keys, "anio"])
    )
    return _add_yoy(anual, keys)


def _partner_share_over(base: pl.LazyFrame, keys: Sequence[str]) -> pl.LazyFrame:
    """Share de cada socio dentro del universo definido por `keys`, más el
    delta en puntos porcentuales frente al año anterior."""
    anual = _sum_by(_with_anio(base), [*keys, "anio", "partner"])

    con_share = anual.with_columns(
        (pl.col("value") / pl.col("value").sum().over([*keys, "anio"]) * 100).alias("share_pct")
    )

    partner_keys = [*keys, "partner"]
    prev_share = pl.col("share_pct").shift(1).over(partner_keys, order_by="anio")
    contiguo = (pl.col("anio") - pl.col("anio").shift(1).over(partner_keys, order_by="anio")) == 1

    return con_share.with_columns(
        pl.when(contiguo).then(prev_share).alias("share_pct_prev")
    ).with_columns(
        (pl.col("share_pct") - pl.col("share_pct_prev")).alias("delta_pp")
    )


def compute_partner_share(
    base: pl.LazyFrame,
    hs_yearly: pl.LazyFrame | None = None,
    valor_minimo: float = VALOR_MINIMO_RELEVANTE,
) -> pl.LazyFrame:
    """Participación de cada socio dentro de país × flujo × partida × año.

    Alimenta la "mezcla de socios" de la pantalla de producto. Si se pasa
    `hs_yearly`, se acota a las partidas relevantes: el share de una partida
    marginal no se consulta nunca y es la mitad del peso de la tabla.
    """
    share = _partner_share_over(base, ["country", "flow", "hs_code"])
    if hs_yearly is None:
        return share

    relevantes = (
        hs_yearly.filter(pl.col("value") >= valor_minimo)
        .select(["country", "flow", "hs_code"])
        .unique()
    )
    return share.join(relevantes, on=["country", "flow", "hs_code"])


def compute_partner_by_country(base: pl.LazyFrame) -> pl.LazyFrame:
    """Participación de cada socio en el comercio total del país y flujo.

    Alimenta "Socios principales" del panorama. Se calcula sobre todas las
    partidas, no solo las relevantes: el ranking país debe reflejar el 100%
    del comercio declarado.
    """
    return _partner_share_over(base, ["country", "flow"])


def compute_hhi(
    base: pl.LazyFrame,
    no_identificados: Sequence[str] = NO_IDENTIFICADOS,
) -> pl.LazyFrame:
    """Índice Herfindahl-Hirschman de concentración de socios por partida.

    El HHI se calcula solo sobre los socios identificados: agrupar bajo un
    mismo rótulo el valor sin país declarado y tratarlo como un proveedor
    inventaría concentración que el dato no respalda. `cobertura_pct` informa
    qué porción del valor sí tiene socio identificado, para que el dashboard
    pueda advertir cuando el índice se apoya en poca base (Argentina declara
    ~14% de su valor sin socio).
    """
    keys = ["country", "flow", "hs_code", "anio"]
    anual = _sum_by(_with_anio(base), [*keys, "partner"])

    identificado = ~pl.col("partner").is_in(list(no_identificados))
    valor_ident = pl.when(identificado).then(pl.col("value")).otherwise(0.0)
    total_ident = valor_ident.sum().over(keys)

    con_share = anual.with_columns([
        pl.when(total_ident > 0)
        .then(valor_ident / total_ident * 100)
        .otherwise(None)
        .alias("_share_ident"),
        (total_ident / pl.col("value").sum().over(keys) * 100).alias("_cobertura"),
    ])

    resumen = (
        con_share.sort([*keys, "_share_ident"], descending=[False] * len(keys) + [True])
        .group_by(keys)
        .agg([
            (pl.col("_share_ident").pow(2)).sum().alias("hhi"),
            pl.col("_share_ident").drop_nulls().head(3).sum().alias("top3_pct"),
            pl.col("partner").filter(identificado).first().alias("top_partner"),
            pl.col("_share_ident").drop_nulls().first().alias("top_partner_pct"),
            pl.col("_cobertura").first().alias("cobertura_pct"),
        ])
        .sort(keys)
    )

    # Hay embarques declarados en 0: sin valor no hay reparto que medir, y
    # dividir por ese total daba cobertura NaN y n_socios infinito.
    sin_cobertura = (pl.col("cobertura_pct") == 0) | pl.col("cobertura_pct").is_nan()
    limpio = resumen.with_columns([
        pl.when(sin_cobertura).then(None).otherwise(pl.col("hhi")).alias("hhi"),
        pl.when(sin_cobertura).then(None).otherwise(pl.col("top3_pct")).alias("top3_pct"),
    ])

    con_socios = limpio.with_columns(
        (HHI_BASE / pl.col("hhi")).alias("n_socios")
    ).with_columns(
        pl.when(pl.col("n_socios").is_null())
        .then(None)
        .when(pl.col("n_socios") < SOCIOS_DOMINANTE)
        .then(pl.lit("1 socio dominante"))
        .when(pl.col("n_socios") < SOCIOS_POCOS)
        .then(pl.lit("2-3 socios"))
        .when(pl.col("n_socios") < SOCIOS_VARIOS)
        .then(pl.lit("4-6 socios"))
        .otherwise(pl.lit("Diversificado"))
        .alias("categoria")
    )

    # Variación del número de socios frente al año anterior: es la lectura de
    # sustitución de origen ("pasó de 4 socios a 1") con la que se ordena la
    # pantalla de concentración.
    hs_keys = ["country", "flow", "hs_code"]
    prev = pl.col("n_socios").shift(1).over(hs_keys, order_by="anio")
    contiguo = (pl.col("anio") - pl.col("anio").shift(1).over(hs_keys, order_by="anio")) == 1

    return con_socios.with_columns(
        pl.when(contiguo).then(prev).alias("n_socios_prev")
    ).with_columns(
        (pl.col("n_socios") - pl.col("n_socios_prev")).alias("delta_socios")
    )


def concentracion_relevante(
    hhi: pl.LazyFrame,
    hs_yearly: pl.LazyFrame,
    valor_minimo: float = VALOR_MINIMO_RELEVANTE,
) -> pl.LazyFrame:
    """Cruza concentración con valor y deja solo las partidas que pesan.

    Una partida con tres embarques al año es concentrada por azar, no por
    dependencia estructural: son el 16% del universo y el 0.78% del comercio.
    Filtrarlas es lo que hace legible la pantalla, sin tocar los cortes.

    Ordena por caída de socios: la partida que más origen sustituyó va primero.
    """
    keys = ["country", "flow", "hs_code", "anio"]
    return (
        hhi.join(hs_yearly.select([*keys, "value", "desc_aran", "yoy_pct"]), on=keys)
        .filter(pl.col("value") >= valor_minimo)
        .sort("delta_socios", nulls_last=True)
    )


def compute_monthly_by_hs(base: pl.LazyFrame) -> pl.LazyFrame:
    """Serie mensual por partida — alimenta el gráfico de 24 meses del producto."""
    return _sum_by(base, ["country", "flow", "hs_code", "periodo"])


def compute_registros(
    base: pl.LazyFrame,
    hs_yearly: pl.LazyFrame,
    valor_minimo: float = VALOR_MINIMO_RELEVANTE,
) -> pl.LazyFrame:
    """Detalle mes × socio de las partidas relevantes, con su peso en el mes.

    Es el máximo detalle que publica freemium: sin identidad de actor, que es
    justamente lo que el tier premium desbloquea. Se acota a las partidas
    relevantes porque es la tabla más pesada y el resto no se consulta.
    """
    relevantes = (
        hs_yearly.filter(pl.col("value") >= valor_minimo)
        .select(["country", "flow", "hs_code"])
        .unique()
    )
    mes_keys = ["country", "flow", "hs_code", "periodo"]
    return (
        _sum_by(base, [*mes_keys, "partner"])
        .join(relevantes, on=["country", "flow", "hs_code"])
        .with_columns(
            (pl.col("value") / pl.col("value").sum().over(mes_keys) * 100).alias("share_mes")
        )
        .sort([*mes_keys, "value"], descending=[False, False, False, True, True])
    )


def compute_monthly_by_country(base: pl.LazyFrame) -> pl.LazyFrame:
    """Serie mensual por país y flujo — alimenta los sparklines del panorama."""
    return _sum_by(base, ["country", "flow", "periodo"])
