# Manifiestos — diccionario de métricas del buscador

Contrato entre el diseño y la implementación. Cada número que aparece en las
seis pantallas del módulo está definido aquí: qué columna usa, qué operación,
sobre qué universo, y qué significa. Si un número de la pantalla no está en
este documento, es un error del diseño, no una licencia del código.

Diseño de referencia: canvas «Buscador de Manifiestos».
Fuente de datos: `data/manifiestos/periodo=/flujo=/via=/datos.parquet`.
Motor: DuckDB sobre parquet hive-particionado (`src/pivot.py`).

---

## 1. Reglas que valen para todo el módulo

### 1.1 El recorte (`R`)

Todo número se calcula sobre un **recorte**, que es siempre esta cláusula:

```sql
WHERE periodo BETWEEN :desde AND :hasta      -- selector de la barra lateral
  AND flujo = :flujo                          -- del cuadrante elegido
  AND via   = :via                            -- del cuadrante elegido
  [AND <dimensión> IN (:valores)]             -- filtros del usuario, 0..n
```

Los cuatro cuadrantes (`impo`/`expo` × `maritimo`/`aereo`) **no se mezclan**
en ninguna pantalla salvo el buscador de resultados, que muestra una fila por
cuadrante. El motivo no es estético: cada formato trae columnas distintas y
coberturas distintas.

### 1.2 Una fila es un documento de transporte

Una fila del lake es **una guía aérea o un conocimiento de embarque**, no una
declaración y no un contenedor. De ahí:

- `COUNT(*)` cuenta documentos de transporte, y es la métrica `registros`.
- Los valores monetarios vienen repetidos por DUA y **ya llegan prorrateados
  por peso** desde `cleaning_manifiestos.prorratear_valor_dua`. El código de
  consulta los suma directo: **nunca vuelve a prorratear**.
- Las métricas de carga (peso, TEUs, contenedores) son propias de la fila y se
  suman tal cual.

### 1.3 Nulos

- Al **agrupar**: el nulo se etiqueta `(sin dato)` con
  `COALESCE(CAST(col AS VARCHAR), '(sin dato)')`. No se descarta, para que el
  total de la tabla siga cuadrando con el total del recorte.
- Al **contar entidades distintas**: `COUNT(DISTINCT col)` ignora los nulos.
  Es lo correcto — "23 navieras" son 23 navieras con nombre.
- Al **sumar**: `SUM` ignora nulos. Si toda la columna es nula el resultado es
  `NULL` y se muestra `—`, nunca `0`.

### 1.4 Qué métrica existe en qué cuadrante

Una métrica que el formato no trae **no se ofrece**: mostrarla daría una
columna entera de `—`.

| Métrica | Impo marítimo | Impo aéreo | Expo marítimo | Expo aéreo |
|---|---|---|---|---|
| `registros`, `documentos`, `duas`, `actores` | sí | sí | sí | sí |
| `peso_kg` | sí | sí | sí | sí |
| `peso_neto_kg` | sí | — | — | — |
| `teus`, `cont_20`, `cont_40`, `contenedores` | sí | — | sí | — |
| `fob_usd` | sí | sí | sí | sí ⚠ 6% |
| `cif_usd`, `flete_usd`, `seguro_usd` | sí | sí | — | — |
| `contraparte` (dimensión) | — | ~0% | sí | sí |
| `pais`, `puerto_desembarque` | sí | sí | sí | — |

La implementación **no codifica esta tabla**: la deriva en tiempo real con
`dimensiones_disponibles()` / `metricas_disponibles()`, que preguntan al lake
qué columnas tienen algún dato en el recorte vigente. La tabla es la
expectativa, no la regla.

### 1.5 Lo que nunca se suma

- **CIF y FOB no se suman entre sí** y no se suman entre flujos: la
  importación se declara CIF y la exportación FOB. Misma regla que la capa
  freemium.
- **TEUs y peso sí se pueden sumar entre cuadrantes** (misma unidad física).
  Es lo que hace la pantalla de resultados al mostrar «144.663 TEUs» de una
  naviera que opera en entrada y en salida.

---

## 2. Métricas base

Son las que el usuario elige en «Medir». Todas son una agregación de una
columna sobre el recorte.

