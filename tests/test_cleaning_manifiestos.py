"""Tests para src/cleaning_manifiestos.py — normalización de manifiestos.

El caso que da sentido al módulo entero es `prorratear_valor_dua`: una DUA que
consolida varias guías estampa su valor total en cada una de sus filas, así que
sumar la columna tal cual sobrecuenta hasta 22 veces la misma declaración.
"""

import polars as pl
import pytest

from src.cleaning_manifiestos import (
    clean_manifiestos,
    limpiar_texto,
    normalize_hs,
    prorratear_valor_dua,
    quitar_prefijo_codigo,
)


def _lf(**columnas) -> pl.LazyFrame:
    return pl.DataFrame(columnas).lazy()


# ---------------------------------------------------------------------------
# prorratear_valor_dua
# ---------------------------------------------------------------------------

def test_prorrateo_reparte_el_valor_de_la_dua_entre_sus_guias():
    """Caso INGRAM MICRO: una DUA aérea de 3 guías repite su FOB en las 3."""
    lf = _lf(
        dua=["10-235-2026-113318"] * 3,
        fob_usd=[4_281_989.0] * 3,
        peso_kg=[84.8, 542.6, 1415.4],
    )

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["fob_usd"].sum() == pytest.approx(4_281_989.0)
    # cada guía se queda con su parte del peso
    total_peso = 84.8 + 542.6 + 1415.4
    assert out["fob_usd"][0] == pytest.approx(4_281_989.0 * 84.8 / total_peso)
    assert out["fob_usd"][2] == pytest.approx(4_281_989.0 * 1415.4 / total_peso)


def test_prorrateo_no_toca_una_dua_de_una_sola_fila():
    lf = _lf(dua=["A", "B"], fob_usd=[100.0, 250.0], peso_kg=[10.0, 20.0])

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["fob_usd"].to_list() == [100.0, 250.0]


def test_prorrateo_separa_valores_distintos_dentro_de_la_misma_dua():
    """Una DUA puede traer más de un valor declarado; cada uno se conserva."""
    lf = _lf(
        dua=["X", "X", "X"],
        fob_usd=[100.0, 100.0, 60.0],
        peso_kg=[1.0, 3.0, 5.0],
    )

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["fob_usd"].sum() == pytest.approx(160.0)
    assert out["fob_usd"].to_list() == pytest.approx([25.0, 75.0, 60.0])


def test_prorrateo_sin_peso_reparte_en_partes_iguales():
    lf = _lf(dua=["X"] * 4, fob_usd=[800.0] * 4, peso_kg=[0.0, 0.0, None, 0.0])

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["fob_usd"].to_list() == [200.0, 200.0, 200.0, 200.0]


def test_prorrateo_ignora_las_filas_sin_dua():
    """Sin DUA no hay declaración que repartir: el valor queda como vino.

    Agruparlas por el nulo las mezclaría a todas en un solo reparto.
    """
    lf = _lf(dua=[None, None], fob_usd=[100.0, 250.0], peso_kg=[10.0, 20.0])

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["fob_usd"].to_list() == [100.0, 250.0]


def test_prorrateo_conserva_los_nulos():
    lf = _lf(dua=["X", "X"], fob_usd=[None, None], peso_kg=[1.0, 3.0])

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["fob_usd"].to_list() == [None, None]


def test_prorrateo_aplica_a_varias_columnas_a_la_vez():
    lf = _lf(
        dua=["X", "X"],
        fob_usd=[1000.0, 1000.0],
        cif_usd=[1200.0, 1200.0],
        peso_kg=[1.0, 3.0],
    )

    out = prorratear_valor_dua(lf, ["fob_usd", "cif_usd"]).collect()

    assert out["fob_usd"].to_list() == pytest.approx([250.0, 750.0])
    assert out["cif_usd"].to_list() == pytest.approx([300.0, 900.0])


def test_prorrateo_no_altera_las_metricas_de_carga():
    """TEUs y contenedores ya son reales por guía: no se tocan."""
    lf = _lf(
        dua=["X"] * 3,
        fob_usd=[900.0] * 3,
        peso_kg=[1.0, 1.0, 1.0],
        teus=[2, 0, 4],
    )

    out = prorratear_valor_dua(lf, ["fob_usd"]).collect()

    assert out["teus"].to_list() == [2, 0, 4]
    assert out["teus"].sum() == 6


# ---------------------------------------------------------------------------
# normalize_hs
# ---------------------------------------------------------------------------

def test_partida_repone_el_cero_inicial_de_los_capitulos_01_09():
    """`604` es la partida 06.04 (follaje), no la 604."""
    lf = _lf(partida_4d=["604", "3808", None], capitulo=["6", "38", None],
             seccion=["2", "6", None], partidas=[None, None, None])

    out = normalize_hs(lf).collect()

    assert out["partida_4d"].to_list() == ["0604", "3808", None]
    assert out["capitulo"].to_list() == ["06", "38", None]
    assert out["seccion"].to_list() == ["02", "06", None]


def test_partidas_limpia_el_envoltorio_de_excel():
    """ex_maritimo entrega la lista como `="80440.0"`."""
    lf = _lf(partida_4d=[None], capitulo=[None], seccion=[None],
             partidas=['="80440.0"'])

    out = normalize_hs(lf).collect()

    assert out["partidas"].to_list() == ["080440"]
    assert out["n_partidas"].to_list() == [1]
    assert out["multi_partida"].to_list() == [False]


