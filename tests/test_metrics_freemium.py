"""Tests para src/metrics_freemium.py — métricas de la capa freemium.

Todas las métricas se calculan solo sobre `value`: la fuente estadística no
trae cantidad ni unidad de medida, por lo que no hay precio unitario.
"""

from datetime import date

import polars as pl
import pytest

from src.metrics_freemium import (
    NO_IDENTIFICADOS,
    compute_country_yearly,
    compute_hhi,
    compute_hs_yearly,
    compute_monthly_by_country,
    compute_monthly_by_hs,
    compute_partner_by_country,
    compute_partner_share,
    compute_registros,
    concentracion_relevante,
)


def _base(rows: list[dict]) -> pl.LazyFrame:
    """Construye una base freemium mínima con valores por defecto sensatos."""
    defaults = {
        "country": "CL",
        "flow": "impo",
        "base_valor": "CIF",
        "hs_code": "270900",
        "partner": "China",
        "desc_aran": "Petroleo crudo",
        "periodo": date(2025, 1, 1),
        "value": 100.0,
    }
    return pl.LazyFrame([{**defaults, **r} for r in rows])


# ---------------------------------------------------------------------------
# compute_country_yearly
# ---------------------------------------------------------------------------

def test_country_yearly_computes_yoy_growth():
    base = _base([
        {"periodo": date(2024, 3, 1), "value": 100.0},
        {"periodo": date(2025, 3, 1), "value": 150.0},
    ])
    out = compute_country_yearly(base).collect().sort("anio")

    assert out["value"].to_list() == [100.0, 150.0]
    assert out["yoy_pct"].to_list() == [None, 50.0]


def test_country_yearly_yoy_is_null_without_base_year():
    """PA y UY solo tienen 2025: el YoY debe ser nulo, no cero ni infinito."""
    base = _base([{"country": "PA", "periodo": date(2025, 5, 1), "value": 80.0}])
    out = compute_country_yearly(base).collect()

    assert out["yoy_pct"].to_list() == [None]


def test_country_yearly_never_mixes_flows():
    base = _base([
        {"flow": "impo", "base_valor": "CIF", "value": 100.0},
        {"flow": "expo", "base_valor": "FOB", "value": 40.0},
    ])
    out = compute_country_yearly(base).collect().sort("flow")

    assert out["flow"].to_list() == ["expo", "impo"]
    assert out["value"].to_list() == [40.0, 100.0]


# ---------------------------------------------------------------------------
# compute_hs_yearly
# ---------------------------------------------------------------------------

def test_hs_yearly_groups_by_product_and_carries_description():
    base = _base([
        {"hs_code": "270900", "desc_aran": "Petroleo crudo", "value": 100.0},
        {"hs_code": "854231", "desc_aran": "Procesadores", "value": 60.0},
    ])
    out = compute_hs_yearly(base).collect().sort("hs_code")

    assert out["hs_code"].to_list() == ["270900", "854231"]
    assert out["desc_aran"].to_list() == ["Petroleo crudo", "Procesadores"]


def test_hs_yearly_yoy_is_null_for_products_absent_in_prior_year():
    base = _base([
        {"hs_code": "270900", "periodo": date(2024, 1, 1), "value": 200.0},
        {"hs_code": "270900", "periodo": date(2025, 1, 1), "value": 100.0},
        {"hs_code": "854231", "periodo": date(2025, 1, 1), "value": 50.0},
    ])
    out = compute_hs_yearly(base).collect().filter(pl.col("anio") == 2025).sort("hs_code")

    assert out["yoy_pct"].to_list() == [-50.0, None]


# ---------------------------------------------------------------------------
# compute_partner_share
# ---------------------------------------------------------------------------

def test_partner_shares_sum_to_one_hundred():
    base = _base([
        {"partner": "China", "value": 75.0},
        {"partner": "Brasil", "value": 25.0},
    ])
    out = compute_partner_share(base).collect()

    assert out["share_pct"].sum() == pytest.approx(100.0)
    assert dict(zip(out["partner"], out["share_pct"])) == pytest.approx(
        {"China": 75.0, "Brasil": 25.0}
    )


def test_partner_share_delta_in_percentage_points():
    base = _base([
        {"partner": "China", "periodo": date(2024, 1, 1), "value": 50.0},
        {"partner": "Brasil", "periodo": date(2024, 1, 1), "value": 50.0},
        {"partner": "China", "periodo": date(2025, 1, 1), "value": 80.0},
        {"partner": "Brasil", "periodo": date(2025, 1, 1), "value": 20.0},
    ])
    out = compute_partner_share(base).collect().filter(pl.col("anio") == 2025)

    assert dict(zip(out["partner"], out["delta_pp"])) == pytest.approx(
        {"China": 30.0, "Brasil": -30.0}
    )