| Clave | Etiqueta | SQL | Qué representa |
|---|---|---|---|
| `registros` | Guías / BL | `COUNT(*)` | Documentos de transporte. Cuántos embarques distintos. |
| `documentos` | Documentos únicos | `COUNT(DISTINCT documento)` | Igual que el anterior salvo que la fuente repita un número de documento. La diferencia con `registros` delata duplicados. |
| `duas` | DUAs únicas | `COUNT(DISTINCT dua)` | Declaraciones aduaneras involucradas. Menor que `registros` cuando una DUA consolida varias guías. |
| `actores` | Actores únicos | `COUNT(DISTINCT actor)` | Importadores o exportadores distintos. En la ficha de un operador logístico es **su cartera de clientes**. |
| `teus` | TEUs | `SUM(teus)` | Unidad equivalente a veinte pies, tal como la declara la fuente. **No es** `cont_20 + 2×cont_40`: difieren entre 0,03% y 1,7% porque existen contenedores de 45 pies. Se publican las dos. |
| `cont_20` | Contenedores 20' | `SUM(cont_20)` | Cajas de veinte pies. |
| `cont_40` | Contenedores 40' (FEU) | `SUM(cont_40)` | Cajas de cuarenta pies. |
| `contenedores` | Contenedores | `SUM(cont_20) + SUM(cont_40)` | **Cajas físicas**, sin equivalencia. Es la métrica que pide la pregunta "quién trae más contenedores". Distinta de TEUs: 100 cajas de 40' son 100 contenedores y ~200 TEUs. |
| `peso_kg` | Peso (kg) | `SUM(peso_kg)` | Peso bruto. Presente en el 100% de las guías de los cuatro formatos: es la base sólida del módulo. |
| `peso_neto_kg` | Peso neto (kg) | `SUM(peso_neto_kg)` | Solo impo marítimo. |
| `fob_usd` | FOB (USD) | `SUM(fob_usd)` | Valor de la mercadería sin flete ni seguro, ya prorrateado por peso entre las guías de su DUA. |
| `cif_usd` | CIF (USD) | `SUM(cif_usd)` | FOB + flete + seguro. Solo importación. Prorrateado. |
| `flete_usd` | Flete (USD) | `SUM(flete_usd)` | Prorrateado. |
| `seguro_usd` | Seguro (USD) | `SUM(seguro_usd)` | Prorrateado. |
| `n_partidas` | Partidas declaradas | `SUM(n_partidas)` | Cuántas partidas arancelarias declara el conjunto. Sirve para medir consolidación. |

**Agregaciones alternativas.** Todas las métricas numéricas admiten además
`AVG`, `MAX` y `MIN`; `registros` solo `COUNT`; `documentos`, `duas` y
`actores` solo `COUNT(DISTINCT)`. La etiqueta de la columna lleva el nombre de
la agregación cuando no es la propia (`Promedio de Peso (kg)`).

---

## 3. Métricas derivadas

Las que dan la lectura y no están en ninguna columna. **Cada una tiene un
denominador distinto y confundirlos es el error clásico del módulo**, así que
la etiqueta de pantalla siempre dice cuál es.

### 3.1 Participación de mercado — `share_mercado`

```sql
100.0 * <métrica del grupo> / <métrica de TODO el cuadrante en el periodo>
```

El denominador es el cuadrante completo y **no** el recorte de las filas: se
pasa aparte, en el argumento `denominador` de `buscador.ranking`. También
ignora las exclusiones de bucket — si el ranking excluye a las navieras, sus
TEUs siguen contando abajo. Por eso los porcentajes de un ranking excluido **no
suman 100%**, y la pantalla muestra el resto como una franja aparte.

Se lee: *"MAERSK mueve el 19,3% de los TEUs que entraron por vía marítima."*

Aparece en: tarjetas de cuadrante, mini rankings del buscador, resultados de
búsqueda, columna «Participación» del ranking, KPI de una ficha, columna «% de
la entrada marítima» de la tabla dinámica.

### 3.2 Reparto interno de una entidad — `share_interno`

```sql
100.0 * <métrica del grupo> / <métrica de la entidad de la ficha>
```

Mismo cálculo y **la misma función**: lo único que cambia es el denominador.
`buscador.ranking` sin `denominador` compara contra el propio recorte, así que
filtrando por un importador se obtiene su reparto interno. Es lo que muestran
los bloques «Con quién trabaja»: los porcentajes de navieras, agentes,
agencias y almacenes de un importador suman 100% (con `(sin dato)` incluido).

