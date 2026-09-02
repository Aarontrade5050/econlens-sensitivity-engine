"""Tests para src/pivot.py — constructor de tabla dinámica sobre el lake."""

from pathlib import Path

import polars as pl
import pytest

from src.pivot import (
    AGREGACIONES,
    DIMENSIONES,
    METRICAS,
    SIN_DATO,
    cobertura,
    conectar,
    dimensiones_disponibles,
    periodos_disponibles,
    run_pivot,
    run_totales,
    valores_de_dimension,
)


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    """Lake mínimo con dos periodos, dos navieras y un nulo."""
    raiz = tmp_path / "manifiestos"
    filas = [
        # periodo,  flujo,  via,       transportista, pais,    teus, fob,  cont40, actor
        ("2026-06", "impo", "maritimo", "MAE-MAERSK", "CHINA",   2, 100.0, 1, "ACME"),
        ("2026-06", "impo", "maritimo", "MAE-MAERSK", "BRASIL",  4, 200.0, 2, "ACME"),
        ("2026-06", "impo", "maritimo", "CMA-CGM",    "CHINA",   6, 300.0, 3, "OTRA"),
        ("2026-07", "impo", "maritimo", "MAE-MAERSK", "CHINA",   8, 400.0, 4, "OTRA"),
        ("2026-07", "impo", "maritimo", "CMA-CGM",    None,     10, None,  5, "ACME"),
    ]
    for periodo in ("2026-06", "2026-07"):
        bloque = [f for f in filas if f[0] == periodo]
        destino = raiz / f"periodo={periodo}" / "flujo=impo" / "via=maritimo"
        destino.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({
            "transportista": [f[3] for f in bloque],
            "pais": [f[4] for f in bloque],
            "teus": [f[5] for f in bloque],
            "fob_usd": [f[6] for f in bloque],
            "cont_40": [f[7] for f in bloque],
            "actor": [f[8] for f in bloque],
            "dua": [f"D{i}" for i, _ in enumerate(bloque)],
            "documento": [f"BL{i}" for i, _ in enumerate(bloque)],
        }).write_parquet(destino / "datos.parquet")
    return raiz


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def test_el_catalogo_cubre_las_dimensiones_del_caso_de_uso():
    assert "transportista" in DIMENSIONES
    assert "partida_4d" in DIMENSIONES
    assert "pais" in DIMENSIONES


def test_el_catalogo_cubre_las_metricas_del_caso_de_uso():
    """TEUs y FEUs por naviera es el cuadro que los usuarios ya arman a mano."""
    assert "teus" in METRICAS
    assert "cont_40" in METRICAS
    assert "fob_usd" in METRICAS
    assert "registros" in METRICAS


def test_las_etiquetas_no_se_repiten():
    etiquetas = [d.etiqueta for d in DIMENSIONES.values()]
    assert len(etiquetas) == len(set(etiquetas))
    etiquetas = [m.etiqueta for m in METRICAS.values()]
    assert len(etiquetas) == len(set(etiquetas))


def test_registros_cuenta_filas_y_no_admite_promedio():
    assert METRICAS["registros"].agregaciones == ("conteo",)


# ---------------------------------------------------------------------------
# Validación: nada entra al SQL sin pasar por el catálogo
# ---------------------------------------------------------------------------

def test_dimension_fuera_del_catalogo_es_error(lake):
    with pytest.raises(ValueError, match="Dimensión"):
        run_pivot(lake, filas=["DROP TABLE m"], metricas=["teus"])


def test_metrica_fuera_del_catalogo_es_error(lake):
    with pytest.raises(ValueError, match="Métrica"):
        run_pivot(lake, filas=["transportista"], metricas=["sueldos"])


def test_agregacion_fuera_del_catalogo_es_error(lake):
    with pytest.raises(ValueError, match="Agregación"):
        run_pivot(lake, filas=["transportista"], metricas=[("teus", "mediana")])


def test_agregacion_no_permitida_para_la_metrica_es_error(lake):
    with pytest.raises(ValueError, match="registros"):
        run_pivot(lake, filas=["transportista"], metricas=[("registros", "promedio")])


