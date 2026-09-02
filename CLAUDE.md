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
- **FASE 10** ✅ Despliegue en Streamlit Community Cloud ✅ — `resources/dim_partida.csv` fallback estático de jerarquía HS ✅ — Navegador en cascada disponible en modo file-upload (sin DB) ✅
- **FASE 11** ✅ Capa **Freemium** (estadística multi-país LATAM) ✅ — Ingesta + normalización de socios ✅ — Métricas de valor (YoY, share, concentración) ✅ — Precómputo offline ✅ — Selector de módulo + dashboard freemium de 4 pantallas ✅
- **FASE 12** ✅ Capa **Manifiestos** (constructor de tabla dinámica) ✅ — Lake parquet particionado + DuckDB ✅ — Prorrateo del valor de la DUA ✅ — Catálogo de 27 dimensiones y 14 métricas ✅ — Tabla cruzada y presets ✅ — Tema compartido en `src/theme.py` ✅

## Los tres módulos

La app abre en un **selector de módulo**, no en un file uploader:

| | Freemium — Comex Latam | Manifiestos — Constructor | Premium — Motor ISE |
|---|---|---|---|
| Data | 10 países LATAM, precomputada | Manifiestos Perú, precomputada | Transaccional, la sube el usuario |
| Granularidad | HS 6d × socio × mes | Guía / BL (documento de transporte) | HS 10d × importador × mes |
| Métricas | YoY, share, concentración | Las que arme el usuario | ISE, elasticidad, volatilidad, shock |
| Procesamiento | Ninguno (lee artefactos) | Ninguno (consulta DuckDB) | Pipeline completo en memoria |
| Entrada | `build_freemium.py` (offline) | `build_manifiestos.py` (offline) | `run.py` o file uploader |

`src/dashboard.py` decide con `st.session_state["view_mode"]` y delega en
`src/dashboard_freemium.py` o `src/dashboard_manifiestos.py`. **El flujo premium
quedó intacto**: si se toca `dashboard.py`, verificar que las 5 tabs siguen
renderizando.

Freemium y Manifiestos comparten identidad visual y por eso comparten
`src/theme.py` (paleta, formateadores, CSS, tarjetas KPI). El Motor ISE conserva
su tema oscuro de `.streamlit/config.toml`.

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
  # --- Capa freemium (FASE 11) — todo LazyFrame, sin UDFs de Python ---
  ingest_freemium.py    # scan_freemium_tree() / normalize_hs6() / load_freemium_source() / aggregate_freemium()
  cleaning_freemium.py  # normalize_partner() — unifica grafías de socio entre países (vectorizado)
  metrics_freemium.py   # compute_country_yearly / hs_yearly / partner_share / hhi / registros — solo sobre valor
  dashboard_freemium.py # render() — 4 pantallas (panorama / producto / concentración / registros)
  # --- Capa manifiestos (FASE 12) — lake parquet + DuckDB, sin procesar por sesión ---
  ingest_manifiestos.py   # parse_formato() / scan_manifiestos_dir() / load_manifiesto_source()
  cleaning_manifiestos.py # prorratear_valor_dua() / normalize_hs() / clean_manifiestos()
  pivot.py                # DIMENSIONES + METRICAS + run_pivot() / run_totales() / cobertura()
  dashboard_manifiestos.py# render() — constructor de tabla dinámica
  theme.py                # paleta C, formateadores y CSS compartidos freemium ↔ manifiestos
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
  test_ingest_freemium.py    # 22 tests — 4 variantes de esquema, HS 6d, descarte de actor
  test_cleaning_freemium.py  # 17 tests — unificación de socios entre países
  test_metrics_freemium.py   # 39 tests — YoY nulo sin año base, shares, concentración
  test_dashboard_freemium.py # 14 smoke tests con streamlit.testing — render real, BR y BO
  test_deploy_compat.py      # compila cada fuente con Python 3.11, la versión del deploy
  test_ingest_manifiestos.py    # 25 tests — 4 formatos, mapeo por formato, enteros "2.0"
  test_cleaning_manifiestos.py  # 31 tests — prorrateo de DUA, ceros de HS, grafías
  test_build_manifiestos.py     # 10 tests — lake particionado, rebuild sin rmtree
  test_pivot.py                 # 40 tests — catálogo, validación, cruce, cobertura
  test_dashboard_manifiestos.py # 22 smoke tests con AppTest — presets y expo_aereo