Que las dos lecturas salgan de una sola función es deliberado: la diferencia
entre «el 25,4% de Supermercados» y «el 1,3% del mercado» queda en un
argumento visible y no en dos consultas que se pueden desincronizar.

Se lee: *"El 25,4% de los TEUs de Supermercados Peruanos viajó con MAERSK."*

### 3.3 Participación capturada — `captura`

Solo en la ficha de un operador logístico (naviera, agente, agencia, almacén).
Para el operador `O` y cada cliente `c` de su cartera:

```sql
100.0 * SUM(métrica) FILTER (WHERE <rol> = :O) / SUM(métrica)
```

agrupando por `actor` sobre **todo el cuadrante**, no solo sobre las guías de
`O`. El numerador es lo que ese cliente mueve con `O`; el denominador es todo
lo que ese cliente mueve, con quien sea.

Se lee: *"De los 2.235 TEUs de Samsung, el 47,7% ya va con MAERSK."* Lo que
falta para 100% está en manos de otro.

Implementación: una sola consulta con `FILTER`, nunca dos consultas y una
división en Python — el denominador tiene que salir del mismo recorte.

### 3.4 Cuentas donde no está — `oportunidad`

El complemento del anterior, y el listado de prospección de la ficha:

```sql
SELECT actor,
       SUM(m) AS total,
       COALESCE(SUM(m) FILTER (WHERE <rol> = :O), 0) AS con_operador,
       COUNT(DISTINCT <rol>) AS alternativas
  FROM R
 GROUP BY actor
HAVING SUM(m) >= :piso                    -- 1.500 TEUs en el diseño
   AND COALESCE(SUM(m) FILTER (WHERE <rol> = :O), 0) / SUM(m) < :techo   -- 12%
 ORDER BY total DESC
```

`piso` y `techo` son parámetros de la pantalla, no constantes escondidas.

`alternativas` cuenta operadores **del mismo rol que el de la ficha**: en la de
una naviera son navieras, en la de una agencia de carga son agencias. Contar
siempre navieras respondía otra pregunta —en la ficha de KUEHNE + NAGEL decía
«usa 2 navieras», que no dice nada sobre su competencia—. Un `1` ahí es una
lectura fuerte: esa cuenta contrata directo y no terceriza.

### 3.5 Costo implícito — `usd_por_teu`, `usd_por_kg`

```sql
SUM(flete_usd) / NULLIF(SUM(teus), 0)      -- USD por TEU
SUM(cif_usd)   / NULLIF(SUM(peso_kg), 0)   -- USD por kilo
```

**Razón de sumas, no promedio de razones.** `AVG(flete_usd / teus)` daría el
mismo peso a un BL de un contenedor que a uno de cincuenta, y el número
dejaría de ser el costo del conjunto.

Nunca se muestra sin su cobertura al lado (§3.7): un promedio calculado sobre
el 82% de las guías no es la tarifa del mercado, es el promedio de lo que se
declaró. Y depende de la mezcla de rutas: los USD 890/TEU de MAERSK contra los
USD 1.536 del mercado no dicen que sea más barata, dicen que un cuarto de su
carga entra por transbordo en Balboa.

### 3.6 Cardinalidad — `n_<dimensión>`

```sql
COUNT(DISTINCT <dimensión>)
```

Da los "de 23 navieras", "de 70 depósitos", "de 334 agentes" del panel de
concentración, y las columnas «Navieras» y «Países» del ranking, que ahí se
calculan **por fila del ranking** (cuántas navieras usa ese importador).

### 3.7 Cobertura — `cobertura`

```sql
100.0 * COUNT(<columna>) / COUNT(*)
```

`COUNT(col)` cuenta no nulos. Es el porcentaje de guías del recorte que
declaran ese dato. Se muestra **siempre** que la selección toque una métrica
monetaria y la cobertura sea menor al 95%.

### 3.8 Mix de una dimensión categórica — `mix`

```sql
100.0 * COUNT(*) FILTER (WHERE dim = :valor) / COUNT(*)
```

Es el bloque de canal de la ficha. El nulo es una categoría propia y se
etiqueta **«Sin DUA cruzada»**, no «(sin dato)»: en canal, el nulo significa
exactamente eso y decirlo es información.

### 3.9 Concentración por tramos — `tramos`

