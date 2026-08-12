"""Tests para src/cleaning_freemium.py — normalización de socios comerciales."""

from datetime import date
from pathlib import Path

import polars as pl

from src.cleaning_freemium import load_partner_config, normalize_partner

CONFIG_PATH = Path(__file__).resolve().parents[1] / "resources" / "partner_aliases.yml"


def _norm(values: list[str | None]) -> list[str]:
    """Normaliza una lista de nombres crudos usando la config real del proyecto."""
    lf = pl.LazyFrame({"partner": pl.Series(values, dtype=pl.String)})
    return normalize_partner(lf, load_partner_config(CONFIG_PATH)).collect()["partner"].to_list()


# ---------------------------------------------------------------------------
# Unificación entre países
# ---------------------------------------------------------------------------

def test_unifies_every_spelling_of_united_states():
    variantes = [
        "Estados Unidos",            # AR, CO
        "ESTADOS UNIDOS",            # BR, MX
        "U.S.A",                     # CL
        "Estados Unidos de América",  # HN
        "ESTADOS UNIDOS DE NORTEAMERICA",  # PA
    ]
    assert set(_norm(variantes)) == {"Estados Unidos"}


def test_unifies_china_variants():
    assert set(_norm(["CHINA", "China", "Republica Popular de China"])) == {"China"}


def test_unifies_south_korea_variants():
    variantes = ["COREA DEL SUR", "Corea del Sur", "COREA (SUR)", "República de Corea"]
    assert set(_norm(variantes)) == {"Corea del Sur"}


def test_unifies_netherlands_variants():
    assert set(_norm(["PAÍSES BAJOS", "Paises Bajos", "HOLANDA"])) == {"Países Bajos"}


def test_case_and_accent_differences_collapse():
    assert set(_norm(["JAPÓN", "Japon", "JAPON", "japón"])) == {"Japón"}


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------

def test_null_partner_becomes_no_declarado():
    assert _norm([None]) == ["No declarado"]


def test_undetermined_country_becomes_no_declarado():
    valores = ["País no determinado", "ORIGEN O DESTINO NO PRECISADO", "Pais desconocido"]
    assert set(_norm(valores)) == {"No declarado"}


def test_free_zones_are_grouped_into_special_regime():
    zonas = [
        "ZONA FRANCA DE BOGOTA",
        "ZFP INTEXZONA S A",
        "Z.F. PUNTA PEREIRA",
        "ZON FRANCA FREY BENTOS BOTNIA",
        "Zona Libre de Colon",
    ]
    assert set(_norm(zonas)) == {"Zona franca / régimen especial"}


def test_named_special_regimes_are_grouped():
    assert _norm(["Area aduanera especial de Tierra del Fuego"]) == [
        "Zona franca / régimen especial"
    ]


def test_real_countries_are_not_swallowed_by_the_zone_pattern():
    assert _norm(["Zambia", "Zimbabwe"]) == ["Zambia", "Zimbabwe"]


def test_unresolved_numeric_codes_become_no_declarado():
    """Algunas fuentes dejan el código de país sin resolver ('042', '781')."""
    assert set(_norm(["042", "781", "7"])) == {"No declarado"}


def test_countries_with_digits_in_the_name_survive():
    assert _norm(["Bosnia y Herzegovina"]) == ["Bosnia y Herzegovina"]


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

def test_uncurated_names_fall_back_to_title_case():
    assert _norm(["BANGLADESH", "guatemala"]) == ["Bangladesh", "Guatemala"]


def test_display_map_restores_accents_and_connectors():
    assert _norm(["TRINIDAD TOBAGO", "COSTA DE MARFIL", "MEXICO"]) == [
        "Trinidad y Tobago",
        "Costa de Marfil",
        "México",
    ]


# ---------------------------------------------------------------------------
# Contrato de eficiencia
# ---------------------------------------------------------------------------

def test_normalize_partner_stays_lazy():
    lf = pl.LazyFrame({"partner": ["CHINA"]})
    assert isinstance(normalize_partner(lf, load_partner_config(CONFIG_PATH)), pl.LazyFrame)


def test_other_columns_are_preserved():
    lf = pl.LazyFrame({"partner": ["CHINA"], "value": [10.0], "hs_code": ["270900"]})
    out = normalize_partner(lf, load_partner_config(CONFIG_PATH)).collect()
    assert out.columns == ["partner", "value", "hs_code"]
    assert out["value"].to_list() == [10.0]


# ---------------------------------------------------------------------------
# Integración con la agregación
# ---------------------------------------------------------------------------

def test_variants_collapse_into_a_single_aggregated_row():
    """El objetivo real: dos grafías del mismo socio suman, no se duplican."""
    from src.ingest_freemium import aggregate_freemium

    lf = pl.LazyFrame({
        "periodo": [date(2025, 1, 1)] * 3,
        "country": ["CL"] * 3,
        "flow": ["impo"] * 3,
        "base_valor": ["CIF"] * 3,
        "hs_code": ["270900"] * 3,
        "partner": ["U.S.A", "Estados Unidos", "ESTADOS UNIDOS DE NORTEAMERICA"],
        "desc_aran": ["Petroleo"] * 3,
        "value": [10.0, 20.0, 30.0],
    })

    result = aggregate_freemium([normalize_partner(lf, load_partner_config(CONFIG_PATH))])

    assert result.height == 1
    assert result["partner"].to_list() == ["Estados Unidos"]
    assert result["value"].to_list() == [60.0]
