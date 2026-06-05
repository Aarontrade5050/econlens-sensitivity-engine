# EconoLens – Contexto del Proyecto

## Qué es este proyecto

Motor de Sensibilidad Económica Dinámica para análisis de importaciones Perú–USA.
Transforma datos de aduanas (Excel/Parquet) en métricas de riesgo estructural por producto e importador.

El output principal es una tabla con:

| periodo | actor | hs_code | volumen | precio | var_pct_volumen_mensual | var_pct_precio_mensual | volatilidad_precio_6m | elasticidad_simple | shock_compuesto_flag | ise_score | ise_nivel |

## Plan 18 meses

- **FASE 1** ✅ Motor cuantitativo (variación, volatilidad, elasticidad, shock, ISE)
- **FASE 2** ✅ Score ISE, variante actor, pipeline orquestado, validación, multi-producto
- **FASE 3** ✅ Base de datos DuckDB ✅ — API FastAPI ✅ — Pipeline automatizado ✅
- **FASE 4** ✅ Dashboard Streamlit ✅ — Interpretabilidad económica ✅ — Documentación publicable ✅
- **FASE 5** ✅ Dashboard profesional multi-tab ✅ — Agregaciones de mercado ✅ — Dark theme ✅
- **FASE 6** ✅ Capa de limpieza liviana ✅ — Normalización de nombres (top 80% volumen) ✅
- **FASE 7** ✅ Dimensión arancelaria — tabla `dim_partida` ✅ — Navegador en cascada 5 niveles en dashboard ✅

## Estructura del proyecto

```
src/
  metrics.py       # Cálculo de métricas (variación, volatilidad, elasticidad, shock, ISE)
  pipeline.py      # run_pipeline() y run_pipeline_multi() — orquestación del flujo
  validation.py    # validate_dataframe() — validación de input antes del pipeline
  database.py      # save_results() / load_results() / load_aggregation() / load_dim_partida() — persistencia en DuckDB
  api.py           # FastAPI — endpoints GET /results, /results/{hs_code}, /results/{hs_code}/actores
  updater.py       # run_pipeline_auto() — detecta archivos nuevos y actualiza la DB
  dashboard.py     # Streamlit 4 tabs — Competidores / Precios y Rutas / Evolución / Alertas ISE
  narratives.py    # generate_narrative(row) y add_narratives(df) — texto automático por fila ISE
  aggregations.py  # 5 funciones de mercado + run_aggregations() — trabaja sobre df_all.parquet
  cleaning.py      # clean_raw_df() — normalización vectorizada de IMPORTADOR y UNIDAD DE MEDIDA
  io.py            # Conversión XLSX → Parquet
tests/
  test_metrics.py
  test_pipeline.py
  test_validation.py
  test_database.py
  test_api.py
  test_updater.py
  test_narratives.py
  test_aggregations.py  # 12 tests para las 5 funciones de agregación
  test_cleaning.py      # 12 tests para clean_raw_df()
  # test_database.py incluye 3 tests adicionales para load_dim_partida()
data/
  raw/             # Excel originales (ignorados por git)
  interim/         # df_all.parquet (ignorado por git)
  processed/       # econolens.duckdb, CSVs de output (ignorados por git)
.streamlit/
  config.toml      # Dark theme: #0f172a fondo, #38bdf8 acento
run.py             # Script de entrada: limpieza → pipeline ISE → 5 tablas de agregación → dim_partida → DuckDB
```

## Datos

- Fuente: importaciones Perú desde USA 2025 (SUNAT) — 1.2M filas, 64 columnas
- Columnas usadas por el pipeline ISE: `PARTIDA ARANCELARIA`, `IMPORTADOR`, `US$ FOB`, `CANTIDAD`, `UNIDAD DE MEDIDA`, `DÍA`, `MES`, `AÑO`
- Columnas adicionales usadas por aggregations.py: `ADUANA` (17 puertos de ingreso), `PAÍS DE ADQUISICIÓN` (87 países)
- `PARTIDA ARANCELARIA` viene como Int64 en el parquet — se castea a String antes del pipeline **y antes de run_aggregations()**
- Otras columnas disponibles relevantes: `VÍA DE TRANSPORTE`, `PUERTO DE EMBARQUE`, `PESO NETO`, `US$ CIF`, `INCOTERM`, `CANAL`

## Reglas de código

### Estilo
- Sigue **PEP8**
- **Type hints** en todas las funciones y clases
- **Docstrings** breves y útiles en funciones públicas
- Sin duplicación de lógica

### Arquitectura
- **Separación clara de responsabilidades**: io / validación / métricas / pipeline / base de datos
- **Modularidad**: cada función hace una sola cosa
- **Configuración centralizada**: sin rutas, nombres o parámetros hardcodeados
- **Diseño escalable y mantenible**

### Desarrollo
- **TDD obligatorio**: escribir tests que fallen (RED) antes de implementar (GREEN)
- Correr suite completa (`pytest -v`) después de cada cambio para confirmar que nada se rompe
- **Manejo de errores explícito**: `ValueError` con mensajes claros, no errores crípticos de Polars

### Performance
- Usar **Polars** sobre Pandas
- Preferir **lazy evaluation** (`scan_parquet`, `.lazy()`) cuando el dataset lo justifique
- Evitar recalcular lo que ya está en la base de datos

### Observabilidad
- Usar **logging** en lugar de `print()`
- Nivel `INFO` para flujo normal, `WARNING` para hs_codes saltados en multi-producto

### CI (pendiente configurar)
- Tests automáticos en cada push
- Lint automático (ruff o flake8)

## Dependencias actuales

```
polars
duckdb
pyarrow
openpyxl
pytest
pandas  # solo para conversión inicial en notebook
numpy
fastapi
uvicorn
httpx       # requerido por FastAPI TestClient
streamlit   # dashboard
plotly      # gráficos en el dashboard
# Para correr la API: uvicorn src.api:app --reload
# Para correr el dashboard: streamlit run src/dashboard.py
```

## Regla principal del proyecto

> No rediseñar mientras se ejecuta.
> Progreso > perfección. Consistencia > intensidad. Acumulación > entusiasmo.
