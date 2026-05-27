# EconoLens — Motor de Sensibilidad Económica

> Transforma datos de aduanas en métricas de riesgo estructural por producto e importador.

EconoLens es un motor de análisis cuantitativo que procesa importaciones Perú–USA (SUNAT) y produce un **Score de Sensibilidad Económica (ISE)** por producto y actor, detectando shocks, volatilidad y cambios estructurales en precio y volumen.

---

## Output principal

| periodo | actor | hs_code | volumen | precio | var_pct_volumen_mensual | var_pct_precio_mensual | volatilidad_precio_6m | elasticidad_simple | shock_compuesto_flag | ise_score | ise_nivel | narrativa |
|---------|-------|---------|---------|--------|------------------------|----------------------|----------------------|--------------------|---------------------|-----------|-----------|-----------|
| 2025-03 | EMPRESA_A | 2710200012 | 50000 | 2.50 | -18.4 | 11.2 | 0.23 | -1.64 | 1 | 78.5 | Alto | EMPRESA_A — shock compuesto detectado; redujo volumen un 18.4% ... (ISE Alto: 78.5) |

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
  database.py      # save_results() y load_results() — persistencia en DuckDB
  api.py           # FastAPI — endpoints REST para consultar resultados
  updater.py       # run_pipeline_auto() — detecta archivos nuevos y actualiza la DB
  dashboard.py     # Streamlit — visualización ISE con filtros y gráficos
  narratives.py    # generate_narrative() — texto automático por fila ISE
  io.py            # Conversión XLSX → Parquet
tests/             # 96 tests — pytest
data/
  raw/             # Excel originales de SUNAT (ignorados por git)
  interim/         # Parquets intermedios (ignorados por git)
  processed/       # econolens.duckdb y CSVs de output (ignorados por git)
run.py             # Script de entrada principal
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
- Filtros por producto (HS Code), importador y rango de fechas
- Métricas resumen: total de registros y conteo por nivel ISE
- Gráfico de ISE en el tiempo por actor o producto
- Tabla de resultados con columna de narrativa automática
- Panel de **Eventos destacados** con los registros ISE Alto

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

---

## Tests

```bash
pytest -v
```

96 tests distribuidos en:

| Archivo | Tests | Cubre |
|---------|-------|-------|
| `test_metrics.py` | 30 | Cálculo de métricas |
| `test_pipeline.py` | 22 | Orquestación del flujo |
| `test_validation.py` | 4 | Validación de input |
| `test_database.py` | 9 | Persistencia DuckDB |
| `test_api.py` | 10 | Endpoints FastAPI |
| `test_updater.py` | 9 | Pipeline automatizado |
| `test_narratives.py` | 18 | Generador de narrativas |

---

## Decisiones de diseño

**Polars sobre Pandas** — rendimiento significativamente mayor en datasets tabulares grandes; lazy evaluation donde aplica.

**DuckDB como base de datos** — embebida, sin servidor, ideal para analítica local con SQL completo. Cero configuración.

**FastAPI con dependency injection** — `get_db_path()` como dependencia inyectable permite sobrescribir la ruta de DB en tests sin modificar el código de producción.

**Pipeline automatizado con manifest JSON** — rastrea qué archivos ya fueron procesados para hacer append incremental a la DB sin duplicar datos.

**Narrativas por reglas** — texto generado sin LLM, determinista y auditable. Prioridad: shock → volumen → precio → volatilidad.

**TDD a lo largo de todo el proyecto** — cada módulo tiene tests escritos antes de la implementación (RED → GREEN).

---

## Datos

- **Fuente:** SUNAT — importaciones Perú desde USA 2025
- **Formato raw:** Excel (.xlsx) con columnas `PARTIDA ARANCELARIA`, `IMPORTADOR`, `US$ FOB`, `CANTIDAD`, `UNIDAD DE MEDIDA`, `DÍA`, `MES`, `AÑO`
- **Nota:** `PARTIDA ARANCELARIA` viene como Int64 en parquet — se castea a String antes del pipeline

---

## Dependencias

```
polars          # procesamiento de datos
duckdb          # base de datos embebida
pyarrow         # serialización parquet
openpyxl        # lectura de Excel
fastapi         # API REST
uvicorn         # servidor ASGI
httpx           # cliente HTTP para tests de FastAPI
streamlit       # dashboard interactivo
plotly          # gráficos
pandas          # conversión inicial desde Excel
numpy           # cálculos numéricos
pytest          # tests
```
