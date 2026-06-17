# EconoLens — Motor de Sensibilidad Económica

> Transforma datos de aduanas en métricas de riesgo estructural por producto e importador.

EconoLens es un motor de análisis cuantitativo que procesa importaciones Perú–USA (SUNAT) y produce un **Score de Sensibilidad Económica (ISE)** por producto y actor, detectando shocks, volatilidad y cambios estructurales en precio y volumen.

---

## Output principal

| periodo | actor | hs_code | arquetipo_economico | volumen | precio | var_pct_volumen_mensual | var_pct_precio_mensual | volatilidad_precio_6m | elasticidad_simple | shock_compuesto_flag | ise_score | ise_nivel |
|---------|-------|---------|---------------------|---------|--------|------------------------|----------------------|----------------------|--------------------|---------------------|-----------|-----------|
| 2025-03 | EMPRESA_A | 2710200012 | COMMODITY | 50000 | 2.50 | -18.4 | 11.2 | 0.23 | -1.64 | 1 | 78.5 | Alto |

---

## Instalación

### Requisitos
- Python 3.11+
- pip

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/Aarontrade5050/econlens-sensitivity-engine.git
cd econlens-sensitivity-engine

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## Estructura del proyecto

```
src/
  metrics.py       # Cálculo de métricas: variación, volatilidad, elasticidad, shock, ISE
  pipeline.py      # run_pipeline() y run_pipeline_multi() — orquestación del flujo
  validation.py    # validate_dataframe() — validación de input antes del pipeline
  database.py      # save_results() / load_results() / load_aggregation() / load_dim_partida()
  api.py           # FastAPI — endpoints REST para consultar resultados
  updater.py       # run_pipeline_auto() — detecta archivos nuevos y actualiza la DB
  dashboard.py     # Streamlit 4 tabs + navegador arancelario en cascada (5 niveles)
  narratives.py    # generate_narrative() — texto automático por fila ISE
  aggregations.py  # 5 funciones de mercado + run_aggregations() (market share, precios, rutas...)
  cleaning.py      # clean_raw_df() / add_unit_adjusted_quantity() — normalización y guardián de unidades
  arquetipos.py    # clasificar_arquetipo() / get_archetype() / ARCHETYPE_THRESHOLDS
  io.py            # Conversión XLSX → Parquet
tests/             # 128 tests — pytest
data/
  raw/             # Excel originales de SUNAT + HS2022_Jerarquia_Completa.xlsx (ignorados por git)
  interim/         # Parquets intermedios (ignorados por git)
  processed/       # econolens.duckdb y CSVs de output (ignorados por git)
run.py             # Script de entrada: limpieza → arquetipos → pipeline ISE → agregaciones → dim_partida → DuckDB
```

---

## Uso

### 1. Procesar datos y poblar la base de datos

Coloca los archivos Excel de SUNAT en `data/raw/` y ejecuta:

```bash
python run.py
```

Esto procesa todos los productos del dataset, calcula métricas ISE y guarda los resultados en `data/processed/econolens.duckdb`.

### 2. Dashboard interactivo

```bash
streamlit run src/dashboard.py
```

Abre `http://localhost:8501` en el navegador. El dashboard incluye:

**Navegador arancelario en cascada** (parte superior, 5 niveles):
Sección → Capítulo → Partida 4d → Subpartida 6d → Código 10d

**Badge de arquetipo** (debajo del navegador): muestra el tipo económico del producto seleccionado y los umbrales de shock activos (volumen / precio).

**4 pestañas de análisis:**
- **Competidores e Importadores** — cuota de mercado, volumen y participación por actor
- **Precios, Rutas y Adquisición** — precio FOB por país de origen y aduana de ingreso
- **Evolución Temporal** — empresas activas por período, volumen y precio en el tiempo
- **Alertas ISE** — shocks calibrados por arquetipo, con narrativa automática y severidad (Crítico/Alto/Moderado)

### 3. API REST

```bash
uvicorn src.api:app --reload
```

Documentación interactiva disponible en `http://localhost:8000/docs`.

**Endpoints:**

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/results` | Todos los resultados. Filtros: `hs_code`, `actor`, `from_period`, `to_period` |
| GET | `/results/{hs_code}` | Resultados de un producto específico |
| GET | `/results/{hs_code}/actores` | Resultados con breakdown por importador |

**Ejemplo:**
```bash
curl "http://localhost:8000/results?hs_code=2710200012&from_period=2025-01&to_period=2025-06"
```

### 4. Pipeline automatizado (nuevos archivos)

Para procesar solo archivos nuevos sin reprocesar los anteriores:

```python
from pathlib import Path
from src.updater import run_pipeline_auto