def test_filtro_sobre_dimension_desconocida_es_error(lake):
    with pytest.raises(ValueError, match="Dimensión"):
        run_pivot(lake, filas=["transportista"], metricas=["teus"],
                  filtros={"; DELETE": ["x"]})


def test_pivote_sin_filas_es_error(lake):
    with pytest.raises(ValueError, match="al menos una dimensión"):
        run_pivot(lake, filas=[], metricas=["teus"])


def test_pivote_sin_metricas_es_error(lake):
    with pytest.raises(ValueError, match="al menos una métrica"):
        run_pivot(lake, filas=["transportista"], metricas=[])


# ---------------------------------------------------------------------------
# Agrupación simple
# ---------------------------------------------------------------------------

def test_agrupa_y_suma_una_metrica(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"])

    assert df.columns == ["Naviera / Aerolínea", "TEUs"]
    valores = dict(zip(df["Naviera / Aerolínea"], df["TEUs"]))
    assert valores == {"MAE-MAERSK": 14, "CMA-CGM": 16}


def test_ordena_por_la_primera_metrica_descendente(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"])

    assert df["Naviera / Aerolínea"].to_list() == ["CMA-CGM", "MAE-MAERSK"]


def test_agrupa_por_varias_dimensiones(lake):
    df = run_pivot(lake, filas=["periodo", "transportista"], metricas=["teus"])

    assert df.columns[:2] == ["Periodo", "Naviera / Aerolínea"]
    assert df.height == 4


def test_varias_metricas_a_la_vez(lake):
    df = run_pivot(lake, filas=["transportista"],
                   metricas=["teus", "cont_40", "registros"])

    assert df.columns == ["Naviera / Aerolínea", "TEUs", "Contenedores 40' (FEU)",
                          "Guías / BL"]
    fila = df.filter(pl.col("Naviera / Aerolínea") == "MAE-MAERSK")
    assert fila["TEUs"][0] == 14
    assert fila["Contenedores 40' (FEU)"][0] == 7
    assert fila["Guías / BL"][0] == 3


def test_promedio_como_agregacion(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=[("fob_usd", "promedio")])

    fila = df.filter(pl.col("Naviera / Aerolínea") == "MAE-MAERSK")
    assert fila[df.columns[1]][0] == pytest.approx(700 / 3)


def test_conteo_de_distintos(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["actores"])

    valores = dict(zip(df["Naviera / Aerolínea"], df["Actores únicos"]))
    assert valores == {"MAE-MAERSK": 2, "CMA-CGM": 2}


def test_el_nulo_se_muestra_como_sin_dato(lake):
    df = run_pivot(lake, filas=["pais"], metricas=["teus"])

    assert SIN_DATO in df["País"].to_list()
    assert None not in df["País"].to_list()


def test_limite_recorta_las_filas(lake):
    df = run_pivot(lake, filas=["periodo", "transportista"], metricas=["teus"],
                   limite=2)

    assert df.height == 2


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def test_filtro_por_valores_de_una_dimension(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   filtros={"transportista": ["MAE-MAERSK"]})

    assert df.height == 1
    assert df["TEUs"][0] == 14


def test_filtro_por_rango_de_periodos(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   desde="2026-07", hasta="2026-07")

    assert df["TEUs"].sum() == 18


def test_filtro_por_sin_dato_alcanza_los_nulos(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   filtros={"pais": [SIN_DATO]})

    assert df.height == 1
    assert df["TEUs"][0] == 10


def test_los_valores_de_filtro_no_se_interpolan_en_el_sql(lake):
    """Un valor con comillas no debe romper ni ejecutar nada."""
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   filtros={"pais": ["' OR 1=1 --"]})

    assert df.height == 0


# ---------------------------------------------------------------------------
# Tabla cruzada
# ---------------------------------------------------------------------------

def test_columna_cruza_los_valores_en_columnas(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   columna="periodo")

    assert df.columns == ["Naviera / Aerolínea", "2026-06", "2026-07", "Total"]
    fila = df.filter(pl.col("Naviera / Aerolínea") == "MAE-MAERSK")
    assert fila["2026-06"][0] == 6
    assert fila["2026-07"][0] == 8
    assert fila["Total"][0] == 14


def test_la_tabla_cruzada_se_acota_al_top_de_columnas(lake):
    """Se queda con el valor de más guías: 2026-06 trae 3 filas y 2026-07, 2."""
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   columna="periodo", top_columnas=1)

    assert df.columns == ["Naviera / Aerolínea", "2026-06", "Total"]


