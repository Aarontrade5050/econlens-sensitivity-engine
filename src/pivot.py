"""Constructor de tabla dinámica sobre el lake de manifiestos.

El usuario elige dimensiones, métricas y filtros; acá se arma el SQL y DuckDB
lo resuelve sobre los parquet particionados, sin cargar nada a memoria.

Nada de lo que elige el usuario se interpola en el SQL: los nombres de
dimensión, métrica y agregación se resuelven contra los catálogos de este
módulo (`ValueError` si no están), y los valores de filtro viajan como
parámetros. Es la única defensa que necesita una interfaz que deja armar
consultas libres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import duckdb
import polars as pl

# Etiqueta con la que se muestran los nulos. La fuente tiene muchos: el 100%
# del país de destino en exportación aérea, por ejemplo. Se muestran en vez de
# descartarse, para que el total de la tabla siga cuadrando con el universo.
SIN_DATO = "(sin dato)"

# Tope de columnas de una tabla cruzada. Sin esto, cruzar por importador
# devuelve miles de columnas.
TOP_COLUMNAS = 12

LIMITE_FILAS = 500

MetricaPedida = str | tuple[str, str]


@dataclass(frozen=True)
class Dimension:
    """Una columna por la que se puede agrupar o filtrar."""

    name: str
    etiqueta: str
    grupo: str

    @property
    def sql(self) -> str:
        """Expresión de agrupación, con los nulos ya etiquetados."""
        return f"COALESCE(CAST({self.name} AS VARCHAR), '{SIN_DATO}')"


@dataclass(frozen=True)
class Metrica:
    """Un valor agregable."""

    name: str
    etiqueta: str
    grupo: str
    columna: str | None = None
    agregacion: str = "suma"
    agregaciones: tuple[str, ...] = ("suma", "promedio", "maximo", "minimo")
    decimales: int = 0

    def sql(self, agregacion: str) -> str:
        if agregacion not in self.agregaciones:
            raise ValueError(
                f"La métrica '{self.name}' no admite la agregación "
                f"'{agregacion}'. Admite: {list(self.agregaciones)}"
            )
        return AGREGACIONES[agregacion].format(col=self.columna or "*")


AGREGACIONES: dict[str, str] = {
    "suma": "SUM({col})",
    "promedio": "AVG({col})",
    "maximo": "MAX({col})",
    "minimo": "MIN({col})",
    "conteo": "COUNT({col})",
    "distintos": "COUNT(DISTINCT {col})",
}

ETIQUETA_AGREGACION: dict[str, str] = {
    "suma": "Suma", "promedio": "Promedio", "maximo": "Máximo",
    "minimo": "Mínimo", "conteo": "Conteo", "distintos": "Distintos",
}


def _dims(*items: tuple[str, str, str]) -> dict[str, Dimension]:
    return {n: Dimension(n, e, g) for n, e, g in items}


DIMENSIONES: dict[str, Dimension] = _dims(
    ("periodo", "Periodo", "Tiempo"),
    ("fecha", "Fecha", "Tiempo"),
    ("flujo", "Flujo", "Operación"),
    ("via", "Vía", "Operación"),
    ("aduana", "Aduana", "Operación"),
    ("canal", "Canal", "Operación"),
    ("incoterm", "Incoterm", "Operación"),
    ("tipo_carga", "Tipo de carga", "Operación"),
    ("actor", "Importador / Exportador", "Actores"),
    ("ruc_actor", "RUC", "Actores"),
    ("contraparte", "Contraparte extranjera", "Actores"),
    ("agencia_carga", "Agencia de carga", "Actores"),
    ("agente_aduana", "Agente de aduana", "Actores"),
    ("agente_portuario", "Agente portuario", "Actores"),
    ("almacen", "Almacén", "Actores"),
    ("transportista", "Naviera / Aerolínea", "Logística"),
    ("nave_vuelo", "Nave / Vuelo", "Logística"),
    ("pais", "País", "Logística"),
    ("puerto_embarque", "Puerto de embarque", "Logística"),
    ("puerto_desembarque", "Puerto de desembarque", "Logística"),
    ("partida_4d", "Partida (4 díg.)", "Producto"),
    ("desc_partida", "Descripción de partida", "Producto"),
    ("capitulo", "Capítulo", "Producto"),
    ("desc_capitulo", "Descripción de capítulo", "Producto"),
    ("seccion", "Sección", "Producto"),
    ("desc_seccion", "Descripción de sección", "Producto"),
    ("multi_partida", "Declara varias partidas", "Producto"),
)


METRICAS: dict[str, Metrica] = {
    m.name: m
    for m in (
        Metrica("fob_usd", "FOB (USD)", "Valor", "fob_usd", decimales=0),
        Metrica("cif_usd", "CIF (USD)", "Valor", "cif_usd", decimales=0),
        Metrica("flete_usd", "Flete (USD)", "Valor", "flete_usd", decimales=0),
        Metrica("seguro_usd", "Seguro (USD)", "Valor", "seguro_usd", decimales=0),
        Metrica("peso_kg", "Peso (kg)", "Carga", "peso_kg", decimales=0),
        Metrica("peso_neto_kg", "Peso neto (kg)", "Carga", "peso_neto_kg"),
        Metrica("teus", "TEUs", "Carga", "teus"),
        Metrica("cont_20", "Contenedores 20'", "Carga", "cont_20"),
        Metrica("cont_40", "Contenedores 40' (FEU)", "Carga", "cont_40"),
        Metrica("n_partidas", "Partidas declaradas", "Carga", "n_partidas"),
        Metrica("registros", "Guías / BL", "Conteos", "*",
                agregacion="conteo", agregaciones=("conteo",)),
        Metrica("documentos", "Documentos únicos", "Conteos", "documento",
                agregacion="distintos", agregaciones=("distintos",)),
        Metrica("duas", "DUAs únicas", "Conteos", "dua",
                agregacion="distintos", agregaciones=("distintos",)),
        Metrica("actores", "Actores únicos", "Conteos", "actor",
                agregacion="distintos", agregaciones=("distintos",)),
    )
}


@dataclass
class _Consulta:
    """SQL con sus parámetros, para que ningún valor entre por interpolación."""

    where: str
    params: list[Any] = field(default_factory=list)


def _dimension(nombre: str) -> Dimension:
    if nombre not in DIMENSIONES:
        raise ValueError(
            f"Dimensión desconocida: '{nombre}'. "
            f"Disponibles: {sorted(DIMENSIONES)}"
        )
    return DIMENSIONES[nombre]


def _metrica(pedida: MetricaPedida) -> tuple[Metrica, str]:
    nombre, agregacion = pedida if isinstance(pedida, tuple) else (pedida, None)
    if nombre not in METRICAS:
        raise ValueError(
            f"Métrica desconocida: '{nombre}'. Disponibles: {sorted(METRICAS)}"
        )
    metrica = METRICAS[nombre]
    agregacion = agregacion or metrica.agregacion
    if agregacion not in AGREGACIONES:
        raise ValueError(
            f"Agregación desconocida: '{agregacion}'. "
            f"Disponibles: {sorted(AGREGACIONES)}"
        )
    return metrica, agregacion


def etiqueta_metrica(pedida: MetricaPedida) -> str:
    """Nombre de columna de una métrica, con la agregación si no es la propia."""
    metrica, agregacion = _metrica(pedida)
    if agregacion == metrica.agregacion:
        return metrica.etiqueta
    return f"{metrica.etiqueta} ({ETIQUETA_AGREGACION[agregacion].lower()})"


_CONEXIONES: dict[str, duckdb.DuckDBPyConnection] = {}


def _numerico(df: pl.DataFrame) -> pl.DataFrame:
    """Convierte los Decimal que devuelve DuckDB a enteros o flotantes.

    `SUM` sobre BIGINT vuelve como DECIMAL(38,0), que el formateo de la
    interfaz no sabe manejar.
    """
    casts = [
        pl.col(c).cast(pl.Int64 if dtype.scale == 0 else pl.Float64)
        for c, dtype in df.schema.items()
        if isinstance(dtype, pl.Decimal)
    ]
    return df.with_columns(casts) if casts else df


def conectar(lake: Path | str) -> duckdb.DuckDBPyConnection:
    """Devuelve una conexión con la vista `m` sobre el lake particionado.

    La vista no materializa nada: DuckDB lee los parquet al resolver cada
    consulta y poda las particiones que el filtro de periodo descarta. La
    conexión se reutiliza porque abrirla y leer los metadatos de los parquet
    cuesta más de un segundo, y Streamlit vuelve a ejecutar el script entero
    ante cada interacción.
    """
    lake = Path(lake)
    if not lake.is_dir() or not any(lake.rglob("*.parquet")):
        raise ValueError(
            f"No hay datos de manifiestos en {lake}. "
            "Corré `python build_manifiestos.py` para construir el lake."
        )

    clave = str(lake.resolve())
    if clave not in _CONEXIONES:
        patron = (lake / "**" / "*.parquet").as_posix()
        con = duckdb.connect()
        con.execute(
            f"CREATE VIEW m AS SELECT * FROM "
            f"read_parquet('{patron}', hive_partitioning=1)"
        )
        _CONEXIONES[clave] = con
    return _CONEXIONES[clave]


def _filtrar(
    filtros: dict[str, Sequence[str]] | None,
    desde: str | None,
    hasta: str | None,
) -> _Consulta:
    clausulas: list[str] = []
    params: list[Any] = []

    if desde:
        clausulas.append("periodo >= ?")
        params.append(desde)
    if hasta:
        clausulas.append("periodo <= ?")
        params.append(hasta)

    for nombre, valores in (filtros or {}).items():
        dimension = _dimension(nombre)
        if not valores:
            continue
        marcadores = ", ".join("?" for _ in valores)
        clausulas.append(f"{dimension.sql} IN ({marcadores})")
        params.extend(valores)

    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    return _Consulta(where, params)


def _columnas(con: duckdb.DuckDBPyConnection) -> set[str]:
    """Columnas que expone la vista del lake."""
    return {
        f[0] for f in con.execute("DESCRIBE SELECT * FROM m").fetchall()
    }


def _valores_de_columna(
    con: duckdb.DuckDBPyConnection,
    dimension: Dimension,
    filtro: _Consulta,
    tope: int,
) -> list[str]:
    """Los valores más frecuentes de una dimensión, para cruzar o filtrar."""
    filas = con.execute(
        f"SELECT {dimension.sql} AS v, COUNT(*) AS n FROM m {filtro.where} "
        f"GROUP BY 1 ORDER BY n DESC, v LIMIT {int(tope)}",
        filtro.params,
    ).fetchall()
    return [f[0] for f in filas]


def run_pivot(
    lake: Path | str,
    filas: Sequence[str],
    metricas: Sequence[MetricaPedida],
    columna: str | None = None,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limite: int = LIMITE_FILAS,
    top_columnas: int = TOP_COLUMNAS,
) -> pl.DataFrame:
    """Arma la tabla dinámica y la devuelve con las etiquetas de la interfaz.

    Con `columna` se cruza: cada valor de esa dimensión se vuelve una columna,
    acotada al top de valores más frecuentes, más una de total. El cruce usa
    agregados condicionales y no el `PIVOT` de DuckDB, para controlar el nombre
    de cada columna resultante.
    """
    if not filas:
        raise ValueError("Elegí al menos una dimensión para las filas.")
    if not metricas:
        raise ValueError("Elegí al menos una métrica.")

    dimensiones = [_dimension(f) for f in filas]
    pedidas = [_metrica(m) for m in metricas]

    if columna is not None:
        dim_columna = _dimension(columna)
        if columna in filas:
            raise ValueError(
                f"'{dim_columna.etiqueta}' no puede estar en filas y columnas "
                "a la vez."
            )

    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)

    seleccion = [f'{d.sql} AS "{d.etiqueta}"' for d in dimensiones]
    agrupacion = ", ".join(str(i + 1) for i in range(len(dimensiones)))
    # DuckDB liga los `?` por posición en el TEXTO de la consulta, y el SELECT
    # va antes del WHERE: los parámetros del cruce tienen que ir primero.
    params: list[Any] = []

    if columna is None:
        for pedida, (metrica, agregacion) in zip(metricas, pedidas):
            seleccion.append(
                f'{metrica.sql(agregacion)} AS "{etiqueta_metrica(pedida)}"'
            )
        orden = f'"{etiqueta_metrica(metricas[0])}" DESC NULLS LAST'
    else:
        # Se eligen los valores más frecuentes para acotar el ancho, pero se
        # muestran en orden natural: cruzar por periodo tiene que dar columnas
        # cronológicas, no ordenadas por cuál trajo más guías.
        valores = sorted(
            _valores_de_columna(con, dim_columna, filtro, top_columnas)
        )
        una_metrica = len(metricas) == 1
        for valor in valores:
            for pedida, (metrica, agregacion) in zip(metricas, pedidas):
                columna_valor = metrica.sql(agregacion).replace(
                    metrica.columna or "*",
                    f"CASE WHEN {dim_columna.sql} = ? "
                    f"THEN {metrica.columna} END",
                    1,
                ) if metrica.columna != "*" else (
                    f"COUNT(CASE WHEN {dim_columna.sql} = ? THEN 1 END)"
                )
                titulo = valor if una_metrica else f"{valor} · {metrica.etiqueta}"
                seleccion.append(f'{columna_valor} AS "{titulo}"')
                params.append(valor)
        # Total: el mismo agregado sin condicionar, para que la fila cierre.
        for pedida, (metrica, agregacion) in zip(metricas, pedidas):
            titulo = "Total" if una_metrica else f"Total · {metrica.etiqueta}"
            seleccion.append(f'{metrica.sql(agregacion)} AS "{titulo}"')
        orden = f'"{"Total" if una_metrica else f"Total · {pedidas[0][0].etiqueta}"}" DESC NULLS LAST'

    params.extend(filtro.params)
    sql = (
        f"SELECT {', '.join(seleccion)} FROM m {filtro.where} "
        f"GROUP BY {agrupacion} ORDER BY {orden} LIMIT {int(limite)}"
    )
    return _numerico(con.execute(sql, params).pl())


def run_totales(
    lake: Path | str,
    metricas: Sequence[MetricaPedida],
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[str, float]:
    """Agrega las métricas sobre todo el universo filtrado, sin agrupar."""
    if not metricas:
        raise ValueError("Elegí al menos una métrica.")

    pedidas = [_metrica(m) for m in metricas]
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)

    seleccion = [
        f'{metrica.sql(agregacion)} AS "{etiqueta_metrica(pedida)}"'
        for pedida, (metrica, agregacion) in zip(metricas, pedidas)
    ]
    fila = _numerico(
        con.execute(
            f"SELECT {', '.join(seleccion)} FROM m {filtro.where}", filtro.params
        ).pl()
    )
    return {c: fila[c][0] for c in fila.columns}


def cobertura(
    lake: Path | str,
    metrica: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> float:
    """Porcentaje de filas del universo filtrado que traen esa métrica.

    El FOB de exportación solo existe donde la guía cruzó con una DUA: en
    exportación aérea llega al 7% de las filas. Sin este número, un total de
    exportación se lee como si fuera la exportación del país.
    """
    metrica_obj, _ = _metrica(metrica)
    if metrica_obj.columna in (None, "*"):
        return 100.0

    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    total, con_dato = con.execute(
        f"SELECT COUNT(*), COUNT({metrica_obj.columna}) FROM m {filtro.where}",
        filtro.params,
    ).fetchone()
    return round(con_dato / total * 100, 1) if total else 0.0


def periodos_disponibles(lake: Path | str) -> list[str]:
    """Los periodos que existen en el lake, en orden."""
    filas = conectar(lake).execute(
        "SELECT DISTINCT periodo FROM m ORDER BY 1"
    ).fetchall()
    return [f[0] for f in filas]


def valores_de_dimension(
    lake: Path | str,
    dimension: str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    tope: int = 300,
) -> list[str]:
    """Valores de una dimensión ordenados por frecuencia, para los filtros."""
    dim = _dimension(dimension)
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    return _valores_de_columna(con, dim, filtro, tope)


def dimensiones_disponibles(
    lake: Path | str,
    filtros: dict[str, Sequence[str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> list[str]:
    """Dimensiones que tienen algún dato en el universo filtrado.

    Los cuatro formatos no traen lo mismo: exportación aérea no declara país ni
    puerto de destino, y aéreo no tiene contenedores. Ofrecer una dimensión
    vacía sería ofrecer una tabla de una sola fila `(sin dato)`.
    """
    con = conectar(lake)
    filtro = _filtrar(filtros, desde, hasta)
    # Un lake construido antes de que se agregara una dimensión no la tiene:
    # se pregunta solo por las columnas que la vista realmente expone.
    existentes = [d.name for d in DIMENSIONES.values() if d.name in _columnas(con)]
    if not existentes:
        return []
    seleccion = ", ".join(f'COUNT({c}) AS "{c}"' for c in existentes)
    fila = con.execute(
        f"SELECT {seleccion} FROM m {filtro.where}", filtro.params
    ).pl()
    return [c for c in fila.columns if (fila[c][0] or 0) > 0]