```sql
WITH r AS (
  SELECT actor, SUM(m) c,
         ROW_NUMBER() OVER (ORDER BY SUM(m) DESC) rn
    FROM R WHERE <exclusiones> GROUP BY actor)
SELECT SUM(c) FILTER (WHERE rn <= 12)             AS top12,
       SUM(c) FILTER (WHERE rn BETWEEN 13 AND 100) AS top13_100,
       SUM(c) FILTER (WHERE rn > 100)              AS resto
  FROM r
```

Los tres tramos se dividen por el total del cuadrante **sin exclusiones**, así
que la franja que falta es exactamente la carga excluida (§4). Eso es
deliberado: el hueco es el dato.

### 3.10 Serie mensual — `serie`

`GROUP BY periodo` sobre el recorte, ordenado ascendente. La barra del mes más
alto va en naranja; el resto en azul claro. Cuando la serie acompaña a un
share, se calcula un share por mes con el denominador de ese mes.

---

## 4. Buckets y exclusiones

Cuatro valores de la fuente **no son empresas** y el módulo los marca. No se
borran nunca: se etiquetan y, donde corresponde, se excluyen con un
interruptor visible.

| Valor | Dónde | Qué es | Tratamiento |
|---|---|---|---|
| `A LA ORDEN`, `TO ORDER%` | `actor` | Conocimiento de embarque sin consignatario nombrado (2.507 BL, 8.964 TEUs) | Bucket. Excluido del ranking de importadores por defecto. |
| `EMBARQUE DIRECTO` | `agencia_carga` | No hubo agencia de carga: el dueño contrató directo con la naviera. Es el 68% de la columna. | Bucket. Se muestra siempre —es el dato más frecuente— pero etiquetado como "sin agencia". |
| `ZZ-OTRAS` | `transportista` aéreo | Cajón de sastre de la fuente (37,5% del peso aéreo de entrada) | Bucket. Se muestra con marca. |
| Filiales peruanas de navieras | `actor` | `MAERSK LINE PERU S.A.C.`, `MEDITERRANEAN SHIPPING COMPANY DEL PERU SAC`, `HAPAG-LLOYD ( PERU ) S.A.C.`, `CMA CGM PERU S.A.C.`, `OCEAN NETWORK EXPRESS (PERU) S.A.C.`, `WAN HAI LINES PERU S.A.C.`, `PACIFIC INTERNATIONAL LINES PERU S.A.C.`, `TERMINALES PORTUARIOS PERUANOS SAC` — consignatarias de su propia carga | Excluidas del ranking de importadores/exportadores por defecto, con interruptor. |

La lista de filiales vive en configuración, no en el código: es una lista que
va a crecer.

Con el interruptor puesto, el ranking de importadores de entrada marítima pasa
de 20.691 a **20.505** actores (186 nombres) y deja fuera el **21,0%** de los
contenedores. Los 186 no son 12: los prefijos atrapan las decenas de grafías de
`TO THE ORDER OF <banco>`, que la fuente escribe una por endosatario.

---

## 5. El buscador

### 5.1 Qué columnas se buscan

Un término se busca contra estas dimensiones, cada una un **rol** distinto:

| Rol mostrado | Columna | Métrica principal que se muestra |
|---|---|---|
| Importador / Exportador | `actor` | según cuadrante (§5.3) |
| Naviera / Aerolínea | `transportista` | ídem |
| Agente de aduana | `agente_aduana` | ídem |
| Agencia de carga | `agencia_carga` | ídem |
| Almacén | `almacen` | ídem |
| Agente portuario | `agente_portuario` | ídem |
| Contraparte extranjera | `contraparte` | ídem |
| País | `pais` | ídem |
| Puerto | `puerto_embarque`, `puerto_desembarque` | ídem |
| Nave / Vuelo | `nave_vuelo` | ídem |
| Partida | `partida_4d`, `desc_partida` | ídem |
| RUC | `ruc_actor` | ídem |

### 5.2 Regla de coincidencia

`WHERE upper(col) LIKE '%' || upper(:q) || '%'`, sin acentos normalizados en
esta fase. El término viaja **siempre como parámetro**, nunca interpolado.

Un resultado es la tupla `(rol, valor, cuadrante)`. La misma cadena puede
aparecer en varios roles y en varios cuadrantes: eso es una feature, es lo que
muestra que «maersk» es naviera, agente, agencia, consignataria y almacén a la
vez.

