"""Tests para src/buscador.py — las consultas por entidad del módulo.

El lake de prueba está armado para que las cuentas se puedan verificar a mano:
la entrada marítima suma exactamente 100 TEUs, así que cada participación de
mercado se lee directo del número de TEUs.

Reparto de los 100 TEUs de entrada marítima:

    naviera   MAERSK 40 · MSC 60
    actor     ACME 60 · BETA 10 · GAMMA 10 · A LA ORDEN 10 · MAERSK LINE 10

Los dos últimos son buckets (§4 de docs/manifiestos_metricas.md).
"""

from pathlib import Path

import polars as pl
import pytest

from src.buscador import (
    BUCKETS_ACTOR,
    ROLES,
    es_bucket,
    buscar,
    captura,
    cardinalidad,
    costo_implicito,
    mix,
    oportunidad,
    ranking,
    resumen_cuadrantes,
    serie,
    tramos,
)

# periodo, transportista, actor, agente_aduana, agencia_carga, almacen, pais,
# canal, teus, c20, c40, peso, cif, flete
IMPO_MAR = [
    ("2026-06", "MAERSK", "ACME", "AGA", "EMBARQUE DIRECTO", "DEP1", "CHINA",
     "VERDE", 20, 2, 9, 1000.0, 5000.0, 1000.0),
    ("2026-06", "MAERSK", "BETA", "AGB", "FWD1", "DEP1", "CHINA",
     "ROJO", 10, 0, 5, 500.0, 2500.0, 500.0),
    ("2026-06", "MSC", "ACME", "AGA", "EMBARQUE DIRECTO", "DEP2", "BRASIL",
     "VERDE", 30, 5, 12, 1500.0, None, None),
    ("2026-07", "MAERSK", "ACME", "AGA", "FWD1", "DEP1", "CHINA",
     "VERDE", 10, 1, 4, 400.0, 2000.0, 400.0),
    ("2026-07", "MSC", "GAMMA", None, "EMBARQUE DIRECTO", "DEP2", None,
     None, 10, 0, 5, 400.0, 1000.0, 200.0),
    ("2026-07", "MSC", "A LA ORDEN", "AGB", "FWD1", "DEP2", "CHINA",
     "VERDE", 10, 2, 4, 300.0, 500.0, 100.0),
    ("2026-07", "MSC", "MAERSK LINE PERU S.A.C.", "AGA", "EMBARQUE DIRECTO",
     "DEP1", "CHINA", "VERDE", 10, 0, 5, 200.0, 300.0, 60.0),
]

EXPO_MAR = [
    ("2026-06", "MAERSK", "EXPACME", "AGA", "FWD1", "DEP1", "CHILE",
     None, 50, 5, 22, 2000.0, None, None),
]

IMPO_AEREO = [
    ("2026-06", "LATAM", "ACME", "AGA", "FWD1", "DEP1", "ESPAÑA",
     "VERDE", None, None, None, 200.0, 900.0, 90.0),
]

COLUMNAS = ("transportista", "actor", "agente_aduana", "agencia_carga",
            "almacen", "pais", "canal", "teus", "cont_20", "cont_40",
            "peso_kg", "cif_usd", "flete_usd")


def _escribir(raiz: Path, flujo: str, via: str, filas: list[tuple]) -> None:
    for periodo in sorted({f[0] for f in filas}):
        bloque = [f for f in filas if f[0] == periodo]
        destino = raiz / f"periodo={periodo}" / f"flujo={flujo}" / f"via={via}"
        destino.mkdir(parents=True, exist_ok=True)
        datos = {c: [f[i + 1] for f in bloque] for i, c in enumerate(COLUMNAS)}
        datos["dua"] = [f"{flujo}{via}{periodo}{i}" for i, _ in enumerate(bloque)]
        datos["documento"] = [f"BL{flujo}{periodo}{i}" for i, _ in enumerate(bloque)]
        datos["fob_usd"] = [None] * len(bloque)
        datos["puerto_embarque"] = ["CALLAO"] * len(bloque)
        # Los tipos se declaran aunque la columna venga toda nula: si no, polars
        # la escribe como Null y DuckDB no puede unir ese parquet con los demás
        # (toma el esquema del primero). `build_manifiestos.py` castea igual.
        tipos = {c: pl.String for c in COLUMNAS[:7]}
        tipos.update({
            "teus": pl.Int64, "cont_20": pl.Int64, "cont_40": pl.Int64,
            "peso_kg": pl.Float64, "cif_usd": pl.Float64,
            "flete_usd": pl.Float64, "fob_usd": pl.Float64,
            "dua": pl.String, "documento": pl.String,
            "puerto_embarque": pl.String,
        })
        pl.DataFrame(datos, schema_overrides=tipos).write_parquet(
            destino / "datos.parquet")


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    raiz = tmp_path / "manifiestos"
    _escribir(raiz, "impo", "maritimo", IMPO_MAR)
    _escribir(raiz, "expo", "maritimo", EXPO_MAR)
    _escribir(raiz, "impo", "aereo", IMPO_AEREO)
    return raiz


