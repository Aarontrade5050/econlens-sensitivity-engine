"""Smoke tests del buscador de manifiestos con el runner de Streamlit.

Ejercitan el render real. Los errores de esta capa son de datos —un nulo
inesperado, una columna que un formato no trae— y no aparecen leyendo el
código ni corriendo tests unitarios.

`expo_aereo` es el caso de borde de este módulo, el equivalente a Bolivia en
freemium: no declara país ni puerto de destino y solo el 6% de sus guías trae
FOB. Todo cambio se prueba también contra él.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.dashboard_manifiestos as dm

APP = Path(__file__).resolve().parents[1] / "src" / "dashboard.py"
LAKE = Path(__file__).resolve().parents[1] / "data" / "manifiestos"

pytestmark = pytest.mark.skipif(
    not (LAKE.is_dir() and any(LAKE.rglob("*.parquet"))),
    reason="falta el lake de manifiestos: correr `python build_manifiestos.py`",
)

ENTRAR = "Entrar al Buscador"


def _abrir() -> AppTest:
    """App ya dentro del módulo de manifiestos."""
    at = AppTest.from_file(str(APP), default_timeout=300).run()
    return next(b for b in at.button if b.label == ENTRAR).click().run()


def _en(at: AppTest, pantalla: str, **estado) -> AppTest:
    """Fija la pantalla y el estado del buscador y vuelve a renderizar.

    Los widgets usan `format_func`, así que el estado se fija con el valor
    interno (`"transportista"`), no con la etiqueta que se ve en pantalla.
    """
    at.session_state["mf_pantalla"] = pantalla
    for clave, valor in estado.items():
        at.session_state[clave] = valor
    return at.run()


def _texto(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def _boton(at: AppTest, etiqueta: str):
    return next(b for b in at.button if b.label == etiqueta)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def test_el_landing_ofrece_el_buscador():
    at = AppTest.from_file(str(APP), default_timeout=300).run()

    assert ENTRAR in [b.label for b in at.button]


def test_entrar_al_buscador_no_revienta():
    at = _abrir()

    assert not at.exception
    assert at.session_state["view_mode"] == "manifiestos"


def test_arranca_mostrando_los_cuatro_manifiestos():
    """La primera decisión es cuál de los cuatro manifiestos se mira."""
    at = _abrir()

    assert not at.exception
    for etiqueta in ("Marítimo · Ingreso", "Marítimo · Salida",
                     "Aéreo · Ingreso", "Aéreo · Salida"):
        assert etiqueta in _texto(at)


def test_sin_escribir_nada_ya_hay_rankings():
    """La entrada no es un formulario vacío: contesta algo de entrada."""
    at = _abrir()

    assert "Sin buscar nada" in _texto(at)
    assert "Ver el ranking completo" in [b.label for b in at.button]


def test_cambiar_de_manifiesto_no_revienta():
    at = _abrir()
    _boton(at, "Ver este manifiesto").click().run()

    assert not at.exception


# ---------------------------------------------------------------------------
# Buscador — el corazón del módulo
# ---------------------------------------------------------------------------

def test_buscar_una_naviera_la_encuentra_en_varios_roles():
    """«maersk» es naviera, agente, agencia, consignataria y almacén."""
    at = _en(_abrir(), "buscador", mf_q="maersk")

    assert not at.exception
    texto = _texto(at)
    assert "coincidencias en" in texto
    assert "Navieras / Aerolíneas" in texto
    assert "Agentes de aduana" in texto


def test_el_resultado_no_muestra_la_flecha_como_si_fuera_una_variacion():
    """Cada recuadro nombra su manifiesto; el porcentaje no es un delta."""
    at = _en(_abrir(), "buscador", mf_q="maersk")

    assert "no una variación" in _texto(at)


def test_buscar_marca_los_consignatarios_genericos():
    at = _en(_abrir(), "buscador", mf_q="a la orden")

    assert not at.exception
    assert "No es una empresa" in _texto(at)


def test_buscar_algo_que_no_existe_avisa_en_vez_de_fallar():
    at = _en(_abrir(), "buscador", mf_q="zzzzzzzz")

    assert not at.exception
    assert at.info


def test_una_comilla_en_la_busqueda_no_rompe_la_consulta():
    """El término va como parámetro, nunca interpolado en el SQL."""
    at = _en(_abrir(), "buscador", mf_q="' OR 1=1 --")

    assert not at.exception


# ---------------------------------------------------------------------------
# Ficha
# ---------------------------------------------------------------------------

def test_la_ficha_de_un_importador_muestra_con_quien_trabaja():
    at = _en(_abrir(), "buscador",
             mf_ficha=("actor", "SUPERMERCADOS PERUANOS SOCIEDAD ANONIMA"))

    assert not at.exception
    texto = _texto(at)
    assert "Con quién trabaja" in texto
    assert "Navieras / Aerolíneas" in texto
    assert "Cómo se movió mes a mes" in texto


def test_la_ficha_de_una_naviera_muestra_la_captura_de_cada_cliente():
    """La columna más accionable: cuánto de cada cliente ya tiene."""
    at = _en(_abrir(), "buscador", mf_ficha=("transportista", "MAE-MAERSK"))

    assert not at.exception
    texto = _texto(at)
    assert "Sus clientes" in texto
    assert "Total del cliente" in texto
    assert "Cuentas donde no está" in texto


def test_la_ficha_dice_cuanto_pesa_en_su_mercado():
    at = _en(_abrir(), "buscador", mf_ficha=("transportista", "MAE-MAERSK"))

    assert "del manifiesto" in _texto(at)


def test_volver_desde_la_ficha_no_revienta():
    at = _en(_abrir(), "buscador", mf_ficha=("transportista", "MAE-MAERSK"))
    _boton(at, "← Volver").click().run()

    assert not at.exception
    assert at.session_state["mf_ficha"] is None


def test_una_entidad_que_no_existe_no_rompe_la_ficha():
    at = _en(_abrir(), "buscador", mf_ficha=("actor", "NO EXISTE S.A.C."))

    assert not at.exception


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def test_el_ranking_de_importadores_por_contenedores():
    """La pregunta original: quién es el que trae más contenedores."""
    at = _en(_abrir(), "rankings", mf_rank_dim="actor",
             mf_rank_met="contenedores")

    assert not at.exception
    texto = _texto(at)
    assert "Importadores / Exportadores por contenedores" in texto
    assert "Cómo se reparte el mercado" in texto
    assert "Costo implícito del mercado" in texto


@pytest.mark.parametrize("dimension", ["transportista", "agente_aduana",
                                       "agencia_carga", "almacen", "pais"])
def test_cada_eslabon_de_la_cadena_se_puede_rankear(dimension):
    at = _en(_abrir(), "rankings", mf_rank_dim=dimension, mf_rank_met="teus")

    assert not at.exception


def test_el_ranking_excluye_las_navieras_del_listado_de_importadores():
    at = _en(_abrir(), "rankings", mf_rank_dim="actor",
             mf_rank_met="contenedores", mf_rank_excluir=True)

    texto = _texto(at)
    assert "MAERSK LINE PERU S.A.C." not in texto
    assert "A LA ORDEN" not in texto


def test_el_hueco_de_los_excluidos_se_muestra_aparte():
    """Los porcentajes no suman 100 y el diseño explica por qué (§3.1)."""
    at = _en(_abrir(), "rankings", mf_rank_dim="actor",
             mf_rank_met="contenedores", mf_rank_excluir=True)

    assert "Navieras y «a la orden»" in _texto(at)


# ---------------------------------------------------------------------------
# Tabla dinámica
# ---------------------------------------------------------------------------

def test_la_tabla_arranca_dibujada():
    at = _en(_abrir(), "tabla")

    assert not at.exception
    assert "Total de la selección" in _texto(at)


def test_tres_dimensiones_y_tres_metricas():
    """El criterio de éxito del checkpoint original, que sigue valiendo."""
    at = _en(_abrir(), "tabla", mf_filas=["pais", "partida_4d", "canal"],
             mf_metricas=["cif_usd", "peso_kg", "registros"],
             mf_flujo="impo", mf_via="maritimo")

    assert not at.exception
    texto = _texto(at)
    for encabezado in ("País", "Partida (4 díg.)", "Canal", "CIF (USD)",
                       "Peso (kg)", "Guías / BL"):
        assert f">{encabezado}</th>" in texto


def test_la_tabla_puede_medir_contenedores():
    at = _en(_abrir(), "tabla", mf_filas=["transportista"],
             mf_metricas=["contenedores"], mf_flujo="impo", mf_via="maritimo")

    assert not at.exception
    assert ">Contenedores</th>" in _texto(at)
    df = dm._pivote(("transportista",), ("contenedores",), None,
                    (("flujo", ("impo",)), ("via", ("maritimo",))),
                    at.session_state["mf_desde"], at.session_state["mf_hasta"])
    assert df["Contenedores"].sum() > 0


def test_la_tabla_cruzada_abre_los_periodos_en_columnas():
    at = _en(_abrir(), "tabla", mf_filas=["transportista"],
             mf_metricas=["teus"], mf_columna="periodo", mf_via="maritimo")

    assert not at.exception
    texto = _texto(at)
    assert ">Naviera / Aerolínea</th>" in texto
    assert ">Total</th>" in texto
    assert ">2026-07</th>" in texto


def test_la_tabla_cruzada_no_lleva_fila_de_total():
    """Cruzada, cada columna es un valor: una fila de total no cerraría nada."""
    at = _en(_abrir(), "tabla", mf_filas=["transportista"],
             mf_metricas=["teus"], mf_columna="periodo", mf_via="maritimo")

    assert "Total de la selección" not in _texto(at)


def test_sin_dimensiones_pide_elegir_en_vez_de_fallar():
    at = _en(_abrir(), "tabla", mf_filas=[], mf_metricas=["teus"])

    assert not at.exception
    assert at.info
    assert not at.dataframe


def test_el_filtro_heredado_de_una_ficha_se_puede_quitar():
    """Venir de una ficha precarga un filtro, no restringe la tabla."""
    at = _en(_abrir(), "tabla", mf_heredado=("transportista", "MAE-MAERSK"))

    assert "Vienes de la ficha de MAE-MAERSK" in _texto(at)
    _boton(at, "Quitar filtro").click().run()

    assert not at.exception
    assert at.session_state["mf_heredado"] is None


def test_la_tabla_aclara_que_se_agrupa_por_cualquier_campo():
    at = _en(_abrir(), "tabla")

    assert "no solo por naviera" in _texto(at)


# ---------------------------------------------------------------------------
# Periodo
# ---------------------------------------------------------------------------

def test_un_rango_de_periodos_invertido_avisa_en_vez_de_fallar():
    """Nada impide elegir un `desde` posterior al `hasta`: no puede reventar."""
    at = _en(_abrir(), "buscador", mf_desde="2026-07", mf_hasta="2026-05")

    assert not at.exception
    assert at.warning


# ---------------------------------------------------------------------------
# expo_aereo — el caso de borde
# ---------------------------------------------------------------------------

def test_exportacion_aerea_renderiza_el_buscador():
    at = _en(_abrir(), "buscador", mf_flujo="expo", mf_via="aereo")

    assert not at.exception


def test_exportacion_aerea_renderiza_el_ranking():
    at = _en(_abrir(), "rankings", mf_flujo="expo", mf_via="aereo",
             mf_rank_dim="transportista", mf_rank_met="peso_kg")

    assert not at.exception


def test_exportacion_aerea_no_ofrece_pais_ni_puerto():
    """No los declara: ofrecerlos sería ofrecer una tabla de un solo `(sin dato)`."""
    at = _en(_abrir(), "tabla", mf_flujo="expo", mf_via="aereo")

    disponibles = dm._dimensiones(
        (("flujo", ("expo",)), ("via", ("aereo",))),
        at.session_state["mf_desde"], at.session_state["mf_hasta"])
    assert "pais" not in disponibles
    assert "puerto_desembarque" not in disponibles
    assert "transportista" in disponibles


def test_exportacion_aerea_no_ofrece_teus_ni_contenedores():
    """El manifiesto aéreo no declara contenedores: la métrica no existe."""
    medibles = dm._metricas(
        (("flujo", ("expo",)), ("via", ("aereo",))), "2026-05", "2026-07")

    assert "teus" not in medibles
    assert "contenedores" not in medibles
    assert "peso_kg" in medibles


def test_exportacion_aerea_con_fob_avisa_la_cobertura():
    """Su FOB cubre ~6% de las guías: el total no es la exportación del país."""
    at = _en(_abrir(), "tabla", mf_flujo="expo", mf_via="aereo",
             mf_filas=["transportista"], mf_metricas=["fob_usd"])

    assert not at.exception
    assert "existe en el" in _texto(at)


def test_importacion_maritima_no_avisa_cobertura_de_peso():
    """El aviso es para el valor; el peso está en todas las guías."""
    at = _en(_abrir(), "tabla", mf_flujo="impo", mf_via="maritimo",
             mf_filas=["transportista"], mf_metricas=["peso_kg", "teus"])

    assert "existe en el" not in _texto(at)


# ---------------------------------------------------------------------------
# Estado vacío (el caso de Streamlit Cloud, sin lake)
# ---------------------------------------------------------------------------

def test_sin_lake_muestra_el_estado_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "LAKE", tmp_path / "sin-lake")

    at = _abrir()

    assert not at.exception
    assert not at.dataframe
    assert "build_manifiestos.py" in _texto(at)


def test_hay_datos_detecta_el_lake():
    assert dm.hay_datos(LAKE)


def test_hay_datos_es_falso_sin_parquets(tmp_path):
    assert not dm.hay_datos(tmp_path)


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

def test_cada_columna_se_formatea_con_la_unidad_de_su_metrica():
    assert dm._metrica_de_columna("CIF (USD)", ["cif_usd", "teus"], False) == "cif_usd"
    assert dm._metrica_de_columna("TEUs", ["cif_usd", "teus"], False) == "teus"
    assert "$" in dm._valor("cif_usd", 1_500_000)
    assert "$" not in dm._valor("teus", 1500)


def test_la_tabla_cruzada_de_una_metrica_hereda_su_formato():
    """Las columnas se llaman `2026-06`, no `CIF (USD)`: el formato es de la métrica."""
    assert dm._metrica_de_columna("2026-06", ["cif_usd"], True) == "cif_usd"
    assert dm._metrica_de_columna("2026-06", ["teus"], True) == "teus"


def test_el_nulo_se_muestra_como_raya_y_no_como_cero():
    """El aéreo no tiene contenedores: mostrar 0 sería inventar un dato."""
    assert dm._valor("contenedores", None) == "—"
    assert dm._valor("teus", 0) == "0"


# ---------------------------------------------------------------------------
# Diseño: chips de la búsqueda y navegación a la ficha
# ---------------------------------------------------------------------------

def test_el_buscador_ofrece_los_chips_de_tipo_de_entidad():
    """Están en el diseño y acotan la búsqueda a un rol."""
    at = _abrir()
    chips = next(r for r in at.radio if r.key == "mf_chip")

    assert chips.options[:4] == ["Todo", "Importadores", "Navieras",
                                 "Agentes de aduana"]
    assert "Almacenes" in chips.options
    assert "Puertos" in chips.options


def test_el_chip_acota_la_busqueda_a_un_rol():
    at = _en(_abrir(), "buscador", mf_q="maersk", mf_chip="transportista")

    assert not at.exception
    texto = _texto(at)
    assert "Navieras / Aerolíneas" in texto
    assert "Agentes de aduana" not in texto


def test_un_chip_sin_coincidencias_avisa_con_su_nombre():
    at = _en(_abrir(), "buscador", mf_q="maersk", mf_chip="pais")

    assert at.info
    assert "países" in at.info[0].value


def test_cada_fila_del_ranking_lleva_a_su_ficha():
    """La navegación no está en un selector aparte: está en la fila."""
    at = _en(_abrir(), "rankings", mf_rank_dim="transportista",
             mf_rank_met="teus")
    fichas = [b for b in at.button if b.label == "Ver ficha"]

    assert len(fichas) >= 5
    fichas[0].click().run()

    assert not at.exception
    assert at.session_state["mf_ficha"][0] == "transportista"


def test_la_tabla_no_usa_la_grilla_nativa():
    """La grilla se pinta sobre un canvas y toma el tema oscuro del Motor ISE."""
    at = _en(_abrir(), "tabla")

    assert not at.dataframe


# ---------------------------------------------------------------------------
# Render del HTML propio
# ---------------------------------------------------------------------------

def test_el_html_no_se_filtra_como_texto_en_la_ficha():
    """Markdown lee cuatro espacios como bloque de código.

    «Cuentas donde no está» se mostraba como HTML crudo porque su cuerpo
    empezaba con un salto de línea y catorce espacios de sangría.
    """
    at = _en(_abrir(), "buscador",
             mf_ficha=("agencia_carga", "KUEHNE + NAGEL S.A."))

    assert not at.exception
    texto = _texto(at)
    assert "Cuentas donde no está" in texto
    assert "&lt;div" not in texto
    assert "\n              <div" not in texto


def test_ninguna_pantalla_deja_html_indentado():
    """El normalizador aplana todo lo que sale por `_md`."""
    assert "<div" in dm._html_plano('\n    <div class="x">a</div>')
    assert "\n" not in dm._html_plano('<div>\n      <span>a</span>\n</div>')


def test_el_ranking_muestra_las_columnas_del_diseno():
    at = _en(_abrir(), "rankings", mf_rank_dim="actor",
             mf_rank_met="contenedores")
    texto = _texto(at)

    for encabezado in ("Contenedores", "TEUs", "BL", "Navieras", "Países",
                       "CIF", "Participación"):
        assert encabezado in texto


def test_las_columnas_del_ranking_dependen_del_manifiesto():
    """El aéreo no tiene contenedores; el ranking de navieras no cuenta navieras."""
    maritimo = dict(dm._columnas_ranking(
        "impo", "maritimo", "actor", ["contenedores", "teus", "cif_usd"],
        ["transportista", "pais"]))
    aereo = dict(dm._columnas_ranking(
        "expo", "aereo", "transportista", ["peso_kg"], ["pais"]))

    assert "contenedores" in maritimo and "n_transportista" in maritimo
    assert "contenedores" not in aereo and "peso_kg" in aereo
    assert "n_actor" in aereo and "n_transportista" not in aereo


def test_el_puerto_se_nombra_segun_el_flujo():
    """En una exportación el puerto de embarque es peruano: no dice nada."""
    assert dm._dim_puerto("impo") == ("puerto_embarque", "De qué puerto viene")
    assert dm._dim_puerto("expo") == ("puerto_desembarque", "A qué puerto va")
    assert dm._dim_pais("impo")[1] == "De qué país viene"
    assert dm._dim_pais("expo")[1] == "A qué país va"


def test_la_tabla_ofrece_las_tres_acciones_del_pie():
    """Están dibujadas y deshabilitadas: no tienen funcionalidad todavía."""
    at = _en(_abrir(), "tabla")
    acciones = [b for b in at.button if b.label.startswith(("Ver estas", "Guardar", "Descargar"))]

    assert len(acciones) == 3
    assert all(b.disabled for b in acciones)


def test_el_ranking_va_dentro_de_una_tarjeta_con_su_titulo():
    """El fondo blanco y el título a la izquierda, como el resto del módulo.

    Una tarjeta escrita a mano no puede contener widgets: los botones «Ver
    ficha» quedaban fuera del fondo. Va con `st.container(key=...)`, que deja
    la clase que el CSS del tema pinta.
    """
    at = _en(_abrir(), "rankings", mf_rank_dim="actor",
             mf_rank_met="contenedores")

    assert not at.exception
    assert "Importadores / Exportadores por contenedores" in _texto(at)


def test_la_tabla_dinamica_titula_el_cruce_que_se_armo():
    """«Naviera / Aerolínea × País», como en el diseño."""
    at = _en(_abrir(), "tabla", mf_filas=["transportista", "pais"],
             mf_metricas=["contenedores"], mf_flujo="impo", mf_via="maritimo")

    texto = _texto(at)
    assert "Naviera / Aerolínea × País" in texto
    assert "los nulos se agrupan como" in texto


def test_el_titulo_de_la_tabla_nombra_tambien_el_cruce_en_columnas():
    at = _en(_abrir(), "tabla", mf_filas=["transportista"],
             mf_metricas=["teus"], mf_columna="periodo", mf_via="maritimo")

    assert "Naviera / Aerolínea × Periodo" in _texto(at)