Orden: por métrica principal descendente dentro de cada rol; los roles se
ordenan por el volumen de su mejor coincidencia.

### 5.3 Métrica principal por cuadrante

Lo que se muestra como número grande de un resultado o de una tarjeta:

- **Marítimo** → `teus`. Es la unidad del negocio.
- **Aéreo** → `peso_kg` en toneladas. No hay contenedores.

Nunca el valor, porque la cobertura no lo permite.

---

## 6. Pantalla por pantalla

### 6.1 Buscador

| Elemento | Cálculo |
|---|---|
| Número grande de cada tarjeta de cuadrante | `SUM(teus)` (marítimo) o `SUM(peso_kg)/1000` en toneladas (aéreo), sobre el cuadrante y el periodo |
| «Conocimientos de embarque» / «Guías aéreas» | `COUNT(*)` |
| «Contenedores» | `SUM(cont_20) + SUM(cont_40)` |
| «Importadores» / «Exportadores» | `COUNT(DISTINCT actor)` |
| «Aerolíneas» | `COUNT(DISTINCT transportista)` |
| Mini ranking, valor | métrica principal del cuadrante, `GROUP BY` la dimensión, `ORDER BY` desc, `LIMIT 5` |
| Mini ranking, porcentaje | `share_mercado` (§3.1) |
| Mini ranking, nota al pie de cada fila | `COUNT(*)` y las cardinalidades de esa fila (§3.6) |
| «251.162 guías» de la barra lateral | `COUNT(*)` de los cuatro cuadrantes en el periodo |

### 6.2 Resultados de búsqueda

| Elemento | Cálculo |
|---|---|
| Recuadro de presencia: etiqueta | nombre del cuadrante donde aparece la coincidencia |
| Recuadro de presencia: número | métrica principal del cuadrante (§5.3) y su `share_mercado` |
| Número grande de la derecha | suma de la métrica principal **entre cuadrantes** — legítima solo para TEUs y peso (§1.5) |
| «6 coincidencias en 5 roles» | conteo de tuplas `(rol, valor)` distintas y de roles distintos |
| «45 importadores y 118 exportadores» | `COUNT(DISTINCT actor)` con el rol filtrado, por cuadrante |
| «11.º del ranking de agentes» | posición de la entidad en el ranking del rol por métrica principal |

> **La flecha de dirección no es una variación.** En la primera versión del
> diseño el icono de flujo quedaba pegado al porcentaje y se leía como una
> caída. Ahora el recuadro dice «Marítimo · Ingreso» en texto y el número va
> separado por una barra. Ningún porcentaje del módulo es un delta temporal
> salvo los que digan explícitamente "contra el mes anterior".

### 6.3 Quién mueve más

| Columna | Cálculo |
|---|---|
| Contenedores | `SUM(cont_20) + SUM(cont_40)` |
| 20' / 40' | `SUM(cont_20)` y `SUM(cont_40)` |
| TEUs | `SUM(teus)` |
| BL | `COUNT(*)` |
| Navieras | `COUNT(DISTINCT transportista)` de esa fila |
| Países | `COUNT(DISTINCT pais)` de esa fila |
| CIF | `SUM(cif_usd)`, `—` si la columna no existe en el cuadrante |
| Participación | `share_mercado` (§3.1) |

Las columnas **no son fijas**: se arman con `_columnas_ranking` según el
manifiesto y el eslabón. El aéreo no tiene contenedores y muestra Peso y Guías;
en el ranking de un operador la columna «Navieras» no dice nada y se cambia por
**«Clientes»** (`COUNT(DISTINCT actor)`). Las cajas de 20 y de 40 pies van en
una sola celda `20' / 40'`, como en el diseño: separarlas sumaba un track y la
grilla dejaba de entrar.

- Panel «El mercado está muy repartido»: tramos de §3.9 más la franja de lo
  excluido.
- Panel «Quién concentra de verdad»: para cada dimensión, el `share_mercado`
  de su primer valor y su cardinalidad (§3.6).
- Panel de costo: §3.5 con su cobertura.

### 6.4 Ficha de importador / exportador