data/
  inbox/           # Parquets nuevos para ingestar (procesados → se mueven a inbox/done/)
  inbox/done/      # Parquets ya procesados (no se reprocesarán)
  raw/             # Archivos de referencia: HS2022_Jerarquia_Completa.xlsx (ignorados por git)
  interim/         # df_all.parquet — dataset combinado (ignorado por git)
  processed/       # econolens.duckdb, CSVs de output (ignorados por git)
  freemium/        # {PAIS}/{IM|EX}/{AÑO}.parquet — fuente estadística LATAM (ignorada por git)
  data-manifiestos/# CSV crudos de manifiestos Perú (ignorados por git)
  manifiestos/     # lake: periodo=/flujo=/via=/datos.parquet (ignorado por git)
resources/
  dim_partida.csv       # Jerarquía HS 2022 estática (5,633 filas) — fallback cuando no hay DB
  partner_aliases.yml   # Unificación de nombres de socio + buckets (no declarado / zona franca)
  freemium/             # Artefactos del precómputo freemium (versionados, ~42 MB)
    country_yearly.parquet  hs_yearly.parquet  partner_share.parquet
    partner_country.parquet  hhi.parquet  registros.parquet
    monthly_country.parquet  monthly_hs.parquet
    base/               # Base particionada por país (68 MB, NO versionada — se regenera)
.streamlit/
  config.toml      # Dark theme: #0f172a fondo, #38bdf8 acento
config.yml         # Schema canónico de ingesta premium: required/optional con aliases por fuente
config_freemium.yml # Schema canónico freemium: fecha, partner, hs_code, desc_aran, value
config_manifiestos.yml # Schema canónico manifiestos: mapeo POR FORMATO (no por alias global)
run.py             # Entrada premium: inbox → limpieza → arquetipos → pipeline ISE → agregaciones → dim_partida → DuckDB
build_freemium.py  # Entrada freemium: data/freemium/ → normalización → agregado → 8 tablas derivadas
build_manifiestos.py # Entrada manifiestos: data/data-manifiestos/ → lake parquet particionado
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

## Flujo de ingesta freemium

```
data/freemium/{PAIS}/{IM|EX}/{AÑO}.parquet
    → scan_freemium_tree() deriva país y flujo de la RUTA, no de una columna
    → load_freemium_source() resuelve columnas por alias de config_freemium.yml
    → normalize_hs6() castea Int64 → String y rellena a 6 dígitos
    → normalize_partner() unifica grafías de socio (resources/partner_aliases.yml)
    → aggregate_freemium() colapsa a periodo × país × flujo × hs × socio
→ 8 tablas derivadas en resources/freemium/ + DuckDB
```

Para agregar un país o un año:
1. Depositar el parquet en `data/freemium/{PAIS}/{IM|EX}/{AÑO}.parquet`
2. Si el esquema no calza, agregar el nombre real bajo `aliases` en `config_freemium.yml`
3. Correr `python build_freemium.py` — reconstruye todo desde cero, no es incremental

El dashboard **no procesa nada por sesión**: lee los artefactos ya calculados.
Si se toca `metrics_freemium.py`, hay que volver a correr el build para que el
cambio se vea.

## Flujo de ingesta de manifiestos

```
data/data-manifiestos/*_{im|ex}_{aereo|maritimo}_*.csv
    → parse_formato() deriva flujo y vía del NOMBRE del archivo
    → load_manifiesto_source() renombra con el mapeo POR FORMATO
      (config_manifiestos.yml), y completa con nulos lo que ese formato no trae
    → periodo y fecha salen de DIA/MES/AÑO
    → prorratear_valor_dua() reparte por peso el valor repetido de la DUA
    → normalize_hs() repone ceros iniciales y cuenta las partidas de la lista
    → clean_manifiestos() unifica grafías de transportista y almacén
→ data/manifiestos/periodo=/flujo=/via=/datos.parquet
```

El mapeo es **por formato y no por lista de alias** como en las otras dos capas:
los mismos nombres de columna significan cosas distintas según el archivo.
`EXPORTADOR` es el actor peruano en ex_aereo y la contraparte extranjera en
im_aereo; `CONSIGNATARIO` es el actor peruano en im_maritimo y el comprador
extranjero en ex_maritimo. Una lista global los cruzaría.

Para agregar un mes: dejar los CSV en `data/data-manifiestos/` y correr
`python build_manifiestos.py`. No es incremental, reconstruye todo.

