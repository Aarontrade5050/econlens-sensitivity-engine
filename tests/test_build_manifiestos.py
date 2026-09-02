"""Tests para build_manifiestos.py — construcción del lake particionado."""

from pathlib import Path

import polars as pl

from build_manifiestos import construir, resumen, vaciar_lake

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config_manifiestos.yml"


def _csv_impo_maritimo(root: Path, nombre: str, mes: int) -> Path:
    path = root / nombre
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "DIA": [4, 9],
        "MES": [mes, mes],
        "AÑO": [2026, 2026],
        "CONSIGNATARIO": ["IMPORTADORA SA", "OTRA SAC"],
        "COMPAÑIA DE TRANSPORTE": ["MAE-MAERSK", "MAE-MAERSK"],
        "PARTIDA ARANCELARIA": ["604", "3808"],
        "CAPITULO ARANCELARIO": ["6", "38"],
        "SECCION ARANCELARIA": ["2", "6"],
        "PARTIDAS ARANCELARIAS": ["060420", "380893"],
        "DUA": ["D-1", "D-1"],
        "FOB": [1000.0, 1000.0],
        "CIF": [1200.0, 1200.0],
        "PESO EN KG BRUTO": [1.0, 3.0],
        "TEUS": ["2.0", "0.0"],
        "CONTENEDORES 20": [0, 0],
        "CONTENEDORES 40": ["1.0", "0.0"],
    }).write_csv(path, separator=";")
    return path


def test_construir_escribe_el_lake_particionado(tmp_path):
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)

    filas = construir(crudos, lake, CONFIG_PATH)

    assert filas == 2
    destino = lake / "periodo=2026-07" / "flujo=impo" / "via=maritimo" / "datos.parquet"
    assert destino.exists()


def test_las_claves_de_particion_no_se_repiten_dentro_del_archivo(tmp_path):
    """El path ya las declara; guardarlas también las duplicaría al leer."""
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)
    construir(crudos, lake, CONFIG_PATH)

    archivo = next(lake.rglob("*.parquet"))
    columnas = pl.read_parquet(archivo).columns

    assert "periodo" not in columnas
    assert "flujo" not in columnas
    assert "via" not in columnas


def test_el_lake_se_lee_con_hive_y_recupera_las_particiones(tmp_path):
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)
    construir(crudos, lake, CONFIG_PATH)

    df = pl.scan_parquet(lake / "**" / "*.parquet", hive_partitioning=True).collect()

    assert df["periodo"].to_list() == ["2026-07", "2026-07"]
    assert df["flujo"].to_list() == ["impo", "impo"]
    assert df["via"].to_list() == ["maritimo", "maritimo"]


def test_el_build_aplica_prorrateo_y_normalizacion(tmp_path):
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)
    construir(crudos, lake, CONFIG_PATH)

    df = pl.read_parquet(next(lake.rglob("*.parquet")))

    # la DUA repetía 1000 en sus dos filas: se reparte, no se duplica
    assert df["fob_usd"].sum() == 1000.0
    assert df["partida_4d"].to_list() == ["0604", "3808"]
    # los TEUs venían como "2.0": deben sobrevivir el cast
    assert df["teus"].sum() == 2


def test_reconstruir_no_acumula_ni_duplica(tmp_path):
    """Correr el build dos veces deja el mismo lake, no el doble."""
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)

    construir(crudos, lake, CONFIG_PATH)
    construir(crudos, lake, CONFIG_PATH)

    df = pl.scan_parquet(lake / "**" / "*.parquet", hive_partitioning=True).collect()
    assert df.height == 2


def test_reconstruir_descarta_los_periodos_que_ya_no_estan(tmp_path):
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_6.csv", 6)
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)
    construir(crudos, lake, CONFIG_PATH)

    (crudos / "x_im_maritimo_2026_6.csv").unlink()
    construir(crudos, lake, CONFIG_PATH)

    df = pl.scan_parquet(lake / "**" / "*.parquet", hive_partitioning=True).collect()
    assert df["periodo"].unique().to_list() == ["2026-07"]


def test_vaciar_lake_borra_parquets_sin_borrar_la_raiz(tmp_path):
    """OneDrive bloquea las carpetas: el vaciado no puede depender de rmtree."""
    lake = tmp_path / "lake"
    crudos = tmp_path / "csv"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)
    construir(crudos, lake, CONFIG_PATH)

    borrados = vaciar_lake(lake)

    assert borrados == 1
    assert list(lake.rglob("*.parquet")) == []


def test_vaciar_lake_inexistente_no_falla(tmp_path):
    assert vaciar_lake(tmp_path / "no-existe") == 0


def test_sin_csv_reconocibles_no_construye_nada(tmp_path):
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    crudos.mkdir()
    (crudos / "notas.csv").write_text("a;b\n1;2", encoding="utf-8")

    assert construir(crudos, lake, CONFIG_PATH) == 0


def test_resumen_reporta_por_particion(tmp_path):
    crudos, lake = tmp_path / "csv", tmp_path / "lake"
    _csv_impo_maritimo(crudos, "x_im_maritimo_2026_7.csv", 7)
    construir(crudos, lake, CONFIG_PATH)

    df = resumen(lake)

    assert df.height == 1
    assert df["filas"][0] == 2
    assert df["fob_usd"][0] == 1000.0
