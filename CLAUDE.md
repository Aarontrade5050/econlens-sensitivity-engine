# EconoLens – Contexto del Proyecto

## Qué es este proyecto

Motor de Sensibilidad Económica Dinámica para análisis de importaciones Perú–USA.
Transforma datos de aduanas (Parquet) en métricas de riesgo estructural por producto e importador.

El output principal es una tabla con:

| periodo | actor | hs_code | arquetipo_economico | volumen | precio | var_pct_volumen_mensual | var_pct_precio_mensual | volatilidad_precio_6m | elasticidad_simple | shock_compuesto_flag | ise_score | ise_nivel |

## Plan 18 meses

- **FASE 1** ✅ Motor cuantitativo (variación, volatilidad, elasticidad, shock, ISE)
- **FASE 2** ✅ Score ISE, variante actor, pipeline orquestado, validación, multi-producto
- **FASE 3** ✅ Base de datos DuckDB ✅ — API FastAPI ✅ — Pipeline automatizado ✅
- **FASE 4** ✅ Dashboard Streamlit ✅ — Interpretabilidad económica ✅ — Documentación publicable ✅
- **FASE 5** ✅ Dashboard profesional multi-tab ✅ — Agregaciones de mercado ✅ — Dark theme ✅
- **FASE 6** ✅ Capa de limpieza liviana ✅ — Normalización de nombres (top 80% volumen) ✅
- **FASE 7** ✅ Dimensión arancelaria — tabla `dim_partida` ✅ — Navegador en cascada 5 niveles en dashboard ✅
- **FASE 7.5** ✅ Arquetipos económicos ✅ — Umbrales dinámicos ISE por producto ✅ — Guardián de unidades (BIEN_DURADERO → USD/unidad) ✅
- **FASE 8** ✅ Flujo de ingesta desde inbox ✅ — `config.yml` con schema canónico y aliases ✅ — `ingest.py` integrado en `run.py` ✅
- **FASE 9** ✅ Agregaciones con dimensión mensual (`periodo`) ✅ — Filtro Desde/Hasta en dashboard ✅ — File uploader multi-formato (parquet/csv/xlsx) ✅ — Pipeline en memoria por sesión de usuario (`_process_raw`) ✅

## Estructura del proyecto

```
src/
  ingest.py        # ingest_inbox() — lee inbox/, aplica config.yml, une con df_all.parquet
  metrics.py       # Cálculo de métricas (variación, volatilidad, elasticidad, shock, ISE)
  pipeline.py      # run_pipeline() y run_pipeline_multi() — orquestación del flujo
  validation.py    # validate_dataframe() — validación de input antes del pipeline
  database.py      # save_results() / load_results() / load_aggregation() / load_dim_partida() — persistencia en DuckDB
  api.py           # FastAPI — endpoints GET /results, /results/{hs_code}, /results/{hs_code}/actores
  updater.py       # run_pipeline_auto() — detecta archivos nuevos y actualiza la DB
  dashboard.py     # Streamlit 5 tabs + file uploader (parquet/csv/xlsx) + pipeline en memoria por sesión + filtro Desde/Hasta — Competidores / Precios y Rutas / Evolución / Alertas ISE / Proveedores Internacionales
  narratives.py    # generate_narrative(row) y add_narratives(df) — texto automático por fila ISE
  aggregations.py  # compute_market_share (FOB+vol) / compute_supplier_matrix / 4 funciones más / run_aggregations() con dimensión mensual (columna `periodo`)
  cleaning.py      # clean_raw_df() / add_unit_adjusted_quantity() — normalización y guardián de unidades
  arquetipos.py    # clasificar_arquetipo() / get_archetype() / ARCHETYPE_THRESHOLDS — arquetipos por capítulo HS
  io.py            # Conversión XLSX → Parquet
tests/
  test_ingest.py        # 12 tests para ingest_inbox() y funciones auxiliares
  test_metrics.py
  test_pipeline.py
  test_validation.py
  test_database.py
  test_api.py
  test_updater.py
  test_narratives.py
  test_aggregations.py  # 19 tests para las 6 funciones de agregación + 2 tests de segmentación por periodo en run_aggregations()
  test_cleaning.py      # 12 tests para clean_raw_df()
  test_arquetipos.py    # 6 tests para clasificar_arquetipo() y add_unit_adjusted_quantity()
data/
  inbox/           # Parquets nuevos para ingestar (procesados → se mueven a inbox/done/)
  inbox/done/      # Parquets ya procesados (no se reprocesarán)
  raw/             # Archivos de referencia: HS2022_Jerarquia_Completa.xlsx (ignorados por git)
  interim/         # df_all.parquet — dataset combinado (ignorado por git)
  processed/       # econolens.duckdb, CSVs de output (ignorados por git)
.streamlit/
  config.toml      # Dark theme: #0f172a fondo, #38bdf8 acento
config.yml         # Schema canónico de ingesta: columnas required/optional con aliases por fuente
run.py             # Script de entrada: inbox → limpieza → arquetipos → pipeline ISE → agregaciones → dim_partida → DuckDB
```

## Flujo de ingesta de nueva data

```
data/inbox/*.parquet
    → ingest.py lee config.yml
    → resuelve columnas por nombre canónico o alias
    → renombra y castea tipos
    → valida columnas requeridas
    → concat con data/interim/df_all.parquet
    → mueve archivos a data/inbox/done/
→ run_pipeline_multi() → DuckDB
```

Para agregar nueva data:
1. Convertir a parquet si viene en xlsx: `pl.read_excel("archivo.xlsx").write_parquet("data/inbox/archivo.parquet")`
2. Depositar el parquet en `data/inbox/`
3. Correr `python run.py` — la ingesta es automática

## Datos

- Fuente: importaciones Perú desde USA 2025 (SUNAT) — 1.2M+ filas, 64 columnas
- Columnas canónicas requeridas: `PARTIDA ARANCELARIA`, `IMPORTADOR`, `US$ FOB`, `CANTIDAD`, `UNIDAD DE MEDIDA`, `PESO NETO`, `DÍA`, `MES`, `AÑO`
- Columnas opcionales: `ADUANA`, `PAÍS DE ADQUISICIÓN`, `PAÍS DE ORIGEN`, `VÍA DE TRANSPORTE`, `PUERTO DE EMBARQUE`, `US$ CIF`, `DUA`, `CANAL`, `INCOTERM`, `PROVEEDOR`, `EXPORTADOR`, `EMPRESA EXPORTADORA`, `EMBARCADOR`, `PROBABLE EMBARCADOR`
- Si una fuente nueva usa nombres distintos, agregar en `config.yml` bajo `aliases`
- `PARTIDA ARANCELARIA` viene como Int64 en el parquet — se castea a String antes del pipeline **y antes de run_aggregations()**

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
fastexcel
pyyaml      # lectura de config.yml
pytest
pandas      # solo para conversión inicial en notebook
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