## Datos — Capa manifiestos (FASE 12)

- Fuente: manifiestos de carga del Perú — 4 formatos (`{im|ex}` × `{maritimo|aereo}`),
  CSV con `;`, UTF-8. Mayo–julio 2026 = 251.162 filas. ~93k filas/mes, 31–48 columnas
- Estructura: el **flujo y la vía se derivan del nombre del archivo**; el **periodo
  sale de las columnas `DIA`/`MES`/`AÑO`**, no del nombre: tres formatos escriben
  `..._2026_7.csv` y ex_aereo escribe `..._072026_7.csv`
- Lake: `data/manifiestos/periodo=YYYY-MM/flujo=/via=/datos.parquet` (hive). 32,5 MB
  de CSV → 4,7 MB de parquet zstd; ~9 MB por mes completo. **No se versiona**
- **Una fila es una guía (aérea) o un conocimiento de embarque (marítimo), NO una
  declaración.** De ahí salen los dos problemas que definen el módulo:
- **El valor de la DUA viene repetido en todas sus filas.** La DUA
  `10-235-2026-113318` (INGRAM MICRO) consolida 22 guías aéreas y estampa USD 4,28 M
  en las 22: sumar la columna da USD 94 M. `prorratear_valor_dua` reparte el valor
  por peso, y la clave de reparto es `(dua, valor)` porque una misma DUA puede
  traer más de un valor declarado. Sin corregir, el FOB aéreo de julio se infla
  **47%** y el CIF total de importación 12%. Con el prorrateo, julio 2026 da
  **CIF 4,71 mil M USD**, la escala mensual real del Perú
- **El 39% de las guías declara más de una partida.** `PARTIDAS ARANCELARIAS` es una
  lista separada por comas y el valor no está desglosado por ninguna;
  `PARTIDA ARANCELARIA` (singular, 4 díg.) es la *representativa* y coincide con la
  primera de la lista solo el 72% de las veces. Por eso la grilla se queda a nivel
  de documento y se publican `n_partidas` y `multi_partida`, que permiten aislar
  los casos de una sola partida
- **Los códigos perdieron el cero inicial** al viajar como enteros (`604` = partida
  06.04). Se repone con `pad_start`. Validado contra `resources/dim_partida.csv`:
  **100% de las partidas de 4 díg. y 99,9% de las subpartidas son códigos reales**
- **Envoltorio de Excel**: `PARTIDAS ARANCELARIAS` llega como `="80440.0"` en
  ex_maritimo e im_aereo. Hay que quitar `="`, `"` y el `.0` antes de partir por comas
- **Los enteros cambian de formato entre meses**: mayo escribe los TEUs como `"2.0"`
  y junio/julio como `"2"`. Castear directo a Int64 anula los primeros — las
  importaciones marítimas de mayo sumaban 0 TEUs. Se castea Float64 → Int64
- **La misma entidad se escribe distinto entre formatos**: `UX- AIR EUROPA` (impo) vs
  `UX - AIR EUROPA` (expo); `5Y-ATLAS AIR INC` vs `INC.`; el almacén lleva código
  numérico en marítimo (`3306-ALMACENES MUNDO`) y no en aéreo. `clean_manifiestos`
  las unifica: 32 aerolíneas y 23 navieras, no el doble
- **Cobertura muy despareja — el valor NO está en todas las guías**, porque solo
  existe donde la guía cruzó con una DUA:

| Formato | FOB no nulo | HS no nulo | País | TEUs |
|---|---|---|---|---|
| impo marítimo | 96% (jun-jul), **57% (may)** | ídem | sí | sí |
| impo aéreo | 78–100% | 15–77% | sí | — |
| expo marítimo | **44–71%** | ídem | sí | sí |
| expo aéreo | **1–10%** ⚠ | **0,5–10%** ⚠ | **100% nulo** ⚠ | — |

- **Mayo es un extracto más flaco**: solo el 57% de sus guías marítimas de
  importación tiene DUA, contra 96% en junio y julio. No es un bug del pipeline —
  es la fuente. Comparar valor mes a mes sin mirar la cobertura da caídas falsas
- **En exportación la base sólida es peso / TEUs / contenedores, no el valor**: los
  1,30 mil M FOB de julio son ~20% de la exportación real peruana. El dashboard
  arranca en peso/TEUs y avisa el % de guías con dato cuando la selección toca FOB