| Elemento | Cálculo |
|---|---|
| KPI Contenedores, TEUs, BL, CIF | métricas base sobre `R AND actor = :entidad` |
| «1,3% de la entrada marítima» | `share_mercado` |
| «USD 1,65 por kilo» | `usd_por_kg` (§3.5) de la entidad |
| «1.229 DUAs» | `COUNT(DISTINCT dua)` |
| Bloques «Con quién trabaja» | `GROUP BY` el rol, con `share_interno` (§3.2) |
| «De dónde trae» | `GROUP BY pais`, `share_interno` |
| «Qué trae» | `GROUP BY partida_4d`, `share_interno` |
| Canal | `mix` (§3.8) |
| Serie mensual | `serie` (§3.10) |

### 6.5 Ficha de naviera / operador

| Elemento | Cálculo |
|---|---|
| KPI TEUs, Contenedores | métricas base sobre `R AND transportista = :entidad` |
| «19,3% del mercado · 1.ª de 23 navieras» | `share_mercado` + posición + cardinalidad |
| KPI Clientes | `COUNT(DISTINCT actor)` |
| KPI Flete implícito | `usd_por_teu` (§3.5) de la entidad, contra el del cuadrante |
| Tabla de clientes: TEUs, BL | métricas base agrupadas por `actor`, filtradas al operador |
| Tabla de clientes: «Total del cliente» | métrica del cliente en todo el cuadrante |
| Tabla de clientes: «Participación» | `captura` (§3.3) |
| «Cuentas donde no está» | `oportunidad` (§3.4) |
| «Por dónde entra» | `GROUP BY puerto_embarque`, `share_interno` |
| Serie mensual + share por mes | `serie` con `share_mercado` mensual |

### 6.6 Tabla dinámica

Es el constructor libre, y **no queda restringido a nada**. Llegar desde una
ficha solo **precarga un filtro**, que aparece como una etiqueta con × y se
quita en un clic.

| Elemento | Cálculo |
|---|---|
| «Agrupar por» | 1 a 3 dimensiones de las 27, de cualquier familia |
| «Abrir en columnas» | una cuarta dimensión como cruce, acotada al top 12 de valores por frecuencia |
| «Medir» | 1 a n métricas de §2, con su agregación |
| «Filtrar» | cualquier dimensión `IN` una lista de valores |
| Fila de KPIs | la métrica agregada sobre todo el recorte, no sobre las filas mostradas |
| Columna «% de la entrada marítima» | `share_mercado` |
| Fila «Total de la selección» | la métrica sobre todo el recorte. **Puede ser mayor que la suma de las filas visibles** cuando el resultado se recortó: la nota del encabezado lo dice |
| Título de la tarjeta | el cruce que se armó, «Naviera / Aerolínea × País», con la nota de filas y recorte a su derecha |
| Pie | tres acciones dibujadas y **deshabilitadas** (ver las guías una por una, guardar, descargar): quedaron fuera del alcance |
| Aviso de cobertura | §3.7 |

---

## 7. Casos de borde que la implementación tiene que respetar

1. **`expo_aereo`** no trae país ni puerto de destino, y su FOB cubre el 6% de
   las guías. Es el caso de prueba obligatorio de cada pantalla, como Bolivia
   en freemium.
2. **Junio 2026 no tiene `impo_aereo`** en el lake. Una serie mensual de ese
   cuadrante tiene un hueco real: se dibuja el hueco, no se interpola.
3. **Mayo 2026 es un extracto más flaco**: 57% de sus guías marítimas de
   entrada tiene DUA contra 96% en junio y julio. Cualquier serie de valor
   mes a mes tiene que mostrar la cobertura al lado.
4. **El RUC no identifica al importador marítimo.** `ruc_actor` trae el RUC de
   la declaración, no el del consignatario: Supermercados Peruanos aparece con
   10 RUC distintos. La identidad se resuelve por nombre y la ficha no muestra
   un RUC único en ese cuadrante.
5. **Un rango de periodos invertido** (desde > hasta) devuelve universo vacío:
   se avisa, no se falla.
6. **Nada de lo que elige el usuario entra al SQL por interpolación.** Las
   dimensiones, métricas y agregaciones se resuelven contra los catálogos de
   `src/pivot.py` (`ValueError` si no están) y los valores viajan como
   parámetros `?`.
7. **DuckDB liga los `?` por posición en el texto de la consulta**, y el
   `SELECT` va antes del `WHERE`: los parámetros de un cruce se agregan antes
   que los del filtro.
8. **`SUM` sobre `BIGINT` devuelve `DECIMAL(38,0)`** en DuckDB. Se castea a
   `Int64` (escala 0) o `Float64` antes de entregar el DataFrame.