MAR_IMPO = {"flujo": ["impo"], "via": ["maritimo"]}


# ---------------------------------------------------------------------------
# Catálogo de roles
# ---------------------------------------------------------------------------

def test_los_roles_cubren_la_cadena_logistica():
    """Es lo que este módulo sabe y los otros dos no."""
    for rol in ("actor", "transportista", "agente_aduana", "agencia_carga",
                "almacen", "pais"):
        assert rol in ROLES


def test_cada_rol_declara_una_etiqueta_de_interfaz():
    assert all(r.etiqueta for r in ROLES.values())


# ---------------------------------------------------------------------------
# Resumen de los cuatro cuadrantes — la entrada del buscador
# ---------------------------------------------------------------------------

def test_el_resumen_devuelve_una_fila_por_cuadrante_con_dato(lake):
    df = resumen_cuadrantes(lake)

    assert len(df) == 3
    assert set(zip(df["flujo"], df["via"])) == {
        ("impo", "maritimo"), ("expo", "maritimo"), ("impo", "aereo")}


def test_el_resumen_cuenta_teus_contenedores_y_guias(lake):
    df = resumen_cuadrantes(lake)
    fila = df.filter((pl.col("flujo") == "impo") & (pl.col("via") == "maritimo"))

    assert fila["teus"][0] == 100
    assert fila["contenedores"][0] == 54          # 10 de 20' + 44 de 40'
    assert fila["registros"][0] == 7
    assert fila["actores"][0] == 5


def test_el_resumen_no_inventa_contenedores_en_aereo(lake):
    """El manifiesto aéreo no declara contenedores: es nulo, no cero."""
    df = resumen_cuadrantes(lake)
    fila = df.filter(pl.col("via") == "aereo")

    assert fila["contenedores"][0] is None
    assert fila["teus"][0] is None
    assert fila["peso_kg"][0] == 200.0


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def test_el_ranking_ordena_y_calcula_participacion_de_mercado(lake):
    df = ranking(lake, "transportista", "teus", filtros=MAR_IMPO)

    assert list(df["valor"]) == ["MSC", "MAERSK"]
    assert list(df["teus"]) == [60, 40]
    assert list(df["share"]) == [60.0, 40.0]


def test_el_ranking_agrega_las_cardinalidades_pedidas(lake):
    """«13 navieras, 25 países» de la ficha sale de acá."""
    df = ranking(lake, "actor", "teus", filtros=MAR_IMPO,
                 cardinalidades=("transportista", "pais"))
    acme = df.filter(pl.col("valor") == "ACME")

    assert acme["n_transportista"][0] == 2        # MAERSK y MSC
    assert acme["n_pais"][0] == 2                 # CHINA y BRASIL


def test_el_ranking_de_actores_excluye_los_buckets_si_se_pide(lake):
    df = ranking(lake, "actor", "teus", filtros=MAR_IMPO, excluir_buckets=True)

    assert "A LA ORDEN" not in list(df["valor"])
    assert "MAERSK LINE PERU S.A.C." not in list(df["valor"])
    assert list(df["valor"]) == ["ACME", "BETA", "GAMMA"]