- `expo_aereo` es el **caso de borde** de esta capa, el equivalente a Bolivia en
  freemium: sin país, sin puerto, casi sin valor ni HS. Todo cambio se prueba con él
- `TEUS` no es exactamente `cont_20 + 2×cont_40` (difieren 0,03%–1,7%): la fuente
  declara TEUs aparte y hay contenedores de 45 pies. Ambas métricas se publican

## Datos — Capa freemium (FASE 11)

- Fuente: 10 países LATAM (AR, BO, BR, CL, CO, HN, MX, PA, PE, UY), impo + expo, 2024–2025 — ~25M filas crudas
- Estructura: `data/freemium/{PAIS}/{IM|EX}/{AÑO}.parquet` — país y flujo se derivan de la ruta, no de una columna
- Cobertura: los 10 países tienen 2024 y 2025 completos. El código igual deriva países y años de lo que exista en disco: si falta el año base, el YoY es `null`, nunca 0
- Esquema canónico: `fecha`, `partner`, `hs_code` (6d), `desc_aran`, `value` — hay 4 variantes de nombres entre fuentes, resueltas por `aliases` en `config_freemium.yml`
- **`hs_code` llega como Int64 y con el largo del código NACIONAL, no a 6 dígitos**: AR usa NCM de 11, PA 12, PE/CO/HN 10, BR/CL/MX 8. Al venir como Int64 los capítulos 01–09 pierden el cero inicial, y **rellenar a 6 no lo repone**: hay que reponerlo respecto del largo nacional de esa fuente. `normalize_hs6` infiere ese largo por moda de la columna (no por máximo: BO/impo/2025 tiene outliers de 12 sobre una base de 11) y antepone el cero a las filas que quedaron con un dígito menos, antes de truncar a 6.
  Sin esto, `01039200191` (porcinos) se leía `103920` = cereales, y `07142090` (camote) se leía `714209` = piedras preciosas. Afectaba hasta el **33% de las filas de exportación de Chile** — justo los capítulos agrícolas. Validado contra `resources/dim_partida.csv`: 99.5% de las partidas resultantes son subpartidas HS válidas
- **CIF vs FOB nunca se suman**: `base_valor` es parte de la clave de agregación (impo→CIF, expo→FOB)
- **Las columnas de actor (`company`, `id_company`) existen en 8 de 10 países pero se descartan en la ingesta**: no están declaradas en `config_freemium.yml`, por lo que nunca llegan al agregado. El tachado/blur del diseño es decorativo, no un mecanismo de seguridad
- Socios: cada aduana escribe distinto al mismo país (`U.S.A`, `Estados Unidos de América`, `ESTADOS UNIDOS DE NORTEAMERICA`). `normalize_partner` los unifica (974 → 468) usando `resources/partner_aliases.yml`
- Buckets: `No declarado` (3.1% global, **14% en AR**) y `Zona franca / régimen especial` (0.8%). Se muestran, no se descartan; el HHI los excluye del cálculo y reporta `cobertura_pct`
- Métricas posibles: solo sobre valor (YoY, share, concentración). Sin cantidad no hay precio unitario → **no hay volatilidad, elasticidad ni ISE** en freemium
- **Concentración se publica como número efectivo de socios (10.000/HHI), no como HHI crudo.** A 6 dígitos el HHI mediano es 5.259: los cortes antimonopolio clásicos (1.500/2.500) dejan el 84% de las partidas en "alta" porque miden empresas dentro de un mercado, no países proveedores de un producto. Los cortes son sobre socios efectivos (1,5 / 3 / 6) y reparten 17/31/33/19%
- **Las pantallas de Producto, Concentración y Registros muestran el top 300 de cada país y flujo** (`partidas_relevantes`), con piso de 1M USD anuales para descartar ruido: 5.611 partidas con el **84.5% del comercio**. El panorama NO filtra: sus totales y su ranking de socios cubren el 100%.
  El corte es **relativo al propio país**, no absoluto: con un piso único de 50M USD, Brasil mostraba 1.210 partidas y Bolivia 33, y algún país-flujo se quedaba en 5. Ahora cada país muestra entre 416 y 600
- **Se ordena por `delta_socios`** (sustitución de origen 2024→2025), no por nivel: es la lectura que un dashboard genérico no da y el gancho natural hacia premium
- **Cobertura contra cifras oficiales (2024, verificado 2026-08-18, AMBOS flujos)** — la fuente NO cubre igual a todos los países:

| País | Expo nuestra | Expo oficial | Cob. | Impo nuestra | Impo oficial | Cob. | Fuente |
|---|---|---|---|---|---|---|---|
| Brasil | 337.0 | 337.0 | **100%** | 262.5 | 262.4 | **100%** | MDIC |
| Colombia | 49.6 | 49.6 | **100%** | 64.1 | 64.1 | **100%** | DANE |
| Perú | 68.4 | 74.1 | 92% | 54.9 | 55.0 | **100%** | BCRP / WITS |
| Chile | 97.5 | 100.2 | 97% | 75.0 | 78.0 | 96% | Banco Central |
| **Bolivia** | 5.1 | ~9.0 | **57%** ⚠ | 9.8 | 9.9 | 99% | INE / IBCE |
| **Uruguay** | 16.3 | 12.8 | **127%** ⚠ | 22.6 | ~13.5* | **~167%** ⚠ | Uruguay XXI |
| **Argentina** | 141.7 | 79.7 | **178%** ⚠ | 95.4 | 60.8 | **157%** ⚠ | INDEC |
| **México** | 115.5 | 617.1 | **19%** ⚠ | 223.1 | 625.3 | **36%** ⚠ | INEGI |
| Honduras | 5.9 | 5.7 nac. / 11.0 total | ⚠ def. | 13.0 | 19.6 | 66% ⚠ | BCH |
| Panamá | 1.6 | ~1.5 nacional | ⚠ def. | 15.4 | s/v | — | — |

  (miles de millones USD. *la cifra oficial de impo de UY excluye combustibles, no es
  directamente comparable. "def." = depende de la definición: HN y PA publican
  exportación nacional y total con maquila/zona franca por separado, y nuestra cifra
  se parece a la nacional)

- **El pipeline NO es la causa**: Brasil y Colombia calzan al 100% en ambos flujos con
  el mismo código. Los desvíos son de la fuente y de definiciones distintas.
- **Cuatro países con desvío grave**: AR inflado ~1.8x, MX cubre menos de la mitad,
  UY inflado (probablemente por zonas francas, que aparecen en los socios), BO con solo
  el 57% de sus exportaciones.
- **HN y PA dependen de la definición** de exportación (nacional vs. incluyendo
  maquila/reexportación de Zona Libre de Colón). Hay que decidir cuál se publica.
- **Solo BR, CO, PE y CL son presentables sin aclaración.**

## Datos — Capa premium

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

## Cómo trabajar en este proyecto

Conocimiento operativo que no se deduce leyendo el código, y que cuesta caro
redescubrir.

### El dashboard freemium no recalcula nada
Lee los artefactos de `resources/freemium/`. Si se toca `metrics_freemium.py`,
`cleaning_freemium.py` o `ingest_freemium.py`, **hay que correr
`python build_freemium.py`** o el cambio no se ve. Pasó: se arregló un bug de
concentración, se reinició la app y el error seguía en pantalla porque los
parquet eran los viejos.

### Streamlit no recarga módulos importados de forma confiable
Recarga `dashboard.py` al detectar cambios, pero `dashboard_freemium.py` puede
quedar en memoria con la versión anterior. **Ante un cambio ahí, reiniciar el
proceso** (`pkill -f "streamlit run"` y volver a levantar). Pasó: se agregó
Perú al mapa de países y la interfaz seguía mostrando `PE`.
El sidebar muestra `build <sha>` para saber qué versión está corriendo.

### Verificar el render, no leer el código
Los tests unitarios no ven los errores de esta capa, que son de datos: un nulo
inesperado en una columna. Usar `streamlit.testing.v1.AppTest`, que ejecuta el
render de verdad. Encontró tres bugs que 226 tests en verde no detectaban.

```python
at = AppTest.from_file("src/dashboard.py", default_timeout=300).run()
at.button[0].click().run()                      # entrar a freemium
at.session_state["fm_country"] = "BO"           # el valor crudo, no la etiqueta
at.session_state["fm_screen"] = "registros"
at.run()
assert not at.exception
```

`set_value()` en un widget con `format_func` espera el valor interno, no lo que
se ve en pantalla.

### Bolivia es el caso de borde
Economía chica, partidas sin descripción, y códigos con largos atípicos. Rompió
dos veces. Cualquier cambio en el dashboard se prueba con BO además del país por
defecto.