def test_columna_igual_a_una_fila_es_error(lake):
    with pytest.raises(ValueError, match="a la vez"):
        run_pivot(lake, filas=["transportista"], metricas=["teus"],
                  columna="transportista")


# ---------------------------------------------------------------------------
# Totales y cobertura
# ---------------------------------------------------------------------------

def test_totales_agrega_sobre_todo_el_universo_filtrado(lake):
    totales = run_totales(lake, metricas=["teus", "registros"])

    assert totales["TEUs"] == 30
    assert totales["Guías / BL"] == 5


def test_cobertura_reporta_el_porcentaje_con_dato(lake):
    """El FOB de exportación existe en pocas filas: hay que poder decirlo."""
    assert cobertura(lake, "fob_usd") == pytest.approx(80.0)
    assert cobertura(lake, "teus") == pytest.approx(100.0)


def test_cobertura_respeta_los_filtros(lake):
    assert cobertura(lake, "fob_usd", desde="2026-06", hasta="2026-06") == 100.0


def test_cobertura_de_un_universo_vacio_es_cero(lake):
    assert cobertura(lake, "fob_usd", desde="2030-01") == 0.0


# ---------------------------------------------------------------------------
# Ayudas para la interfaz
# ---------------------------------------------------------------------------

def test_periodos_disponibles_salen_del_lake(lake):
    assert periodos_disponibles(lake) == ["2026-06", "2026-07"]


def test_valores_de_dimension_ordenados_por_frecuencia(lake):
    assert valores_de_dimension(lake, "transportista") == ["MAE-MAERSK", "CMA-CGM"]


def test_valores_de_dimension_incluye_sin_dato(lake):
    assert SIN_DATO in valores_de_dimension(lake, "pais")


def test_dimensiones_disponibles_esconde_las_columnas_vacias(lake):
    """`ex_aereo` no trae país: no tiene sentido ofrecerlo como dimensión."""
    disponibles = dimensiones_disponibles(lake, filtros={"transportista": ["CMA-CGM"]})

    assert "transportista" in disponibles
    assert "incoterm" not in disponibles


def test_conectar_expone_la_vista_del_lake(lake):
    con = conectar(lake)
    assert con.execute("SELECT count(*) FROM m").fetchone()[0] == 5


def test_conectar_con_lake_inexistente_es_error(tmp_path):
    with pytest.raises(ValueError, match="No hay datos"):
        conectar(tmp_path / "vacio")


def test_agregaciones_declaradas():
    assert set(AGREGACIONES) >= {"suma", "promedio", "conteo"}


def test_la_tabla_cruzada_respeta_los_filtros(lake):
    """Los `?` del cruce y los del WHERE tienen que ir en orden de texto.

    Con los parámetros invertidos la consulta filtraba por el valor de la
    columna cruzada y devolvía cero filas.
    """
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   columna="periodo", filtros={"transportista": ["MAE-MAERSK"]})

    assert df.height == 1
    assert df["Total"][0] == 14
    assert df["2026-06"][0] == 6


def test_la_tabla_cruzada_con_rango_de_periodos(lake):
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"],
                   columna="pais", desde="2026-06", hasta="2026-06")

    assert df["Total"].sum() == 12


def test_las_sumas_enteras_no_vuelven_como_decimal(lake):
    """DuckDB suma BIGINT a DECIMAL(38,0); el formateo de la UI espera números."""
    df = run_pivot(lake, filas=["transportista"], metricas=["teus"])
    assert df["TEUs"].dtype == pl.Int64

    totales = run_totales(lake, metricas=["teus"])
    assert isinstance(totales["TEUs"], int)