def test_el_denominador_del_share_ignora_la_exclusion_de_buckets(lake):
    """Excluir del listado no borra esa carga del mercado (§3.1).

    ACME mueve 60 de los 100 TEUs del cuadrante. Si el denominador fuese el
    universo ya excluido (80), daría 75% e inflaría a todos.
    """
    df = ranking(lake, "actor", "teus", filtros=MAR_IMPO, excluir_buckets=True)

    assert df.filter(pl.col("valor") == "ACME")["share"][0] == 60.0
    assert sum(df["share"]) == 80.0


def test_el_ranking_respeta_el_tope(lake):
    assert len(ranking(lake, "actor", "teus", filtros=MAR_IMPO, tope=2)) == 2


def test_el_ranking_puede_medir_contenedores(lake):
    """La pregunta original: quién trae más contenedores, no más TEUs."""
    df = ranking(lake, "actor", "contenedores", filtros=MAR_IMPO)
    acme = df.filter(pl.col("valor") == "ACME")

    assert acme["contenedores"][0] == 2 + 9 + 5 + 12 + 1 + 4      # 33 cajas
    assert acme["teus"][0] if "teus" in acme.columns else True


def test_el_ranking_etiqueta_los_nulos(lake):
    df = ranking(lake, "pais", "teus", filtros=MAR_IMPO)

    assert "(sin dato)" in list(df["valor"])


def test_el_ranking_rechaza_una_dimension_desconocida(lake):
    with pytest.raises(ValueError, match="Dimensión desconocida"):
        ranking(lake, "no_existe", "teus", filtros=MAR_IMPO)


# ---------------------------------------------------------------------------
# Buscador
# ---------------------------------------------------------------------------

def test_buscar_encuentra_la_naviera_en_los_dos_cuadrantes(lake):
    df = buscar(lake, "maersk")
    naviera = df.filter(pl.col("rol") == "transportista")

    assert set(naviera["via"]) == {"maritimo"}
    assert set(naviera["flujo"]) == {"impo", "expo"}
    assert naviera.filter(pl.col("flujo") == "impo")["metrica"][0] == 40


def test_buscar_devuelve_la_misma_cadena_en_varios_roles(lake):
    """«maersk» es naviera y además consignataria de su propia carga."""
    roles = set(buscar(lake, "maersk")["rol"])

    assert "transportista" in roles
    assert "actor" in roles


def test_buscar_no_distingue_mayusculas(lake):
    assert len(buscar(lake, "MaErSk")) == len(buscar(lake, "maersk"))


def test_buscar_calcula_la_participacion_dentro_de_su_cuadrante(lake):
    df = buscar(lake, "maersk")
    fila = df.filter((pl.col("rol") == "transportista")
                     & (pl.col("flujo") == "impo"))

    assert fila["share"][0] == 40.0


def test_buscar_usa_peso_como_metrica_en_aereo(lake):
    """El manifiesto aéreo no tiene TEUs: la métrica principal es el peso."""
    df = buscar(lake, "latam")
    fila = df.filter(pl.col("via") == "aereo")

    assert fila["metrica"][0] == 200.0
    assert fila["unidad"][0] == "peso_kg"


def test_buscar_marca_los_buckets(lake):
    df = buscar(lake, "a la orden")

    assert df["bucket"][0] is True


def test_buscar_sin_coincidencias_devuelve_vacio(lake):
    assert buscar(lake, "zzzz").is_empty()


def test_buscar_no_interpola_el_termino_en_el_sql(lake):
    """El término va como parámetro: una comilla no puede romper la consulta."""
    assert buscar(lake, "' OR 1=1 --").is_empty()


# ---------------------------------------------------------------------------
# Participación capturada y oportunidad — la ficha de un operador
# ---------------------------------------------------------------------------

def test_la_captura_compara_contra_el_total_del_cliente(lake):
    """ACME mueve 60 TEUs y 30 van con MAERSK: 50%."""
    df = captura(lake, "transportista", "MAERSK", "teus", filtros=MAR_IMPO)
    acme = df.filter(pl.col("valor") == "ACME")

    assert acme["metrica"][0] == 30
    assert acme["total"][0] == 60
    assert acme["captura"][0] == 50.0


def test_la_captura_llega_a_cien_cuando_el_cliente_es_exclusivo(lake):
    df = captura(lake, "transportista", "MAERSK", "teus", filtros=MAR_IMPO)

    assert df.filter(pl.col("valor") == "BETA")["captura"][0] == 100.0