def test_partner_share_delta_is_null_without_base_year():
    base = _base([{"partner": "China", "periodo": date(2025, 1, 1)}])
    out = compute_partner_share(base).collect()

    assert out["delta_pp"].to_list() == [None]


def test_partner_share_can_be_limited_to_relevant_partidas():
    base = _base([
        {"hs_code": "270900", "partner": "China", "value": 80_000_000.0},
        {"hs_code": "999999", "partner": "China", "value": 1_000.0},
    ])
    out = compute_partner_share(base, compute_hs_yearly(base)).collect()

    assert out["hs_code"].unique().to_list() == ["270900"]


def test_partner_by_country_covers_all_partidas():
    """El ranking país suma todo, incluidas las partidas marginales."""
    base = _base([
        {"hs_code": "270900", "partner": "China", "value": 75.0},
        {"hs_code": "999999", "partner": "Brasil", "value": 25.0},
    ])
    out = compute_partner_by_country(base).collect()

    assert "hs_code" not in out.columns
    assert dict(zip(out["partner"], out["share_pct"])) == pytest.approx(
        {"China": 75.0, "Brasil": 25.0}
    )


# ---------------------------------------------------------------------------
# compute_hhi
# ---------------------------------------------------------------------------

def test_hhi_of_a_single_partner_is_ten_thousand():
    out = compute_hhi(_base([{"partner": "China", "value": 100.0}])).collect()

    assert out["hhi"].to_list() == [10000.0]
    assert out["n_socios"].to_list() == pytest.approx([1.0])
    assert out["categoria"].to_list() == ["1 socio dominante"]


def test_effective_partners_is_the_inverse_of_hhi():
    """4 socios iguales equivalen exactamente a 4 socios efectivos."""
    base = _base([{"partner": p, "value": 25.0} for p in "ABCD"])
    out = compute_hhi(base).collect()

    assert out["hhi"].to_list() == pytest.approx([2500.0])
    assert out["n_socios"].to_list() == pytest.approx([4.0])
    assert out["categoria"].to_list() == ["4-6 socios"]


def test_ten_equal_partners_read_as_diversified():
    base = _base([{"partner": str(i), "value": 10.0} for i in range(10)])
    out = compute_hhi(base).collect()

    assert out["n_socios"].to_list() == pytest.approx([10.0])
    assert out["categoria"].to_list() == ["Diversificado"]


def test_dominant_partner_reads_as_one_supplier():
    """90/5/5: aunque haya tres socios, el mercado depende de uno."""
    base = _base([
        {"partner": "China", "value": 90.0},
        {"partner": "Brasil", "value": 5.0},
        {"partner": "Peru", "value": 5.0},
    ])
    out = compute_hhi(base).collect()

    assert out["n_socios"].to_list() == pytest.approx([1.22], abs=0.01)
    assert out["categoria"].to_list() == ["1 socio dominante"]


def test_two_equal_partners_read_as_few_suppliers():
    base = _base([{"partner": "China", "value": 50.0}, {"partner": "Brasil", "value": 50.0}])
    out = compute_hhi(base).collect()

    assert out["n_socios"].to_list() == pytest.approx([2.0])
    assert out["categoria"].to_list() == ["2-3 socios"]


# ---------------------------------------------------------------------------
# Cambio de concentración — el orden de la pantalla
# ---------------------------------------------------------------------------

def test_delta_socios_captures_origin_substitution():
    """De 4 socios iguales en 2024 a uno solo en 2025: pierde 3 socios."""
    base = _base(
        [{"partner": p, "value": 25.0, "periodo": date(2024, 1, 1)} for p in "ABCD"]
        + [{"partner": "A", "value": 100.0, "periodo": date(2025, 1, 1)}]
    )
    out = compute_hhi(base).collect().sort("anio")

    assert out["n_socios"].to_list() == pytest.approx([4.0, 1.0])
    assert out["delta_socios"].to_list() == pytest.approx([None, -3.0])


def test_delta_socios_is_null_without_base_year():
    base = _base([{"partner": "China", "periodo": date(2025, 1, 1)}])
    out = compute_hhi(base).collect()

    assert out["delta_socios"].to_list() == [None]


def test_hhi_reports_top_partner_and_top3_share():
    base = _base([
        {"partner": "China", "value": 50.0},
        {"partner": "Brasil", "value": 30.0},
        {"partner": "Peru", "value": 15.0},
        {"partner": "Chile", "value": 5.0},
    ])
    out = compute_hhi(base).collect()

    assert out["top_partner"].to_list() == ["China"]
    assert out["top_partner_pct"].to_list() == pytest.approx([50.0])
    assert out["top3_pct"].to_list() == pytest.approx([95.0])


