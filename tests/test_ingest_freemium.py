"""Tests para src/ingest_freemium.py — ingesta estadística multi-país."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from src.ingest_freemium import (
    FreemiumSource,
    aggregate_freemium,
    load_freemium_source,
    normalize_hs6,
    scan_freemium_tree,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config_freemium.yml"


def _write(root: Path, country: str, flow: str, year: int, df: pl.DataFrame) -> Path:
    path = root / country / flow / f"{year}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return path


def _standard_df() -> pl.DataFrame:
    """Variante AR/CO/CL: incluye columnas de actor que deben descartarse."""
    return pl.DataFrame({
        "fecha": [date(2025, 3, 4), date(2025, 3, 18)],
        "company": ["ACME SA", "OTRA SRL"],
        "id_company": [111, 222],
        "value": [1000.0, 500.0],
        "partner": ["Brasil", "China"],
        "aduana": ["BUENOS AIRES", "ROSARIO"],
        "hs_code": [10121, 851712],
        "desc_aran": ["Caballos vivos", "Telefonos"],
        "via_de_transporte": ["MARITIMA", "AEREA"],
    })


def _brazil_df(value_col: str, partner_col: str) -> pl.DataFrame:
    """Variante BR/HN: nombres totalmente distintos y sin columnas de actor."""
    return pl.DataFrame({
        "fecha": [date(2025, 5, 9)],
        value_col: [2500],
        partner_col: ["Estados Unidos"],
        "aduana": ["SANTOS"],
        "cod_arancelario": [270900],
        "desc_arancelaria": ["Aceites crudos de petroleo"],
    })


# ---------------------------------------------------------------------------
# scan_freemium_tree
# ---------------------------------------------------------------------------

def test_scan_tree_derives_country_flow_and_year_from_path(tmp_path):
    _write(tmp_path, "AR", "IM", 2025, _standard_df())
    _write(tmp_path, "AR", "EX", 2024, _standard_df())

    sources = scan_freemium_tree(tmp_path)

    assert len(sources) == 2
    assert {(s.country, s.flow, s.year) for s in sources} == {
        ("AR", "impo", 2025),
        ("AR", "expo", 2024),
    }


def test_scan_tree_ignores_unknown_flow_folders(tmp_path):
    _write(tmp_path, "AR", "IM", 2025, _standard_df())
    _write(tmp_path, "AR", "BORRADOR", 2025, _standard_df())

    sources = scan_freemium_tree(tmp_path)

    assert [s.flow for s in sources] == ["impo"]


def test_scan_tree_ignores_non_parquet_files(tmp_path):
    _write(tmp_path, "BO", "IM", 2025, _standard_df())
    (tmp_path / "BO" / "IM" / "notas.txt").write_text("ignorar", encoding="utf-8")

    assert len(scan_freemium_tree(tmp_path)) == 1


def test_scan_tree_returns_empty_for_missing_root(tmp_path):
    assert scan_freemium_tree(tmp_path / "no-existe") == []


# ---------------------------------------------------------------------------
# normalize_hs6
# ---------------------------------------------------------------------------

def test_normalize_hs6_restores_leading_zeros_from_int(tmp_path):
    lf = pl.LazyFrame({"hs_code": [10121, 20130]})
    result = normalize_hs6(lf).collect()
    assert result["hs_code"].to_list() == ["010121", "020130"]


def test_normalize_hs6_truncates_codes_longer_than_six():
    lf = pl.LazyFrame({"hs_code": [8517120000]})
    assert normalize_hs6(lf).collect()["hs_code"].to_list() == ["851712"]


def test_normalize_hs6_accepts_string_input():
    lf = pl.LazyFrame({"hs_code": ["010121", "8517120000"]})
    assert normalize_hs6(lf).collect()["hs_code"].to_list() == ["010121", "851712"]


def test_normalize_hs6_keeps_nulls():
    lf = pl.LazyFrame({"hs_code": pl.Series([None], dtype=pl.Int64)})
    assert normalize_hs6(lf).collect()["hs_code"].to_list() == [None]


# ---------------------------------------------------------------------------
# load_freemium_source
# ---------------------------------------------------------------------------

def test_load_source_drops_actor_columns(tmp_path):
    path = _write(tmp_path, "AR", "IM", 2025, _standard_df())
    source = FreemiumSource(path=path, country="AR", flow="impo", year=2025)

    result = load_freemium_source(source, CONFIG_PATH).collect()

    assert "company" not in result.columns
    assert "id_company" not in result.columns


def test_load_source_adds_country_flow_and_valuation_basis(tmp_path):
    path = _write(tmp_path, "AR", "IM", 2025, _standard_df())
    source = FreemiumSource(path=path, country="AR", flow="impo", year=2025)

    result = load_freemium_source(source, CONFIG_PATH).collect()

    assert result["country"].unique().to_list() == ["AR"]
    assert result["flow"].unique().to_list() == ["impo"]
    assert result["base_valor"].unique().to_list() == ["CIF"]


def test_load_source_marks_exports_as_fob(tmp_path):
    path = _write(tmp_path, "AR", "EX", 2025, _standard_df())
    source = FreemiumSource(path=path, country="AR", flow="expo", year=2025)

    result = load_freemium_source(source, CONFIG_PATH).collect()

    assert result["base_valor"].unique().to_list() == ["FOB"]


def test_load_source_truncates_periodo_to_month(tmp_path):
    path = _write(tmp_path, "AR", "IM", 2025, _standard_df())
    source = FreemiumSource(path=path, country="AR", flow="impo", year=2025)

    result = load_freemium_source(source, CONFIG_PATH).collect()

    assert result["periodo"].to_list() == [date(2025, 3, 1), date(2025, 3, 1)]


def test_load_source_resolves_brazil_import_aliases(tmp_path):
    path = _write(tmp_path, "BR", "IM", 2025, _brazil_df("cif", "pais_origen"))
    source = FreemiumSource(path=path, country="BR", flow="impo", year=2025)

    result = load_freemium_source(source, CONFIG_PATH).collect()

    assert result["partner"].to_list() == ["Estados Unidos"]
    assert result["hs_code"].to_list() == ["270900"]
    assert result["value"].to_list() == [2500.0]
    assert result["desc_aran"].to_list() == ["Aceites crudos de petroleo"]


def test_load_source_resolves_brazil_export_aliases(tmp_path):
    path = _write(tmp_path, "BR", "EX", 2025, _brazil_df("fob", "pais_destino"))
    source = FreemiumSource(path=path, country="BR", flow="expo", year=2025)

    result = load_freemium_source(source, CONFIG_PATH).collect()

    assert result["partner"].to_list() == ["Estados Unidos"]
    assert result["value"].to_list() == [2500.0]


def test_load_source_raises_when_required_column_missing(tmp_path):
    df = _standard_df().drop("partner")
    path = _write(tmp_path, "AR", "IM", 2025, df)
    source = FreemiumSource(path=path, country="AR", flow="impo", year=2025)

    with pytest.raises(ValueError, match="partner"):
        load_freemium_source(source, CONFIG_PATH)


# ---------------------------------------------------------------------------
# aggregate_freemium
# ---------------------------------------------------------------------------

def test_aggregate_sums_value_by_period_country_flow_hs_partner(tmp_path):
    df = pl.DataFrame({
        "fecha": [date(2025, 3, 1), date(2025, 3, 20), date(2025, 4, 2)],
        "value": [100.0, 50.0, 70.0],
        "partner": ["Brasil", "Brasil", "Brasil"],
        "hs_code": [270900, 270900, 270900],
        "desc_aran": ["Petroleo", "Petroleo", "Petroleo"],
    })
    path = _write(tmp_path, "AR", "IM", 2025, df)
    source = FreemiumSource(path=path, country="AR", flow="impo", year=2025)

    result = aggregate_freemium([load_freemium_source(source, CONFIG_PATH)])

    assert result.height == 2
    marzo = result.filter(pl.col("periodo") == date(2025, 3, 1))
    assert marzo["value"].to_list() == [150.0]


def test_aggregate_never_merges_cif_and_fob(tmp_path):
    impo = _write(tmp_path, "AR", "IM", 2025, _standard_df())
    expo = _write(tmp_path, "AR", "EX", 2025, _standard_df())
    frames = [
        load_freemium_source(FreemiumSource(impo, "AR", "impo", 2025), CONFIG_PATH),
        load_freemium_source(FreemiumSource(expo, "AR", "expo", 2025), CONFIG_PATH),
    ]

    result = aggregate_freemium(frames)

    assert set(result["base_valor"].unique().to_list()) == {"CIF", "FOB"}
    # Mismo periodo/hs/partner en ambos flujos: deben quedar como filas separadas
    petroleo = result.filter(pl.col("hs_code") == "010121")
    assert petroleo.height == 2


def test_aggregate_output_carries_no_actor_columns(tmp_path):
    path = _write(tmp_path, "AR", "IM", 2025, _standard_df())
    source = FreemiumSource(path=path, country="AR", flow="impo", year=2025)

    result = aggregate_freemium([load_freemium_source(source, CONFIG_PATH)])

    assert "company" not in result.columns
    assert "id_company" not in result.columns