def test_la_captura_solo_lista_clientes_del_operador(lake):
    df = captura(lake, "transportista", "MAERSK", "teus", filtros=MAR_IMPO)

    assert "GAMMA" not in list(df["valor"])


def test_la_oportunidad_lista_las_cuentas_donde_casi_no_esta(lake):
    """GAMMA mueve 10 TEUs y ninguno con MAERSK."""
    df = oportunidad(lake, "transportista", "MAERSK", "teus",
                     filtros=MAR_IMPO, piso=10, techo=50)

    assert list(df["valor"]) == ["GAMMA"]
    assert df["captura"][0] == 0.0
    assert df["total"][0] == 10


def test_la_oportunidad_respeta_el_piso(lake):
    assert oportunidad(lake, "transportista", "MAERSK", "teus",
                       filtros=MAR_IMPO, piso=999, techo=50).is_empty()


def test_la_oportunidad_excluye_los_buckets(lake):
    """«A LA ORDEN» tiene 0% de MAERSK, pero no es una cuenta que vender."""
    df = oportunidad(lake, "transportista", "MAERSK", "teus",
                     filtros=MAR_IMPO, piso=1, techo=50)

    assert "A LA ORDEN" not in list(df["valor"])


# ---------------------------------------------------------------------------
# Costo implícito
# ---------------------------------------------------------------------------

def test_el_costo_es_razon_de_sumas_y_no_promedio_de_razones(lake):
    """2.260 USD de flete sobre 100 TEUs = 22,6 USD/TEU (§3.5)."""
    c = costo_implicito(lake, filtros=MAR_IMPO)

    assert c["usd_por_teu"] == pytest.approx(22.6)


def test_el_costo_por_kilo_usa_el_peso_del_recorte(lake):
    c = costo_implicito(lake, filtros=MAR_IMPO)

    assert c["usd_por_kg"] == pytest.approx(11300 / 4300, rel=1e-3)


def test_el_costo_informa_su_cobertura(lake):
    """Seis de siete guías declaran flete."""
    c = costo_implicito(lake, filtros=MAR_IMPO)

    assert c["cobertura_flete"] == pytest.approx(85.7, abs=0.1)


def test_el_costo_no_divide_por_cero(lake):
    """En aéreo no hay TEUs: el USD por TEU no existe, no es infinito."""
    c = costo_implicito(lake, filtros={"flujo": ["impo"], "via": ["aereo"]})

    assert c["usd_por_teu"] is None


# ---------------------------------------------------------------------------
# Mix, serie, cardinalidad y tramos
# ---------------------------------------------------------------------------

def test_el_mix_reparte_las_guias_en_porcentaje(lake):
    df = mix(lake, "canal", filtros=MAR_IMPO)
    verde = df.filter(pl.col("valor") == "VERDE")

    assert verde["registros"][0] == 5
    assert verde["pct"][0] == pytest.approx(71.4, abs=0.1)


def test_el_mix_conserva_el_nulo_como_categoria(lake):
    """En canal el nulo significa «no cruzó con una DUA»: es información."""
    df = mix(lake, "canal", filtros=MAR_IMPO)

    assert "(sin dato)" in list(df["valor"])
    assert sum(df["pct"]) == pytest.approx(100.0, abs=0.2)


def test_la_serie_devuelve_un_punto_por_periodo(lake):
    df = serie(lake, "teus", filtros=MAR_IMPO)

    assert list(df["periodo"]) == ["2026-06", "2026-07"]
    assert list(df["teus"]) == [60, 40]


def test_la_serie_agrega_el_share_del_mes(lake):
    """El share de un mes se calcula contra el total de ese mes, no del rango."""
    df = serie(lake, "teus", filtros={**MAR_IMPO, "transportista": ["MAERSK"]},
               share_sobre=MAR_IMPO)

    assert list(df["teus"]) == [30, 10]
    assert list(df["share"]) == [50.0, 25.0]


def test_la_cardinalidad_cuenta_valores_distintos_sin_los_nulos(lake):
    c = cardinalidad(lake, ("transportista", "actor", "pais"), filtros=MAR_IMPO)

    assert c["transportista"] == 2
    assert c["actor"] == 5
    assert c["pais"] == 2