### El entorno de despliegue no es el local
Streamlit Cloud corre **Python 3.11** y el entorno local es más nuevo. Hay
sintaxis que compila acá y revienta allá — anidar f-strings con la misma comilla
es válida desde 3.12 y tumbó un deploy con 226 tests en verde.
`tests/test_deploy_compat.py` compila cada fuente con el intérprete 3.11 real;
`ast.parse(feature_version=(3,11))` NO sirve, el cambio es del tokenizer.

### Antes de tocar los datos, mirar los datos
Los dos bugs más graves (el cero inicial de los capítulos 01-09, y la
concentración infinita) no los delató una excepción ni un test: los delató
**leer las descripciones y ver que no tenían sentido**. "PARA REPRODUCCIÓN,
PUROS POR CRUZA" no puede ser un cereal. Ante una fuente nueva, inspeccionar
valores reales antes de escribir la transformación.

### Validar contra una referencia externa
`resources/dim_partida.csv` tiene las 5.633 subpartidas HS válidas: sirve para
comprobar que una normalización de códigos produjo partidas reales (hoy 99.5%).
Para los totales, las cifras oficiales de cada instituto — ver la tabla de
cobertura arriba.

### El repo está dentro de OneDrive
OneDrive bloquea carpetas mientras sincroniza y hace fallar operaciones de git
que borran directorios. Ante un checkout trabado: verificar que no haya proceso
git vivo, borrar `.git/index.lock`, y `git restore .`.

Lo mismo vale para el código: `shutil.rmtree` sobre una carpeta del repo falla
con `PermissionError [WinError 5]` y deja el directorio a medio borrar.
`build_manifiestos.py` reconstruye su lake borrando **archivos** y no carpetas
(`vaciar_lake`), justamente por esto. Un build que dejó menos filas de las
esperadas es el síntoma.

### Streamlit no deja escribir el estado de un widget ya instanciado
Los botones de preset del constructor no pueden hacer
`st.session_state["mf_filas"] = [...]` dentro del `if st.button(...)`: para ese
momento los selectores ya existen y Streamlit tira
`StreamlitAPIException`. Van como `on_click=`, que corre antes del rerun.

### AppTest devuelve pandas, no polars
`at.dataframe[0].value` es un `pandas.DataFrame` aunque el módulo trabaje con
Polars: `len(df)`, no `df.height`.

### El caso de borde de manifiestos es `expo_aereo`
Sin país, sin puerto de destino, con FOB en el 6% de las guías y HS en el 6%.
Es a esta capa lo que Bolivia es a la freemium. `tests/test_dashboard_manifiestos.py`
lo cubre; cualquier cambio en el constructor se prueba también contra él.

## Dependencias actuales

```
polars
duckdb
pyarrow
openpyxl
fastexcel
pyyaml      # lectura de config.yml y config_freemium.yml
pandas      # solo para conversión inicial en notebook
numpy
fastapi
uvicorn
httpx       # requerido por FastAPI TestClient
streamlit   # dashboard
plotly      # gráficos en el dashboard (solo premium; freemium dibuja con HTML/CSS)
# pytest solo en desarrollo (no en requirements.txt de producción)
# La capa freemium no agregó dependencias nuevas
```

## Comandos

```
python run.py                      # pipeline premium: inbox → DuckDB
python build_freemium.py           # precómputo freemium: data/freemium/ → resources/freemium/
python build_manifiestos.py        # lake manifiestos: data/data-manifiestos/ → data/manifiestos/
streamlit run src/dashboard.py     # dashboard (los tres módulos)
uvicorn src.api:app --reload       # API
pytest -v                          # 396 tests
```

## Despliegue

- Repo: `Aarontrade5050/econlens-sensitivity-engine`, branch `main`, main file `src/dashboard.py`
- Panel: https://share.streamlit.io → *Manage app* para ver logs en vivo
- En la nube **no existe** `econolens.duckdb`: el freemium lee sus parquet y el
  premium cae al file uploader. Verificado escondiendo la DB local.
- El repo pesa ~38 MB por los artefactos freemium, así que el primer clone del
  deploy tarda más de lo habitual
- `notebooks/` está gitignoreado: guardaba RUC y razón social de importadores en
  los outputs de las celdas

## Regla principal del proyecto

> No rediseñar mientras se ejecuta.
> Progreso > perfección. Consistencia > intensidad. Acumulación > entusiasmo.
