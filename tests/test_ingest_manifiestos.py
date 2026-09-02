"""Tests para src/ingest_manifiestos.py — ingesta de manifiestos de carga."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from src.ingest_manifiestos import (
    CAMPOS_DERIVADOS,
    ManifiestoSource,
    campos_canonicos,
    load_manifiesto_source,
    parse_formato,
    scan_manifiestos_dir,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config_manifiestos.yml"


def _csv(root: Path, nombre: str, filas: dict[str, list]) -> Path:
    """Escribe un CSV con el dialecto real de la fuente: ';' y UTF-8."""
    path = root / nombre
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(filas).write_csv(path, separator=";")
    return path


def _impo_maritimo() -> dict[str, list]:
    return {
        "DIA": [4, 9],
        "MES": [7, 7],
        "AÑO": [2026, 2026],
        "CONSIGNATARIO": ["IMPORTADORA SA", "OTRA SAC"],
        "RUC IMPORTADOR": ["20100028698", "20513481927"],
        "COMPAÑIA DE TRANSPORTE": ["MAE-MAERSK", "CMA-CMA-CGM"],
        "PAIS DE EMBARQUE": ["CHINA", "BRASIL"],
        "PARTIDA ARANCELARIA": ["3808", "604"],
        "PARTIDAS ARANCELARIAS": ["380893", "060420"],
        "DUA": ["10-118-2026-371490", "10-118-2026-369365"],
        "CONOCIMIENTO DE EMBARQUE": ["CHN3387888", "WJ2606046"],
        "FOB": [137003.2, 8229.0],
        "CIF": [142302.2, 14129.0],
        "PESO EN KG BRUTO": [23410.64, 6000.0],
        "TEUS": [2, 2],
        "CONTENEDORES 20": [0, 0],
        "CONTENEDORES 40": [1, 1],
    }


def _expo_maritimo() -> dict[str, list]:
    """Mismo `CONSIGNATARIO` que impo, pero acá es la contraparte extranjera."""
    return {
        "DIA": [10],
        "MES": [7],
        "AÑO": [2026],
        "EMBARCADOR": ["EXPORTADORA PERU SA"],
        "CONSIGNATARIO": ["TROPS IMPORTEXPORT"],
        "COMPAÑIA NAVIERA": ["MAE-MAERSK"],
        "PAIS DE DESEMBARQUE": ["ESPAÑA"],
        "PARTIDA ARANCELARIA": ["804"],
        "PARTIDAS ARANCELARIAS": ['="80440.0"'],
        "DUA": ["40-118-2026-067015"],
        "CONOCIMIENTO DE EMBARQUE": ["MAEU272690247"],
        "FOB": [37987.49],
        "PESO EN KG": [25760.0],
        "TEUS": [2],
        "CONTENEDORES 20": [0],
        "CONTENEDORES 40": [1],
    }


def _expo_aereo() -> dict[str, list]:
    """El formato pobre: sin país, sin contenedores, casi sin FOB."""
    return {
        "DIA": [4],
        "MES": [7],
        "AÑO": [2026],
        "EXPORTADOR": ["INDUSTRIAS NETTALCO S.A."],
        "IMPORTADOR": ["L.L. BEAN INTERNATIONAL"],
        "PAÍS DE DESTINO": [None],
        "AEROLINEA": ["D5 - DHL AERO EXPRESO"],
        "GUÍA HIJA": ["0PE107256926"],
        "PESO EN KG": [136.0],
        "SUBPARTIDA ARANCELARIA": ["610910.0"],
        "PARTIDA ARANCELARIA": ["6109"],
        "DUA": [None],
        "FOB": [None],
    }


def _impo_aereo() -> dict[str, list]:
    return {
        "DÍA": [7],
        "MES": [7],
        "AÑO": [2026],
        "IMPORTADOR": ["FERREYROS SA"],
        "EXPORTADOR": ["No Disponible"],
        "AEROLINEA": ["ZZ- OTRAS"],
        "PAÍS DE ORIGEN": ["ALEMANIA"],
        "GUÍA DE TRANSPORTE": ["0FMO15001597"],
        "DUA": ["10-235-2026-111136"],
        "PARTIDA ARANCELARIA": ["8481"],
        "PARTIDAS ARANCELARIAS": ['="392350,401031"'],
        "FOB": [23743.15],
        "CIF": [25092.04],
        "PESO EN KG": [301.2],
    }


# ---------------------------------------------------------------------------
# parse_formato
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre, esperado", [
    ("20377066635_im_maritimo_2026_7.csv", ("impo", "maritimo")),
    ("20377066635_im_aereo_2026_7.csv", ("impo", "aereo")),
    ("20377066635_ex_maritimo_2026_7.csv", ("expo", "maritimo")),
    # ex_aereo escribe el periodo distinto que el resto; no debe afectar
    ("20377066635_ex_aereo_072026_7.csv", ("expo", "aereo")),
    ("20377066635_EX_AEREO_2026_5.CSV", ("expo", "aereo")),
])
def test_parse_formato_reconoce_las_cuatro_variantes(nombre, esperado):
    assert parse_formato(nombre) == esperado


@pytest.mark.parametrize("nombre", [
    "resumen_2026.csv",
    "20377066635_im_terrestre_2026_7.csv",
    "20377066635_maritimo_2026_7.csv",
])
def test_parse_formato_devuelve_none_si_no_reconoce(nombre):
    assert parse_formato(nombre) is None


# ---------------------------------------------------------------------------
# scan_manifiestos_dir
# ---------------------------------------------------------------------------

def test_scan_encuentra_los_csv_reconocibles(tmp_path):
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    _csv(tmp_path, "x_ex_aereo_072026_7.csv", _expo_aereo())
    _csv(tmp_path, "notas.csv", {"a": [1]})

    fuentes = scan_manifiestos_dir(tmp_path)

    assert [(f.flujo, f.via) for f in fuentes] == [
        ("expo", "aereo"), ("impo", "maritimo"),
    ]
    assert all(isinstance(f, ManifiestoSource) for f in fuentes)


def test_scan_de_carpeta_inexistente_devuelve_lista_vacia(tmp_path):
    assert scan_manifiestos_dir(tmp_path / "no-existe") == []


def test_formato_combina_flujo_y_via():
    fuente = ManifiestoSource(path=Path("x.csv"), flujo="impo", via="maritimo")
    assert fuente.formato == "impo_maritimo"


# ---------------------------------------------------------------------------
# load_manifiesto_source — renombrado por formato
# ---------------------------------------------------------------------------

def test_actor_sale_de_consignatario_en_importacion_maritima(tmp_path):
    p = _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["actor"].to_list() == ["IMPORTADORA SA", "OTRA SAC"]
    assert p.exists()


def test_actor_sale_de_embarcador_en_exportacion_maritima(tmp_path):
    """El mismo `CONSIGNATARIO` es actor en impo y contraparte en expo.

    Es la razón por la que el mapeo es por formato y no por alias global.
    """
    _csv(tmp_path, "x_ex_maritimo_2026_7.csv", _expo_maritimo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["actor"].to_list() == ["EXPORTADORA PERU SA"]
    assert df["contraparte"].to_list() == ["TROPS IMPORTEXPORT"]


def test_transportista_unifica_naviera_y_aerolinea(tmp_path):
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    _csv(tmp_path, "x_ex_aereo_072026_7.csv", _expo_aereo())
    fuentes = {f.formato: f for f in scan_manifiestos_dir(tmp_path)}

    mar = load_manifiesto_source(fuentes["impo_maritimo"], CONFIG_PATH).collect()
    aer = load_manifiesto_source(fuentes["expo_aereo"], CONFIG_PATH).collect()

    assert mar["transportista"][0] == "MAE-MAERSK"
    assert aer["transportista"][0] == "D5 - DHL AERO EXPRESO"


# ---------------------------------------------------------------------------
# load_manifiesto_source — esquema uniforme
# ---------------------------------------------------------------------------

def test_todos_los_formatos_devuelven_el_mismo_esquema(tmp_path):
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    _csv(tmp_path, "x_im_aereo_2026_7.csv", _impo_aereo())
    _csv(tmp_path, "x_ex_maritimo_2026_7.csv", _expo_maritimo())
    _csv(tmp_path, "x_ex_aereo_072026_7.csv", _expo_aereo())

    esquemas = [
        load_manifiesto_source(f, CONFIG_PATH).collect_schema()
        for f in scan_manifiestos_dir(tmp_path)
    ]

    assert all(e == esquemas[0] for e in esquemas)
    esperado = set(campos_canonicos(CONFIG_PATH)) | set(CAMPOS_DERIVADOS)
    assert set(esquemas[0].names()) == esperado


def test_los_cuatro_formatos_se_concatenan_sin_diagonal(tmp_path):
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    _csv(tmp_path, "x_ex_aereo_072026_7.csv", _expo_aereo())

    frames = [
        load_manifiesto_source(f, CONFIG_PATH) for f in scan_manifiestos_dir(tmp_path)
    ]
    combinado = pl.concat(frames, how="vertical").collect()

    assert combinado.height == 3
    assert set(combinado["flujo"].to_list()) == {"impo", "expo"}


def test_columna_ausente_queda_nula_con_su_dtype(tmp_path):
    """expo_aereo no trae contenedores: la métrica existe pero vacía."""
    _csv(tmp_path, "x_ex_aereo_072026_7.csv", _expo_aereo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["teus"].to_list() == [None]
    assert df["teus"].dtype == pl.Int64
    assert df["cif_usd"].dtype == pl.Float64
    assert df["pais"].to_list() == [None]


def test_dtypes_canonicos(tmp_path):
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["fob_usd"].dtype == pl.Float64
    assert df["teus"].dtype == pl.Int64
    assert df["partida_4d"].dtype == pl.String
    assert df["ruc_actor"].dtype == pl.String


# ---------------------------------------------------------------------------
# load_manifiesto_source — campos derivados
# ---------------------------------------------------------------------------

def test_periodo_y_fecha_salen_de_dia_mes_anio(tmp_path):
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", _impo_maritimo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["periodo"].to_list() == ["2026-07", "2026-07"]
    assert df["fecha"].to_list() == [date(2026, 7, 4), date(2026, 7, 9)]
    assert df["fecha"].dtype == pl.Date


def test_periodo_no_se_deriva_del_nombre_de_archivo(tmp_path):
    """ex_aereo escribe `072026` en el nombre; el periodo sale de las columnas."""
    _csv(tmp_path, "x_ex_aereo_072026_7.csv", _expo_aereo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["periodo"].to_list() == ["2026-07"]


def test_flujo_y_via_vienen_de_la_ruta(tmp_path):
    _csv(tmp_path, "x_ex_maritimo_2026_7.csv", _expo_maritimo())
    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["flujo"].to_list() == ["expo"]
    assert df["via"].to_list() == ["maritimo"]


# ---------------------------------------------------------------------------
# Errores explícitos
# ---------------------------------------------------------------------------

def test_formato_desconocido_es_error_explicito(tmp_path):
    fuente = ManifiestoSource(path=tmp_path / "x.csv", flujo="impo", via="terrestre")
    with pytest.raises(ValueError, match="impo_terrestre"):
        load_manifiesto_source(fuente, CONFIG_PATH)


def test_falta_columna_requerida_es_error_explicito(tmp_path):
    filas = _impo_maritimo()
    del filas["AÑO"]
    _csv(tmp_path, "x_im_maritimo_2026_7.csv", filas)

    with pytest.raises(ValueError, match="anio"):
        load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()


def test_campos_canonicos_lee_la_configuracion_real():
    campos = campos_canonicos(CONFIG_PATH)

    assert "fob_usd" in campos
    assert "transportista" in campos
    assert campos["fob_usd"].nivel == "dua"
    assert campos["peso_kg"].nivel == "fila"


def test_enteros_escritos_como_float_no_se_pierden(tmp_path):
    """Mayo escribe los TEUs como `2.0`; un cast directo a Int64 los anula.

    Se detectó porque las importaciones marítimas de 2026-05 sumaban 0 TEUs
    mientras junio y julio sumaban ~130.000.
    """
    filas = _impo_maritimo()
    filas["TEUS"] = ["2.0", "0.0"]
    filas["CONTENEDORES 40"] = ["1.0", "0.0"]
    _csv(tmp_path, "x_im_maritimo_2026_5.csv", filas)

    df = load_manifiesto_source(scan_manifiestos_dir(tmp_path)[0], CONFIG_PATH).collect()

    assert df["teus"].to_list() == [2, 0]
    assert df["cont_40"].to_list() == [1, 0]
    assert df["teus"].dtype == pl.Int64