run_pipeline_auto(
    raw_dir=Path("data/raw"),
    db_path=Path("data/processed/econolens.duckdb"),
    manifest_path=Path("data/processed/manifest.json"),
)
```

---

## Métricas calculadas

| Métrica | Descripción |
|---------|-------------|
| `var_pct_volumen_mensual` | Variación % mensual del volumen importado |
| `var_pct_precio_mensual` | Variación % mensual del precio unitario |
| `volatilidad_precio_6m` | Desviación estándar rolling del precio en 6 meses |
| `elasticidad_simple` | ΔVolumen / ΔPrecio — sensibilidad de demanda |
| `shock_compuesto_flag` | 1 si hay shock simultáneo en precio y volumen |
| `ise_score` | Score compuesto 0–100 de sensibilidad económica |
| `ise_nivel` | Clasificación: Alto (>60) / Medio (30–60) / Bajo (<30) |
| `arquetipo_economico` | Tipo económico del producto: COMMODITY / BIEN_DURADERO / PERECEDERO / ESTANDAR |

---

## Tests

```bash
pytest -v
```

128 tests distribuidos en:

| Archivo | Tests | Cubre |
|---------|-------|-------|
| `test_metrics.py` | 30 | Cálculo de métricas |
| `test_pipeline.py` | 22 | Orquestación del flujo |
| `test_validation.py` | 4 | Validación de input |
| `test_database.py` | 12 | Persistencia DuckDB + load_dim_partida |
| `test_api.py` | 10 | Endpoints FastAPI |
| `test_updater.py` | 9 | Pipeline automatizado |
| `test_narratives.py` | 18 | Generador de narrativas |
| `test_aggregations.py` | 12 | 5 funciones de mercado |
| `test_cleaning.py` | 12 | Normalización de importadores |
| `test_arquetipos.py` | 6 | Clasificador de arquetipos + guardián de unidades |

---

## Decisiones de diseño

**Polars sobre Pandas** — rendimiento significativamente mayor en datasets tabulares grandes; lazy evaluation donde aplica.

**DuckDB como base de datos** — embebida, sin servidor, ideal para analítica local con SQL completo. Cero configuración. Tablas activas: `sensitivity_results`, `market_share`, `price_by_country`, `price_by_route`, `price_spread`, `entities_over_time`, `dim_partida`.

**dim_partida como dimensión HS** — jerarquía arancelaria (Sección → Capítulo → Partida 4d → Subpartida 6d) almacenada en DuckDB. El join con los códigos de 10 dígitos del raw se hace por los primeros 6 caracteres (cobertura 99.9%).

**Limpieza vectorizada** — `clean_raw_df()` normaliza importadores y unidades mediante expresiones Polars puras, sin loops Python. Corrige encoding (`?` por Ñ/Ó), splits por `/`, espacios duplicados y variantes de unidad (`U 3`, `2U`).

**FastAPI con dependency injection** — `get_db_path()` como dependencia inyectable permite sobrescribir la ruta de DB en tests sin modificar el código de producción.

**Pipeline automatizado con manifest JSON** — rastrea qué archivos ya fueron procesados para hacer append incremental a la DB sin duplicar datos.

**Narrativas por reglas** — texto generado sin LLM, determinista y auditable. Prioridad: shock → volumen → precio → volatilidad.

**Arquetipos económicos** — el motor ISE calibra sus umbrales de shock según el tipo de producto: COMMODITY (±5% precio), BIEN_DURADERO (±80% volumen — arribo en lotes), PERECEDERO (±25% volumen), ESTÁNDAR (default). El precio de bienes duraderos se calcula por unidad física (USD/unidad), no por kg.

**TDD a lo largo de todo el proyecto** — cada módulo tiene tests escritos antes de la implementación (RED → GREEN).

---

## Datos

- **Fuente:** SUNAT — importaciones Perú desde USA 2025
- **Formato raw:** Excel (.xlsx) con columnas `PARTIDA ARANCELARIA`, `IMPORTADOR`, `US$ FOB`, `CANTIDAD`, `UNIDAD DE MEDIDA`, `DÍA`, `MES`, `AÑO`
- **Nota:** `PARTIDA ARANCELARIA` viene como Int64 en parquet — se castea a String antes del pipeline y antes de las agregaciones
- **Jerarquía HS:** `data/raw/HS2022_Jerarquia_Completa.xlsx` — 5,612 filas, cubre hasta subpartida 6d; join con el raw por primeros 6 dígitos del código 10d

---

## Dependencias

```
polars          # procesamiento de datos
duckdb          # base de datos embebida
pyarrow         # serialización parquet
openpyxl        # lectura de Excel (Pandas)
fastexcel       # lectura de Excel (Polars) — requerido para pl.read_excel()
fastapi         # API REST
uvicorn         # servidor ASGI
httpx           # cliente HTTP para tests de FastAPI
streamlit       # dashboard interactivo
plotly          # gráficos
pandas          # conversión inicial desde Excel
numpy           # cálculos numéricos
pytest          # tests
```