def test_hhi_excludes_unidentified_partners_but_reports_coverage():
    """'No declarado' no es un proveedor: incluirlo inventaría concentración."""
    base = _base([
        {"partner": "China", "value": 40.0},
        {"partner": "Brasil", "value": 40.0},
        {"partner": NO_IDENTIFICADOS[0], "value": 20.0},
    ])
    out = compute_hhi(base).collect()

    # HHI sobre los identificados: 50/50 -> 5000, no 40/40/20 -> 4800
    assert out["hhi"].to_list() == pytest.approx([5000.0])
    assert out["cobertura_pct"].to_list() == pytest.approx([80.0])


def test_hhi_is_null_when_no_partner_is_identified():
    base = _base([{"partner": lbl, "value": 50.0} for lbl in NO_IDENTIFICADOS])
    out = compute_hhi(base).collect()

    assert out["hhi"].to_list() == [None]
    assert out["n_socios"].to_list() == [None]
    assert out["categoria"].to_list() == [None]
    assert out["cobertura_pct"].to_list() == pytest.approx([0.0])


# ---------------------------------------------------------------------------
# concentracion_relevante
# ---------------------------------------------------------------------------

def test_relevant_concentration_drops_small_partidas():
    base = _base([
        {"hs_code": "270900", "partner": "China", "value": 80_000_000.0},
        {"hs_code": "999999", "partner": "China", "value": 1_000.0},
    ])
    out = concentracion_relevante(compute_hhi(base), compute_hs_yearly(base)).collect()

    assert out["hs_code"].to_list() == ["270900"]


def test_relevant_concentration_leads_with_the_biggest_supplier_loss():
    """Arriba va la partida que más sustituyó origen, no la más concentrada."""
    dos_anios = lambda hs, socios, anio: [  # noqa: E731
        {"hs_code": hs, "partner": p, "value": 80_000_000.0, "periodo": date(anio, 1, 1)}
        for p in socios
    ]
    base = _base(
        dos_anios("111111", "ABCD", 2024) + dos_anios("111111", "A", 2025)
        + dos_anios("222222", "AB", 2024) + dos_anios("222222", "AB", 2025)
    )
    out = concentracion_relevante(compute_hhi(base), compute_hs_yearly(base)).collect()

    assert out.filter(pl.col("anio") == 2025)["hs_code"].to_list() == ["111111", "222222"]


# ---------------------------------------------------------------------------
# Series mensuales
# ---------------------------------------------------------------------------

def test_monthly_by_hs_keeps_one_row_per_month():
    base = _base([
        {"periodo": date(2025, 1, 1), "value": 10.0},
        {"periodo": date(2025, 1, 1), "partner": "Brasil", "value": 5.0},
        {"periodo": date(2025, 2, 1), "value": 20.0},
    ])
    out = compute_monthly_by_hs(base).collect().sort("periodo")

    assert out.height == 2
    assert out["value"].to_list() == [15.0, 20.0]


def test_registros_carries_monthly_partner_weight():
    base = _base([
        {"partner": "China", "value": 75_000_000.0},
        {"partner": "Brasil", "value": 25_000_000.0},
    ])
    out = compute_registros(base, compute_hs_yearly(base)).collect()

    assert out["partner"].to_list() == ["China", "Brasil"]
    assert out["share_mes"].to_list() == pytest.approx([75.0, 25.0])


def test_registros_exposes_no_actor_identity():
    base = _base([{"partner": "China", "value": 80_000_000.0}])
    out = compute_registros(base, compute_hs_yearly(base)).collect()

    assert "company" not in out.columns
    assert "id_company" not in out.columns


def test_registros_skips_irrelevant_partidas():
    base = _base([
        {"hs_code": "270900", "value": 80_000_000.0},
        {"hs_code": "999999", "value": 1_000.0},
    ])
    out = compute_registros(base, compute_hs_yearly(base)).collect()

    assert out["hs_code"].unique().to_list() == ["270900"]


def test_monthly_by_country_aggregates_across_products():
    base = _base([
        {"hs_code": "270900", "value": 10.0},
        {"hs_code": "854231", "value": 20.0},
    ])
    out = compute_monthly_by_country(base).collect()

    assert out.height == 1
    assert out["value"].to_list() == [30.0]
    assert "hs_code" not in out.columns


# ---------------------------------------------------------------------------
# Contrato de eficiencia
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [
    compute_country_yearly,
    compute_hs_yearly,
    compute_partner_share,
    compute_partner_by_country,
    compute_hhi,
    compute_monthly_by_hs,
    compute_monthly_by_country,
])
def test_all_metrics_stay_lazy(fn):
    assert isinstance(fn(_base([{}])), pl.LazyFrame)


def test_hhi_is_null_when_the_partida_has_no_declared_value():
    """Hay embarques declarados en 0: dividir por ese total daba n_socios = inf."""
    base = _base([{"partner": "Paraguay", "value": 0.0}])
    out = compute_hhi(base).collect()

    assert out["hhi"].to_list() == [None]
    assert out["n_socios"].to_list() == [None]
    assert out["categoria"].to_list() == [None]
