# Generador de narrativas económicas automáticas
import polars as pl

# Umbrales para activar cada tipo de mención
_UMBRAL_VOLUMEN = 20.0   # % de cambio en volumen
_UMBRAL_PRECIO = 10.0    # % de cambio en precio
_UMBRAL_VOLATILIDAD = 0.3  # volatilidad rolling 6m


def generate_narrative(row: dict) -> str:
    """Genera una narrativa económica legible para una fila del resultado ISE.

    La narrativa prioriza eventos en este orden:
    1. Shock compuesto detectado
    2. Variación de volumen significativa
    3. Variación de precio significativa
    4. Volatilidad alta
    5. Cierre siempre con ISE score y nivel
    """
    actor = row.get("actor", "Actor desconocido")
    periodo = row.get("periodo", "")
    ise_score = row.get("ise_score", 0.0)
    ise_nivel = row.get("ise_nivel", "")
    var_vol = row.get("var_pct_volumen_mensual", 0.0) or 0.0
    var_precio = row.get("var_pct_precio_mensual", 0.0) or 0.0
    volatilidad = row.get("volatilidad_precio_6m", 0.0) or 0.0
    shock = row.get("shock_compuesto_flag", 0)

    eventos = []

    # 1. Shock compuesto
    if shock:
        eventos.append("shock compuesto detectado")

    # 2. Variación de volumen
    if abs(var_vol) >= _UMBRAL_VOLUMEN:
        if var_vol < 0:
            eventos.append(f"redujo volumen un {abs(var_vol):.1f}%")
        else:
            eventos.append(f"incrementó volumen un {var_vol:.1f}%")

    # 3. Variación de precio
    if abs(var_precio) >= _UMBRAL_PRECIO:
        if var_precio > 0:
            eventos.append(f"precio subió un {var_precio:.1f}%")
        else:
            eventos.append(f"precio cayó un {abs(var_precio):.1f}%")

    # 4. Volatilidad alta
    if volatilidad >= _UMBRAL_VOLATILIDAD:
        eventos.append(f"alta volatilidad de precio ({volatilidad:.2f})")

    # Construir oración principal
    if eventos:
        cuerpo = f"{actor} — {'; '.join(eventos)} en {periodo}"
    else:
        cuerpo = f"{actor} sin eventos significativos en {periodo}"

    return f"{cuerpo} (ISE {ise_nivel}: {ise_score:.1f})"


def add_narratives(df: pl.DataFrame) -> pl.DataFrame:
    """Agrega una columna 'narrativa' al DataFrame con texto generado por fila."""
    narrativas = [generate_narrative(row) for row in df.to_dicts()]
    return df.with_columns(pl.Series("narrativa", narrativas))