def test_partidas_cuenta_la_lista_separada_por_comas():
    lf = _lf(partida_4d=[None, None], capitulo=[None, None],
             seccion=[None, None],
             partidas=['="392350,401031,401699"', "380893"])

    out = normalize_hs(lf).collect()

    assert out["partidas"].to_list() == ["392350,401031,401699", "380893"]
    assert out["n_partidas"].to_list() == [3, 1]
    assert out["multi_partida"].to_list() == [True, False]


def test_partidas_nula_no_cuenta_como_partida():
    lf = _lf(partida_4d=[None], capitulo=[None], seccion=[None], partidas=[None])

    out = normalize_hs(lf).collect()

    assert out["partidas"].to_list() == [None]
    assert out["n_partidas"].to_list() == [0]
    assert out["multi_partida"].to_list() == [False]


def test_subpartida_suelta_tambien_se_rellena_a_seis():
    """ex_aereo no trae lista: entrega una subpartida como float."""
    lf = _lf(partida_4d=[None], capitulo=[None], seccion=[None],
             partidas=["60420.0"])

    out = normalize_hs(lf).collect()

    assert out["partidas"].to_list() == ["060420"]


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("crudo, esperado", [
    ("  UNIMAR   S.A. ", "UNIMAR S.A."),
    ("YML-YANG MING MARINE TRANSPORT CORPORATION\n", "YML-YANG MING MARINE TRANSPORT CORPORATION"),
    ("No Disponible", None),
    ("No Disponible – Ley 29733", None),
    ("NO DECLARADOS", None),
    ("--", None),
    ("", None),
    ("   ", None),
])
def test_limpiar_texto(crudo, esperado):
    out = _lf(x=[crudo]).select(limpiar_texto(pl.col("x"))).collect()
    assert out["x"].to_list() == [esperado]


@pytest.mark.parametrize("crudo, esperado", [
    ("3306-ALMACENES MUNDO S.A.", "ALMACENES MUNDO S.A."),
    ("7770- TRABAJOS MARITIMOS S.A.", "TRABAJOS MARITIMOS S.A."),
    (" TRANSMERIDIAN S.A.C.", "TRANSMERIDIAN S.A.C."),
    # prefijo alfabético: es el código del transportista, no se toca
    ("MAE-MAERSK", "MAE-MAERSK"),
    # el código es toda la identidad que hay: sin nombre no queda dato
    ("6914-", None),
])
def test_quitar_prefijo_codigo(crudo, esperado):
    out = _lf(x=[crudo]).select(quitar_prefijo_codigo(pl.col("x"))).collect()
    assert out["x"].to_list() == [esperado]


# ---------------------------------------------------------------------------
# clean_manifiestos — orquestación
# ---------------------------------------------------------------------------

def _crudo(**extra) -> pl.LazyFrame:
    base = {
        "dua": ["A", "A"],
        "fob_usd": [1000.0, 1000.0],
        "cif_usd": [1200.0, 1200.0],
        "flete_usd": [None, None],
        "seguro_usd": [None, None],
        "peso_kg": [1.0, 3.0],
        "partida_4d": ["604", "604"],
        "capitulo": ["6", "6"],
        "seccion": ["2", "2"],
        "partidas": ['="60420.0"', '="60420.0"'],
        "almacen": ["3306-ALMACENES MUNDO S.A.", "6914-"],
        "agente_portuario": ["7770- TRABAJOS MARITIMOS S.A.", None],
        "transportista": ["UX- AIR EUROPA", "UX - AIR EUROPA"],
        "actor": ["  ACME   SA ", "No Disponible"],
    }
    base.update(extra)
    return pl.DataFrame(base).lazy()


def test_clean_manifiestos_prorratea_normaliza_y_unifica():
    out = clean_manifiestos(_crudo()).collect()

    assert out["fob_usd"].sum() == pytest.approx(1000.0)
    assert out["cif_usd"].to_list() == pytest.approx([300.0, 900.0])
    assert out["partida_4d"].to_list() == ["0604", "0604"]
    assert out["partidas"].to_list() == ["060420", "060420"]
    assert out["almacen"].to_list() == ["ALMACENES MUNDO S.A.", None]
    assert out["agente_portuario"].to_list() == ["TRABAJOS MARITIMOS S.A.", None]
    assert out["actor"].to_list() == ["ACME SA", None]


def test_clean_manifiestos_unifica_la_grafia_del_transportista():
    """`UX- AIR EUROPA` (impo) y `UX - AIR EUROPA` (expo) son la misma aerolínea.

    Sin unificar, un pivote por transportista la parte en dos filas.
    """
    out = clean_manifiestos(_crudo()).collect()

    assert out["transportista"].n_unique() == 1


def test_clean_manifiestos_no_toca_el_codigo_de_naviera():
    out = clean_manifiestos(_crudo(transportista=["MAE-MAERSK", "CMA-CMA-CGM"])).collect()

    assert out["transportista"].to_list() == ["MAE-MAERSK", "CMA-CMA-CGM"]


def test_clean_manifiestos_es_lazy():
    assert isinstance(clean_manifiestos(_crudo()), pl.LazyFrame)


def test_clean_manifiestos_unifica_el_punto_final_del_transportista():
    """`5Y-ATLAS AIR INC` y `5Y-ATLAS AIR INC.` son la misma aerolínea.

    Quedaban como dos categorías distintas en el lake real.
    """
    out = clean_manifiestos(
        _crudo(transportista=["5Y-ATLAS AIR INC", "5Y - ATLAS AIR INC."])
    ).collect()

    assert out["transportista"].n_unique() == 1
    assert out["transportista"][0] == "5Y-ATLAS AIR INC"