def test_los_tramos_dejan_afuera_lo_excluido(lake):
    """Los tramos se dividen por el mercado completo: el hueco es el bucket."""
    t = tramos(lake, "actor", "teus", filtros=MAR_IMPO, cortes=(1, 3))

    assert t["tramos"][0]["pct"] == 60.0          # ACME
    assert t["tramos"][1]["pct"] == 20.0          # BETA + GAMMA
    assert t["excluido_pct"] == 20.0              # los dos buckets


def test_se_reconocen_las_grafias_reales_de_los_buckets():
    """La fuente escribe lo mismo de muchas formas y todas tienen que caer.

    Salieron de contrastar la consulta contra el lake real: el listado de
    prospección devolvía «TO THE ORDER OF BANCO DE CREDITO DEL PERU» (1.700
    TEUs) y «HAPAG-LLOYD PERU S.A.C.» como si fueran cuentas que visitar.
    """
    assert es_bucket("actor", "A LA ORDEN")
    assert es_bucket("actor", "TO ORDER")
    assert es_bucket("actor", "TO THE ORDER OF BANCO DE CREDITO DEL PERU")
    assert es_bucket("actor", "HAPAG-LLOYD PERU S.A.C.")
    assert es_bucket("actor", "HAPAG-LLOYD ( PERU ) S.A.C.")
    assert es_bucket("actor", "COSCO SHIPPING LINES PERU SA")
    assert not es_bucket("actor", "SUPERMERCADOS PERUANOS SOCIEDAD ANONIMA")
    assert not es_bucket("actor", "ORDERLY LOGISTICS S.A.C.")


def test_el_bucket_depende_del_rol():
    """«EMBARQUE DIRECTO» es un cajón en agencia de carga y nada en actor."""
    assert es_bucket("agencia_carga", "EMBARQUE DIRECTO")
    assert not es_bucket("actor", "EMBARQUE DIRECTO")
    assert es_bucket("transportista", "ZZ-OTRAS")


def test_el_ranking_sin_denominador_da_el_reparto_interno(lake):
    """Filtrando por un importador, el share es sobre su propio total (§3.2).

    ACME mueve 60 TEUs y 30 van con MAERSK: 50%, no el 30% que daría comparar
    contra los 100 TEUs del mercado.
    """
    df = ranking(lake, "transportista", "teus",
                 filtros={**MAR_IMPO, "actor": ["ACME"]})

    assert df.filter(pl.col("valor") == "MAERSK")["share"][0] == 50.0
    assert sum(df["share"]) == pytest.approx(100.0)


def test_el_denominador_explicito_da_participacion_de_mercado(lake):
    """El mismo corte, comparado contra el cuadrante entero (§3.1)."""
    df = ranking(lake, "transportista", "teus",
                 filtros={**MAR_IMPO, "actor": ["ACME"]},
                 denominador=MAR_IMPO)

    assert df.filter(pl.col("valor") == "MAERSK")["share"][0] == 30.0
    assert sum(df["share"]) == 60.0


def test_la_oportunidad_cuenta_operadores_del_mismo_rol(lake):
    """Para una agencia de carga la pregunta es con cuántas agencias trabaja.

    Contar siempre navieras respondía otra pregunta: en la ficha de KUEHNE +
    NAGEL decía «usa 2 navieras», que no dice nada sobre la competencia de esa
    agencia.
    """
    por_agencia = oportunidad(lake, "agencia_carga", "FWD1", "teus",
                              filtros=MAR_IMPO, piso=1, techo=100)
    acme = por_agencia.filter(pl.col("valor") == "ACME")

    # ACME movió con EMBARQUE DIRECTO y con FWD1: dos agencias, no dos navieras.
    assert acme["alternativas"][0] == 2


def test_la_oportunidad_de_una_naviera_sigue_contando_navieras(lake):
    df = oportunidad(lake, "transportista", "MAERSK", "teus",
                     filtros=MAR_IMPO, piso=1, techo=100)
    acme = df.filter(pl.col("valor") == "ACME")

    assert acme["alternativas"][0] == 2          # MAERSK y MSC
