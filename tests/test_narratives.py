import polars as pl
import pytest

from src.narratives import generate_narrative, add_narratives


def _base_row(**overrides) -> dict:
    """Fila base con valores neutrales."""
    row = {
        "periodo": "2025-03",
        "hs_code": "2710200012",
        "actor": "EMPRESA_A",
        "var_pct_volumen_mensual": 0.0,
        "var_pct_precio_mensual": 0.0,
        "volatilidad_precio_6m": 0.10,
        "shock_compuesto_flag": 0,
        "ise_score": 30.0,
        "ise_nivel": "Bajo",
    }
    row.update(overrides)
    return row


# --- generate_narrative ---

def test_narrative_siempre_incluye_ise_score():
    row = _base_row(ise_score=45.2, ise_nivel="Medio")
    result = generate_narrative(row)
    assert "45.2" in result
    assert "Medio" in result


def test_narrative_siempre_incluye_actor():
    row = _base_row(actor="VALERO")
    result = generate_narrative(row)
    assert "VALERO" in result


def test_narrative_siempre_incluye_periodo():
    row = _base_row(periodo="2025-07")
    result = generate_narrative(row)
    assert "2025-07" in result


def test_narrative_menciona_shock_cuando_flag_activo():
    row = _base_row(shock_compuesto_flag=1, ise_score=78.5, ise_nivel="Alto")
    result = generate_narrative(row)
    assert "shock" in result.lower()


def test_narrative_no_menciona_shock_cuando_flag_inactivo():
    row = _base_row(shock_compuesto_flag=0)
    result = generate_narrative(row)
    assert "shock" not in result.lower()


def test_narrative_menciona_caida_de_volumen():
    row = _base_row(var_pct_volumen_mensual=-35.0)
    result = generate_narrative(row)
    assert "35" in result
    assert any(w in result.lower() for w in ["redujo", "cayó", "disminuyó", "volumen"])


def test_narrative_menciona_subida_de_volumen():
    row = _base_row(var_pct_volumen_mensual=25.0)
    result = generate_narrative(row)
    assert "25" in result
    assert any(w in result.lower() for w in ["incrementó", "aumentó", "subió", "volumen"])


def test_narrative_menciona_subida_de_precio():
    row = _base_row(var_pct_precio_mensual=15.0)
    result = generate_narrative(row)
    assert "15" in result
    assert any(w in result.lower() for w in ["precio", "subió", "incrementó", "aumentó"])


def test_narrative_menciona_caida_de_precio():
    row = _base_row(var_pct_precio_mensual=-12.0)
    result = generate_narrative(row)
    assert "12" in result
    assert any(w in result.lower() for w in ["precio", "cayó", "redujo", "bajó"])


def test_narrative_menciona_volatilidad_alta():
    row = _base_row(volatilidad_precio_6m=0.45)
    result = generate_narrative(row)
    assert any(w in result.lower() for w in ["volatilidad", "inestabilidad", "volátil"])


def test_narrative_no_menciona_volatilidad_cuando_normal():
    row = _base_row(volatilidad_precio_6m=0.10)
    result = generate_narrative(row)
    assert "volatilidad" not in result.lower()


def test_narrative_retorna_string():
    row = _base_row()
    assert isinstance(generate_narrative(row), str)


def test_narrative_no_retorna_vacio():
    row = _base_row()
    assert len(generate_narrative(row)) > 0


# --- add_narratives ---

def _make_df() -> pl.DataFrame:
    return pl.DataFrame([
        {
            "periodo": "2025-01",
            "hs_code": "2710200012",
            "actor": "EMPRESA_A",
            "var_pct_volumen_mensual": -35.0,
            "var_pct_precio_mensual": 11.0,
            "volatilidad_precio_6m": 0.23,
            "shock_compuesto_flag": 1,
            "ise_score": 78.5,
            "ise_nivel": "Alto",
        },
        {
            "periodo": "2025-02",
            "hs_code": "2710200012",
            "actor": "EMPRESA_B",
            "var_pct_volumen_mensual": 5.0,
            "var_pct_precio_mensual": 2.0,
            "volatilidad_precio_6m": 0.08,
            "shock_compuesto_flag": 0,
            "ise_score": 25.0,
            "ise_nivel": "Bajo",
        },
    ])


def test_add_narratives_agrega_columna_narrativa():
    df = add_narratives(_make_df())
    assert "narrativa" in df.columns


def test_add_narratives_no_modifica_columnas_existentes():
    df_original = _make_df()
    df_result = add_narratives(df_original)
    for col in df_original.columns:
        assert col in df_result.columns


def test_add_narratives_una_narrativa_por_fila():
    df = _make_df()
    df_result = add_narratives(df)
    assert df_result.shape[0] == df.shape[0]


def test_add_narratives_columna_es_string():
    df = add_narratives(_make_df())
    assert df["narrativa"].dtype == pl.String


def test_add_narratives_ninguna_narrativa_vacia():
    df = add_narratives(_make_df())
    assert df["narrativa"].is_null().sum() == 0
    assert (df["narrativa"].str.len_chars() > 0).all()
