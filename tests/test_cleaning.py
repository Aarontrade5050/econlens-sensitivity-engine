import polars as pl
import pytest
from src.cleaning import clean_raw_df


@pytest.fixture
def raw_df() -> pl.DataFrame:
    return pl.DataFrame({
        "IMPORTADOR": [
            "COMPAÑÍA LIMPIA S.A.",                               # sin cambio
            "  ESPACIOS   DOBLES  S.A.C  ",                       # strip + colapso
            '"EMPRESA CON COMILLAS S.R.L."',                      # comillas externas
            "COMPA?IA MOLINERA DEL CENTRO S.A./CIA. MOLINERA S",  # ? + slash
            "AN?NIMA CORPORACION S.A.",                           # ? → Ó
            "VI?A SANTA ISABEL S.A.C.",                           # ? → Ñ
            "SOUTHERN PERU SUCURSA L DEL PERU",                   # espacio insertado
            "::::::",                                              # basura → None
            None,                                                  # nulo → nulo
        ],
        "UNIDAD DE MEDIDA": [
            "KG", "U 3", "2U", "KG", "U", "L", "M2", "KG", "KG"
        ],
        "CANTIDAD": [100.0] * 9,
    })


# -----------------------------------------------------------------------
# Nombres de importadores
# -----------------------------------------------------------------------

def test_clean_raw_df_no_change_for_clean_name(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][0] == "COMPAÑÍA LIMPIA S.A."


def test_clean_raw_df_strips_and_collapses_spaces(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][1] == "ESPACIOS DOBLES S.A.C"


def test_clean_raw_df_removes_outer_quotes(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][2] == "EMPRESA CON COMILLAS S.R.L."


def test_clean_raw_df_fixes_encoding_and_slash(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][3] == "COMPAÑÍA MOLINERA DEL CENTRO S.A."


def test_clean_raw_df_fixes_anonima_encoding(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][4] == "ANÓNIMA CORPORACION S.A."


def test_clean_raw_df_fixes_vina_encoding(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][5] == "VIÑA SANTA ISABEL S.A.C."


def test_clean_raw_df_fixes_sucursal_space(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][6] == "SOUTHERN PERU SUCURSAL DEL PERU"


def test_clean_raw_df_sets_garbage_to_null(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][7] is None


def test_clean_raw_df_preserves_null(raw_df):
    result = clean_raw_df(raw_df)
    assert result["IMPORTADOR"][8] is None


# -----------------------------------------------------------------------
# Unidades de medida
# -----------------------------------------------------------------------

def test_clean_raw_df_fixes_u3_unit(raw_df):
    result = clean_raw_df(raw_df)
    assert result["UNIDAD DE MEDIDA"][1] == "U"


def test_clean_raw_df_fixes_2u_unit(raw_df):
    result = clean_raw_df(raw_df)
    assert result["UNIDAD DE MEDIDA"][2] == "U"


def test_clean_raw_df_preserves_valid_units(raw_df):
    result = clean_raw_df(raw_df)
    assert result["UNIDAD DE MEDIDA"][0] == "KG"
    assert result["UNIDAD DE MEDIDA"][5] == "L"
    assert result["UNIDAD DE MEDIDA"][6] == "M2"
