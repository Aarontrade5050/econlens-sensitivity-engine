"""Consultas por entidad sobre el lake de manifiestos.

`pivot.py` resuelve la tabla dinámica genérica: agrupá por lo que quieras y
medí lo que quieras. Este módulo resuelve la otra mitad del buscador, la que da
la lectura accionable: quién es cada actor de la cadena, cuánto pesa en su
mercado y con quién trabaja.

Las definiciones de cada número —qué columna, qué operación, sobre qué
denominador— están en `docs/manifiestos_metricas.md`, que es el contrato entre
el diseño y este código. Los §§ que se citan en los docstrings son de ese
documento.

Igual que en `pivot.py`, nada de lo que elige el usuario se interpola en el
SQL: los nombres se resuelven contra los catálogos y los valores viajan como
parámetros.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from src.pivot import (
    DIMENSIONES,
    METRICAS,
    SIN_DATO,
    Dimension,
    Metrica,
    _columnas,
    _Consulta,
    _dimension,
    _filtrar,
    _metrica,
    _numerico,
    conectar,
)


@dataclass(frozen=True)
class Rol:
    """Un papel que una entidad cumple en el manifiesto.

    Es una dimensión con una lectura de negocio: la misma cadena puede ser
    naviera, agente de aduana y consignataria a la vez, y el buscador tiene que
    mostrarla tres veces y no una.
    """

    name: str
    etiqueta: str
    singular: str


def _roles(*items: tuple[str, str, str]) -> dict[str, Rol]:
    return {n: Rol(n, e, s) for n, e, s in items}


ROLES: dict[str, Rol] = _roles(
    ("actor", "Importadores / Exportadores", "Importador / Exportador"),
    ("transportista", "Navieras / Aerolíneas", "Naviera / Aerolínea"),
    ("agente_aduana", "Agentes de aduana", "Agente de aduana"),
    ("agencia_carga", "Agencias de carga", "Agencia de carga"),
    ("agente_portuario", "Agentes portuarios", "Agente portuario"),
    ("almacen", "Almacenes", "Almacén"),
    ("contraparte", "Contrapartes extranjeras", "Contraparte extranjera"),
    ("pais", "Países", "País"),
    ("puerto_embarque", "Puertos de embarque", "Puerto de embarque"),
    ("puerto_desembarque", "Puertos de desembarque", "Puerto de desembarque"),
    ("nave_vuelo", "Naves y vuelos", "Nave / Vuelo"),
    ("partida_4d", "Partidas", "Partida"),
    ("ruc_actor", "RUC", "RUC"),
)

# §4 — Valores que no son empresas. No se borran nunca: se marcan, y el ranking
# de actores los deja fuera con un interruptor visible. La lista de filiales de
# navieras va a crecer, por eso vive acá y no dentro de una consulta.
# Filiales peruanas de navieras que figuran como consignatarias de su propia
# carga. Van por nombre exacto y no por patrón: «PERU» dentro del nombre no
# alcanza para decidir que una empresa no es un importador real. La fuente
# escribe la misma filial de varias formas, así que cada grafía es una entrada.
BUCKETS_ACTOR: tuple[str, ...] = (
    "MAERSK LINE PERU S.A.C.",
    "MEDITERRANEAN SHIPPING COMPANY DEL PERU SAC",
    "HAPAG-LLOYD ( PERU ) S.A.C.",
    "HAPAG-LLOYD PERU S.A.C.",
    "CMA CGM PERU S.A.C.",
    "OCEAN NETWORK EXPRESS (PERU) S.A.C.",
    "WAN HAI LINES PERU S.A.C.",
    "PACIFIC INTERNATIONAL LINES PERU S.A.C.",
    "COSCO SHIPPING LINES (PERU) S.A",
    "COSCO SHIPPING LINES PERU SA",
    "COSCO SHIPPING LINES PERU S.A",
    "TERMINALES PORTUARIOS PERUANOS SAC",
)

# Conocimientos sin consignatario nombrado. Van por prefijo porque la fuente
# los escribe de doce maneras: `A LA ORDEN`, `TO ORDER`, `TO THE ORDER`, y
# todas las variantes con el banco endosatario detrás
# (`TO THE ORDER OF BANCO DE CREDITO DEL PERU`, 1.700 TEUs).
PREFIJOS_BUCKET_ACTOR: tuple[str, ...] = ("A LA ORDEN", "TO ORDER", "TO THE ORDER")

# Buckets de otras columnas: se muestran siempre —son el valor más frecuente—
# pero marcados, porque no son una empresa con la que se pueda hablar.
BUCKETS_OTROS: dict[str, tuple[str, ...]] = {
    "agencia_carga": ("EMBARQUE DIRECTO",),
    "transportista": ("ZZ-OTRAS",),
}

# §5.3 — La métrica que encabeza una tarjeta o un resultado, según el
# manifiesto. Nunca el valor: la cobertura no lo permite.
METRICA_PRINCIPAL: dict[str, str] = {"maritimo": "teus", "aereo": "peso_kg"}

TOPE_RANKING = 12
TOPE_BUSQUEDA = 8


# ---------------------------------------------------------------------------
# Composición de consultas
# ---------------------------------------------------------------------------

def _rol(nombre: str) -> Rol:
    if nombre not in ROLES:
        raise ValueError(
            f"Rol desconocido: '{nombre}'. Disponibles: {sorted(ROLES)}"
        )
    return ROLES[nombre]


def _where(filtro: _Consulta, extra: Sequence[str] = ()) -> str:
    """Une el filtro del recorte con cláusulas propias de la consulta."""
    if not extra:
        return filtro.where
    unidas = " AND ".join(extra)
    return f"{filtro.where} AND {unidas}" if filtro.where else f"WHERE {unidas}"


def _exclusion_buckets() -> tuple[str, list[Any]]:
    """Cláusula que deja fuera a los actores que no son empresas (§4).

    El nulo también sale: sin nombre no hay cuenta que vender. Cuando el
    interruptor está apagado el nulo vuelve, etiquetado como `(sin dato)`.
    """
    marcadores = ", ".join("?" for _ in BUCKETS_ACTOR)
    clausulas = [f"actor IS NOT NULL", f"actor NOT IN ({marcadores})"]
    params: list[Any] = list(BUCKETS_ACTOR)
    for prefijo in PREFIJOS_BUCKET_ACTOR:
        clausulas.append("actor NOT LIKE ?")
        params.append(f"{prefijo}%")
    return " AND ".join(clausulas), params


def es_bucket(rol: str, valor: str | None) -> bool:
    """Si ese valor es un cajón de la fuente y no una entidad real."""
    if valor is None:
        return False
    if rol == "actor":
        return (valor in BUCKETS_ACTOR
                or any(valor.startswith(p) for p in PREFIJOS_BUCKET_ACTOR))
    return valor in BUCKETS_OTROS.get(rol, ())


def _pedir(metrica: str) -> tuple[Metrica, str]:
    return _metrica(metrica)


def _agregado(metrica: str) -> tuple[Metrica, str, str]:
    """La métrica, su agregación y su SQL, en un solo paso."""
    obj, agregacion = _metrica(metrica)
    return obj, agregacion, obj.sql(agregacion)


# ---------------------------------------------------------------------------
# Los cuatro manifiestos
# ---------------------------------------------------------------------------

def resumen_cuadrantes(
    lake: Path | str,
    desde: str | None = None,
    hasta: str | None = None,
) -> pl.DataFrame:
    """Una fila por cuadrante con dato: el selector de la pantalla de entrada.

    Solo devuelve los cuadrantes que existen en el lake para ese periodo. Junio
    2026 no tiene importación aérea y eso tiene que verse, no rellenarse.
    """
    con = conectar(lake)
    filtro = _filtrar(None, desde, hasta)
    contenedores = METRICAS["contenedores"].sql("suma")
    sql = (
        f"SELECT flujo, via, COUNT(*) AS registros, SUM(teus) AS teus, "
        f"{contenedores} AS contenedores, SUM(cont_20) AS cont_20, "
        f"SUM(cont_40) AS cont_40, SUM(peso_kg) AS peso_kg, "
        f"COUNT(DISTINCT actor) AS actores, "
        f"COUNT(DISTINCT transportista) AS transportistas "
        f"FROM m {filtro.where} GROUP BY 1, 2 ORDER BY 1, 2"
    )
    return _numerico(con.execute(sql, filtro.params).pl())


# ---------------------------------------------------------------------------
# Ranking — «quién mueve más»
# ---------------------------------------------------------------------------

def ranking(
    lake: Path | str,
    dimension: str,
    metrica: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    cardinalidades: Sequence[str] = (),
    extras: Sequence[str] = (),
    excluir_buckets: bool = False,
    denominador: dict[str, Sequence[str]] | None = None,
    tope: int = TOPE_RANKING,
) -> pl.DataFrame:
    """Los valores de una dimensión ordenados por una métrica, con su share.

    `denominador` decide contra qué se compara cada fila, y es lo único que
    separa las dos lecturas del módulo:

    - Sin pasarlo, el universo es el mismo recorte de las filas. Filtrando por
      un importador se obtiene su **reparto interno** (§3.2): "el 25,4% de los
      TEUs de Supermercados viajó con MAERSK", y los porcentajes suman 100.
    - Pasando el cuadrante entero se obtiene la **participación de mercado**
      (§3.1): "MAERSK mueve el 19,3% de la entrada marítima".

    En los dos casos el denominador ignora la exclusión de buckets: excluir a
    una naviera del listado no borra su carga del mercado. Por eso los
    porcentajes de un ranking excluido no suman 100: el hueco es la carga que
    quedó fuera, y la pantalla la muestra como una franja aparte.

    `extras` agrega otras métricas a cada fila sin tocar el orden. Es lo que
    llena las columnas del ranking: contenedores, TEUs, guías y valor al lado
    de la que se eligió para ordenar.
    """
    dim = _dimension(dimension)
    obj, _, agregado = _agregado(metrica)
    cardinales = [_dimension(c) for c in cardinalidades]

    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    universo = (filtro if denominador is None
                else _filtrar(denominador, desde, hasta))

    seleccion = [f'{dim.sql} AS valor', f'{agregado} AS "{obj.name}"']
    seleccion.append(
        f'ROUND(100.0 * {agregado} / '
        f'NULLIF((SELECT total FROM universo), 0), 1) AS share'
    )
    seleccion += [
        f'{_agregado(m)[2]} AS "{m}"' for m in extras if m != metrica
    ]
    seleccion += [
        f'COUNT(DISTINCT {c.name}) AS "n_{c.name}"' for c in cardinales
    ]

    # El universo del denominador va primero en el texto de la consulta, así
    # que sus parámetros también: DuckDB liga los `?` por posición.
    where, propios = _recorte_sin_buckets(filtro, excluir_buckets)
    params: list[Any] = list(universo.params) + propios

    sql = (
        f"WITH universo AS (SELECT {agregado} AS total FROM m {universo.where}) "
        f"SELECT {', '.join(seleccion)} FROM m {where} "
        # El nombre desempata: sin eso, dos entidades con el mismo volumen
        # cambian de lugar entre corridas y el ranking deja de ser reproducible.
        f'GROUP BY 1 ORDER BY "{obj.name}" DESC NULLS LAST, valor '
        f"LIMIT {int(tope)}"
    )
    df = _numerico(con.execute(sql, params).pl())
    return df.with_columns(
        pl.col("valor")
        .map_elements(lambda v: es_bucket(dimension, v), return_dtype=pl.Boolean)
        .alias("bucket")
    )


# ---------------------------------------------------------------------------
# Buscador
# ---------------------------------------------------------------------------

def buscar(
    lake: Path | str,
    termino: str,
    desde: str | None = None,
    hasta: str | None = None,
    roles: Sequence[str] | None = None,
    tope_por_rol: int = TOPE_BUSQUEDA,
) -> pl.DataFrame:
    """Busca un texto en todos los roles y todos los cuadrantes a la vez.

    Devuelve una fila por `(rol, valor, cuadrante)`: que la misma cadena
    aparezca varias veces es el resultado, no un duplicado. «maersk» es naviera,
    agente de aduana, agencia de carga, consignataria y almacén, y son cinco
    negocios distintos.

    La métrica que se devuelve depende del manifiesto (§5.3): TEUs en marítimo,
    peso en aéreo, nunca el valor.
    """
    termino = (termino or "").strip()
    if not termino:
        return _vacio_busqueda()

    con = conectar(lake)
    del_lake = _columnas(con)
    pedidos = [r for r in (roles or ROLES) if _rol(r).name in del_lake]
    if not pedidos:
        return _vacio_busqueda()

    filtro = _filtrar(None, desde, hasta)
    piezas: list[pl.DataFrame] = []
    for nombre in pedidos:
        dim = DIMENSIONES.get(nombre) or Dimension(nombre, nombre, "Otros")
        piezas.append(_buscar_rol(con, nombre, dim, filtro, termino, tope_por_rol))

    filas = [p for p in piezas if not p.is_empty()]
    if not filas:
        return _vacio_busqueda()
    return pl.concat(filas).sort(["share", "metrica"], descending=True)


def _vacio_busqueda() -> pl.DataFrame:
    return pl.DataFrame(schema={
        "rol": pl.String, "valor": pl.String, "flujo": pl.String,
        "via": pl.String, "metrica": pl.Float64, "unidad": pl.String,
        "share": pl.Float64, "registros": pl.Int64, "bucket": pl.Boolean,
    })


def _buscar_rol(
    con: Any,
    rol: str,
    dim: Dimension,
    filtro: _Consulta,
    termino: str,
    tope: int,
) -> pl.DataFrame:
    """Coincidencias de un rol, con la métrica y el share de cada cuadrante."""
    where = _where(filtro, [f"upper({dim.name}) LIKE '%' || upper(?) || '%'"])
    params = list(filtro.params) + list(filtro.params) + [termino]
    sql = (
        "WITH tot AS (SELECT flujo, via, SUM(teus) AS t_teus, "
        "  SUM(peso_kg) AS t_peso FROM m "
        f" {filtro.where} GROUP BY 1, 2) "
        "SELECT sub.flujo, sub.via, sub.valor, sub.teus, sub.peso_kg, "
        "  sub.registros, tot.t_teus, tot.t_peso FROM ("
        f"  SELECT flujo, via, {dim.sql} AS valor, SUM(teus) AS teus, "
        f"    SUM(peso_kg) AS peso_kg, COUNT(*) AS registros "
        f"  FROM m {where} GROUP BY 1, 2, 3) sub "
        "JOIN tot ON sub.flujo = tot.flujo AND sub.via = tot.via "
        f"ORDER BY COALESCE(sub.teus, sub.peso_kg) DESC NULLS LAST "
        f"LIMIT {int(tope)}"
    )
    df = _numerico(con.execute(sql, params).pl())
    if df.is_empty():
        return _vacio_busqueda()

    principal = pl.when(pl.col("via") == "aereo")
    metrica = principal.then(pl.col("peso_kg")).otherwise(pl.col("teus"))
    total = principal.then(pl.col("t_peso")).otherwise(pl.col("t_teus"))
    return df.select(
        pl.lit(rol).alias("rol"),
        pl.col("valor"),
        pl.col("flujo"),
        pl.col("via"),
        metrica.cast(pl.Float64).alias("metrica"),
        principal.then(pl.lit("peso_kg")).otherwise(pl.lit("teus")).alias("unidad"),
        (100.0 * metrica / total).round(1).alias("share"),
        pl.col("registros").cast(pl.Int64),
        pl.col("valor")
        .map_elements(lambda v: es_bucket(rol, v), return_dtype=pl.Boolean)
        .alias("bucket"),
    ).filter(pl.col("valor") != SIN_DATO)


# ---------------------------------------------------------------------------
# Ficha de un operador — captura y oportunidad
# ---------------------------------------------------------------------------

def captura(
    lake: Path | str,
    rol: str,
    valor: str,
    metrica: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    sobre: str = "actor",
    excluir_buckets: bool = True,
    tope: int = TOPE_RANKING,
) -> pl.DataFrame:
    """La cartera de un operador, con cuánto de cada cliente ya tiene (§3.3).

    El numerador es lo que ese cliente mueve con el operador; el denominador,
    todo lo que ese cliente mueve con quien sea. Sale de **una sola** consulta:
    calcularlo con dos y dividir en Python haría que el denominador saliera de
    un recorte distinto en cuanto alguien tocara un filtro.

    Lo que falta para 100% es lo que hoy está en manos de otro. Es el número
    más accionable del módulo.
    """
    operador = _dimension(_rol(rol).name)
    cliente = _dimension(sobre)
    obj, agregacion, agregado = _agregado(metrica)
    propio = obj.sql_si(f"{operador.sql} = ?", agregacion)

    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    where, params = _recorte_sin_buckets(filtro, excluir_buckets)

    sql = (
        f"SELECT {cliente.sql} AS valor, "
        f"  {propio} AS metrica, "
        f"  {agregado} AS total, "
        f"  ROUND(100.0 * {propio} / NULLIF({agregado}, 0), 1) AS captura "
        f"FROM m {where} GROUP BY 1 "
        f"HAVING {propio} > 0 ORDER BY metrica DESC LIMIT {int(tope)}"
    )
    # Dos `?` del operador en el SELECT y uno en el HAVING, y en el medio los
    # del WHERE: DuckDB liga los marcadores por posición en el texto del SQL.
    return _numerico(con.execute(sql, [valor, valor] + params + [valor]).pl())


def oportunidad(
    lake: Path | str,
    rol: str,
    valor: str,
    metrica: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    sobre: str = "actor",
    piso: float = 0.0,
    techo: float = 12.0,
    excluir_buckets: bool = True,
    tope: int = TOPE_RANKING,
) -> pl.DataFrame:
    """Las cuentas grandes donde el operador casi no está (§3.4).

    `piso` es el volumen mínimo para que la cuenta valga la visita y `techo` el
    porcentaje por debajo del cual se considera que hay lugar. Los dos son
    parámetros de la pantalla y no constantes escondidas.

    `alternativas` cuenta cuántos operadores **del mismo rol** usa ese cliente:
    en la ficha de una naviera son navieras, y en la de una agencia de carga
    son agencias. Contar siempre navieras respondía otra pregunta.
    """
    operador = _dimension(_rol(rol).name)
    cliente = _dimension(sobre)
    obj, agregacion, agregado = _agregado(metrica)
    propio = f"COALESCE({obj.sql_si(f'{operador.sql} = ?', agregacion)}, 0)"

    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    where, params = _recorte_sin_buckets(filtro, excluir_buckets)

    sql = (
        f"SELECT {cliente.sql} AS valor, "
        f"  {agregado} AS total, "
        f"  {propio} AS metrica, "
        f"  ROUND(100.0 * {propio} / NULLIF({agregado}, 0), 1) AS captura, "
        f"  COUNT(DISTINCT {operador.name}) AS alternativas "
        f"FROM m {where} GROUP BY 1 "
        f"HAVING {agregado} >= ? "
        f"   AND 100.0 * {propio} / NULLIF({agregado}, 0) < ? "
        f"ORDER BY total DESC LIMIT {int(tope)}"
    )
    return _numerico(
        con.execute(
            sql, [valor, valor] + params + [piso, valor, techo]
        ).pl()
    )


def _recorte_sin_buckets(
    filtro: _Consulta, excluir: bool
) -> tuple[str, list[Any]]:
    if not excluir:
        return filtro.where, list(filtro.params)
    clausula, params = _exclusion_buckets()
    return _where(filtro, [clausula]), list(filtro.params) + params


# ---------------------------------------------------------------------------
# Costo implícito, mix, serie, cardinalidad, tramos
# ---------------------------------------------------------------------------

def costo_implicito(
    lake: Path | str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[str, float | None]:
    """Flete por TEU y CIF por kilo, con la cobertura de cada uno (§3.5).

    Es razón de sumas y no promedio de razones: `AVG(flete / teus)` le daría el
    mismo peso a un conocimiento de un contenedor que a uno de cincuenta, y el
    número dejaría de ser el costo del conjunto.

    No es una tarifa. Depende de la mezcla de rutas y solo existe donde la guía
    cruzó con una DUA, por eso nunca se muestra sin su cobertura al lado.
    """
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    fila = con.execute(
        "SELECT ROUND(SUM(flete_usd) / NULLIF(SUM(teus), 0), 1), "
        "       ROUND(SUM(cif_usd) / NULLIF(SUM(peso_kg), 0), 3), "
        "       ROUND(100.0 * COUNT(flete_usd) / NULLIF(COUNT(*), 0), 1), "
        "       ROUND(100.0 * COUNT(cif_usd) / NULLIF(COUNT(*), 0), 1) "
        f"FROM m {filtro.where}",
        filtro.params,
    ).fetchone()
    usd_teu, usd_kg, cob_flete, cob_cif = fila
    return {
        "usd_por_teu": float(usd_teu) if usd_teu is not None else None,
        "usd_por_kg": float(usd_kg) if usd_kg is not None else None,
        "cobertura_flete": float(cob_flete) if cob_flete is not None else 0.0,
        "cobertura_cif": float(cob_cif) if cob_cif is not None else 0.0,
    }


def mix(
    lake: Path | str,
    dimension: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> pl.DataFrame:
    """Reparto de las guías entre los valores de una dimensión categórica.

    El nulo es una categoría más y se conserva: en canal significa que la guía
    no cruzó con una DUA, y decirlo es información.
    """
    dim = _dimension(dimension)
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    sql = (
        f"SELECT {dim.sql} AS valor, COUNT(*) AS registros, "
        f"  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct "
        f"FROM m {filtro.where} GROUP BY 1 ORDER BY registros DESC"
    )
    return _numerico(con.execute(sql, filtro.params).pl())


def serie(
    lake: Path | str,
    metrica: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    share_sobre: dict[str, Sequence[str]] | None = None,
) -> pl.DataFrame:
    """La métrica mes a mes, y opcionalmente su share dentro de otro universo.

    El share de un mes se calcula contra el total **de ese mes** (§3.10). Con el
    total del rango entero, un mes flojo del mercado se leería como un mes
    fuerte de la entidad.
    """
    obj, _, agregado = _agregado(metrica)
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)

    if share_sobre is None:
        sql = (
            f"SELECT periodo, {agregado} AS \"{obj.name}\" FROM m "
            f"{filtro.where} GROUP BY 1 ORDER BY 1"
        )
        return _numerico(con.execute(sql, filtro.params).pl())

    universo = _filtrar(share_sobre, desde, hasta)
    sql = (
        f"WITH tot AS (SELECT periodo, {agregado} AS total FROM m "
        f"  {universo.where} GROUP BY 1) "
        f"SELECT sub.periodo, sub.valor AS \"{obj.name}\", "
        f"  ROUND(100.0 * sub.valor / NULLIF(tot.total, 0), 1) AS share "
        f"FROM (SELECT periodo, {agregado} AS valor FROM m {filtro.where} "
        f"      GROUP BY 1) sub "
        f"LEFT JOIN tot ON sub.periodo = tot.periodo ORDER BY 1"
    )
    return _numerico(
        con.execute(sql, list(universo.params) + list(filtro.params)).pl()
    )


def cardinalidad(
    lake: Path | str,
    dimensiones: Sequence[str],
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[str, int]:
    """Cuántos valores distintos tiene cada dimensión en el recorte (§3.6).

    Los nulos no cuentan: «23 navieras» son 23 navieras con nombre.
    """
    dims = [_dimension(d) for d in dimensiones]
    if not dims:
        return {}
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    seleccion = ", ".join(
        f'COUNT(DISTINCT {d.name}) AS "{d.name}"' for d in dims
    )
    fila = con.execute(
        f"SELECT {seleccion} FROM m {filtro.where}", filtro.params
    ).pl()
    return {c: int(fila[c][0] or 0) for c in fila.columns}


def tramos(
    lake: Path | str,
    dimension: str,
    metrica: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    cortes: Sequence[int] = (12, 100),
    excluir_buckets: bool = True,
) -> dict[str, Any]:
    """Cuánto se llevan los primeros, los del medio y la cola (§3.9).

    Los tramos se dividen por el mercado **completo**, así que lo que falta
    para 100% es exactamente la carga excluida. El hueco es el dato: en la
    entrada marítima es el 18,6% que figura a nombre de las navieras y de los
    conocimientos «a la orden».
    """
    dim = _dimension(dimension)
    obj, _, agregado = _agregado(metrica)
    cortes = tuple(sorted({int(c) for c in cortes if c > 0}))

    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    where, params = _recorte_sin_buckets(filtro, excluir_buckets)

    bandas: list[tuple[int, int | None]] = []
    anterior = 0
    for corte in cortes:
        bandas.append((anterior + 1, corte))
        anterior = corte
    bandas.append((anterior + 1, None))

    seleccion = []
    for i, (inicio, fin) in enumerate(bandas):
        condicion = (f"rn >= {inicio}" if fin is None
                     else f"rn BETWEEN {inicio} AND {fin}")
        seleccion.append(f"SUM(c) FILTER (WHERE {condicion}) AS t{i}")
    seleccion.append("SUM(c) AS incluido")

    sql = (
        f"WITH universo AS (SELECT {agregado} AS total FROM m {filtro.where}), "
        f"r AS (SELECT {dim.sql} AS v, {agregado} AS c, "
        f"      ROW_NUMBER() OVER (ORDER BY {agregado} DESC) AS rn "
        f"      FROM m {where} GROUP BY 1) "
        f"SELECT {', '.join(seleccion)}, (SELECT total FROM universo) AS total "
        f"FROM r"
    )
    fila = con.execute(sql, list(filtro.params) + params).fetchone()
    total = float(fila[-1] or 0)
    incluido = float(fila[-2] or 0)

    def pct(v: Any) -> float:
        return round(float(v or 0) / total * 100, 1) if total else 0.0

    return {
        "total": total,
        "tramos": [
            {"desde": inicio, "hasta": fin, "valor": float(fila[i] or 0),
             "pct": pct(fila[i])}
            for i, (inicio, fin) in enumerate(bandas)
        ],
        "excluido_pct": round((total - incluido) / total * 100, 1) if total else 0.0,
    }
