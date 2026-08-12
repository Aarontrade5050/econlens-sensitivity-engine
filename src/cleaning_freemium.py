"""Normalización de nombres de socio comercial para la capa freemium.

Cada aduana escribe distinto al mismo país ("U.S.A", "Estados Unidos de
América", "ESTADOS UNIDOS DE NORTEAMERICA"), lo que rompe cualquier comparación
entre países. Este módulo unifica esos nombres en tres pasos:

    1. normalización mecánica (mayúsculas, sin acentos, sin puntuación)
    2. sinónimos curados en resources/partner_aliases.yml
    3. buckets para socio no informado y para zonas francas

Todo se resuelve con expresiones de Polars sobre LazyFrame: el agregado supera
los 7M de filas y no admite UDFs de Python fila por fila.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import yaml

# Acentos que sobreviven a to_uppercase() en las fuentes latinoamericanas.
_ACCENT_MAP: dict[str, str] = {
    "Á": "A", "À": "A", "Â": "A", "Ã": "A", "Ä": "A",
    "É": "E", "È": "E", "Ê": "E", "Ë": "E",
    "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
    "Ó": "O", "Ò": "O", "Ô": "O", "Õ": "O", "Ö": "O",
    "Ú": "U", "Ù": "U", "Û": "U", "Ü": "U",
    "Ñ": "N", "Ç": "C",
}


def load_partner_config(config_path: Path | str) -> dict[str, Any]:
    """Carga el mapa de sinónimos y buckets de socios desde YAML."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _canonical_key(col: str) -> pl.Expr:
    """Lleva un nombre crudo a su forma comparable: MAYÚSCULAS, sin acentos ni
    puntuación, con espacios colapsados."""
    return (
        pl.col(col)
        .str.to_uppercase()
        .str.replace_many(_ACCENT_MAP)
        .str.replace_all(r"[^A-Z0-9 ]", " ")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
    )


def normalize_partner(
    lf: pl.LazyFrame,
    config: dict[str, Any],
    col: str = "partner",
) -> pl.LazyFrame:
    """Unifica los nombres de socio y devuelve el nombre de presentación.

    Los socios sin informar y las zonas francas se agrupan en sus respectivos
    buckets en lugar de descartarse: en Argentina el socio no informado es el
    14% del valor declarado, y omitirlo distorsionaría los shares y el HHI.
    """
    etiquetas = config["etiquetas"]
    regimen = config["regimen_especial"]

    key = _canonical_key(col).replace(config["sinonimos"])

    es_regimen = key.str.contains(regimen["patron"]) | key.is_in(regimen["nombres"])

    # Algunas fuentes dejan el código numérico de país sin resolver ("042",
    # "781"). Un código suelto no identifica al socio, así que va al mismo
    # bucket que el valor sin país declarado.
    es_codigo = key.str.contains(r"^[0-9]+$")
    es_no_declarado = (
        key.is_null() | (key == "") | es_codigo | key.is_in(config["no_declarado"])
    )

    return lf.with_columns(
        pl.when(es_no_declarado)
        .then(pl.lit(etiquetas["no_declarado"]))
        .when(es_regimen)
        .then(pl.lit(etiquetas["regimen_especial"]))
        .otherwise(key.replace_strict(config["display"], default=key.str.to_titlecase()))
        .alias(col)
    )
