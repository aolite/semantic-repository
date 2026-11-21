# `semantic/`: modelo de datos semántico

Zona del agente `semantico`. Contiene contratos que consumen otras capas: el patrón de URIs, las formas SHACL y los datos de ejemplo. Cambiar cualquiera de ellos exige una PR propia (ver `Plan.md`, sección 4).

## Contenido

| Ruta | Qué es | Consumidores |
|---|---|---|
| `uris.md` | Patrón de URIs persistentes a partir de `BASE_URI` | `backend`, `frontend` |
| `shapes/dcat-ap-3-minimo.ttl` | Propiedades obligatorias de DCAT-AP 3 para `dcat:Dataset`, `dcat:DatasetSeries`, `dcat:Distribution` y `dcat:Catalog` | `backend` (ingesta), `qa` |
| `shapes/itot-reglas.ttl` | Reglas propias de la unidad, cada una justificada en un comentario. Desde la decisión 49, también la pertenencia de cada serie a un solo catálogo y la lápida de los recursos dados de baja | `backend` (ingesta), `qa` |
| `shapes/ontologias-vocabularios.ttl` | Formas de `owl:Ontology` (propia y externa), `skos:ConceptScheme` y `skos:Concept`, cada regla justificada | `backend` (ingesta), `qa` |
| `examples/valid/` | Datos de ejemplo del prototipo que deben cumplir las formas | `backend`, `frontend`, `qa` |
| `examples/invalid/` | Un fichero por regla, que debe fallar exactamente en la forma indicada. En la raíz, los de datasets (los que pasan por la ingesta de datasets); en `ontologias-vocabularios/`, los de esquemas SKOS y ontologías; en `catalogos/`, los de catálogos, y en `bajas/`, los de lápidas (decisión 49) | `backend`, `qa` |
| `data/sintetico/` | Datasets **sintéticos** del catálogo del prototipo para la puerta G2, un fichero por dataset (serie, versiones y distribuciones), marcados con `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>` | `backend` (comando de carga), `frontend`, `qa` |
| `data/vocab-minimo.ttl` | Esquemas **auxiliares** del catálogo: `vocab/dominio` (los cuatro dominios del filtro) y `vocab/tipo-dataset` (marca de sintético). Desde la fase 3 ya no lleva los esquemas de dominio ni los temas | `backend`, `frontend`, `qa` |
| `vocabularios/{slug}.ttl` | Esquemas SKOS **de dominio** sintéticos (`it`, `ot`, `pqc`, `did`, `ia`), uno por fichero con sus conceptos. `ot` tiene los 13 conceptos del prototipo | `backend` (carga), `frontend`, `qa` |
| `vocabularios/corp/{slug}.ttl` | Esquemas SKOS **corporativos** sintéticos (`organizacion`, `financiacion`, `trl`, `sectores`) | `backend` (carga), `frontend`, `qa` |
| `ontologias/{slug}/{version}.ttl` | Ontologías propias sintéticas, una versión por fichero: `itot` 1.0.0, 1.1.0 y 1.2.0; `pqcm` 0.4.0 (borrador); `didx` 1.0.0 | `backend` (carga y métricas), `frontend`, `qa` |
| `ontologias/externas.ttl` | Ontologías externas (SAREF, SOSA/SSN, D3FEND), solo por referencia y con su IRI oficial | `backend`, `frontend` |
| `data/catalogo.ttl` | El `dcat:Catalog` raíz «itot-catalogo», que agrupa los catálogos con `dcat:catalog` (decisión 49) | `backend`, `frontend` |
| `data/catalogos/{slug}.ttl` | Un `dcat:Catalog` `{BASE_URI}catalogo/{slug}` por fichero, con sus series (`dcat:dataset`). Hoy solo `sintetico`, el de los tres datasets sintéticos **[PROPUESTA]** | `backend`, `frontend` |
| `data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}` | Ficheros **sintéticos** de distribución (fase 4): uno mínimo y marcado por cada distribución `PUBLIC` o `RESTRICTED` de `data/sintetico/`, ninguno para `NON_PUBLIC` | `backend` (`load-semantic` los sube), `qa` |
| `consultas/{id}.rq` | Consultas SPARQL de referencia de la Consola SPARQL (fase 4), con cabecera `# title:` / `# hint:` y el marcador `{BASE_URI}` | `backend` (`GET /sparql/queries`), `frontend`, `qa` |
| `scripts/ficheros_sinteticos.py` | Genera `data/sintetico/ficheros/` a partir de las distribuciones, sin red | `semantico`, `qa` |
| `scripts/validate.py` | Validación de todo lo anterior | CI, `qa` |

## Validar

Desde la raíz del repositorio:

```sh
uv run semantic/scripts/validate.py
```

El script declara sus dependencias con metadatos PEP 723, así que no hace falta instalar nada aparte de uv. Las versiones están fijadas (`rdflib==7.6.0` y `pyshacl==0.40.2`) y son las mismas del `uv.lock` del backend, para que el CI, el workflow de publicación y la ingesta validen igual. Si el backend las actualiza, hay que cambiarlas aquí también. Además fija `pyarrow==26.0.0`, que el backend no usa: `validate.py` regenera en memoria los ficheros sintéticos de distribución para compararlos, y el Parquet se escribe con pyarrow (ver más abajo). Comprueba la sintaxis de todos los `.ttl`, que las formas sean SHACL válido, que los ejemplos válidos las cumplan y que cada ejemplo inválido falle exactamente en las formas que indican sus líneas `# expect-violation: <NombreLocal>`. Sale con código 1 si algo falla. El CI usa este mismo comando.

Para `data/`, valida cada fichero de `data/sintetico/` por separado (tal como lo ingesta el backend) y después todo `data/**/*.ttl` en un grafo. Sobre ese grafo conjunto hace además comprobaciones de coherencia que no son SHACL, porque cruzan datos y vocabulario: cada tema es un concepto de un esquema de `vocabularios/` con dominio (`dct:subject`) y los de una versión son de un solo dominio; las series y versiones de `data/sintetico/` llevan la marca de sintético; `dcat:inSeries`, `dcat:previousVersion`, `dcat:first` y `dcat:last` apuntan a recursos descritos de la misma serie; las URIs de versiones y distribuciones siguen `uris.md`; `dcat:accessURL` es la URI de la propia distribución, y los catálogos son coherentes: el raíz agrupa con `dcat:catalog` todos los de `data/catalogos/` y no lista series, cada `data/catalogos/{slug}.ttl` describe solo `{BASE_URI}catalogo/{slug}`, ningún catálogo anida otros y todo `dcat:dataset` sale de uno de ellos hacia una serie descrita (que cada serie esté en exactamente un catálogo lo comprueba SHACL). Son reglas de los datos de este repositorio, no del contrato de ingesta: el backend puede recibir versiones cuyos conceptos están en otro grafo.

Para `vocabularios/` y `ontologias/`, valida cada fichero por separado (un fichero es un grafo con nombre) y comprueba además:

- **Esquemas:** la URI sale de la ruta (`vocabularios/{slug}.ttl` → `{BASE_URI}vocab/{slug}`, `vocabularios/corp/{slug}.ttl` → `{BASE_URI}vocab/corp/{slug}`); un esquema por fichero y ningún recurso bajo `BASE_URI` que no sea él o uno de sus conceptos; los de dominio tienen exactamente un `dct:subject` de `vocab/dominio` y los corporativos ninguno; slugs reservados (`corp`, `dominio`, `tipo-dataset`); marca de sintético.
- **Ontologías propias:** URI, `owl:versionIRI` y `owl:versionInfo` según la ruta (`ontologias/{slug}/{version}.ttl`); prefijo VANN igual al slug; `owl:priorVersion` hacia la versión inmediatamente anterior del repositorio (la primera no lleva) y `owl:backwardCompatibleWith` hacia versiones anteriores; términos solo en `{BASE_URI}onto/{slug}#`; `owl:imports` hacia ontologías de `externas.ttl`; clases externas declaradas y del espacio de nombres de una ontología externa; `dct:subject` hacia conceptos de `vocabularios/`; marca de sintético.
- **Externas:** IRI fuera de `BASE_URI`, sin `owl:versionIRI` ni `adms:status`.
- **Prefijos VANN** únicos entre todos los esquemas y ontologías.

Para `data/sintetico/ficheros/`, comprueba que hay un fichero por cada distribución `PUBLIC` o `RESTRICTED`, ninguno para las `NON_PUBLIC` ni ninguno que no corresponda a una distribución, y que cada uno es byte a byte el que genera `scripts/ficheros_sinteticos.py` (≤ 64 KB, con la marca `SINTETICO`). Si algún formato quedara pendiente (`PENDIENTES` del generador, hoy vacío), se informaría como `PENDIENTE` sin fallar.

Para `consultas/`, comprueba la cabecera `# title:` / `# hint:`, que no escriban el dominio ni otro marcador que `{BASE_URI}` y que, sustituido el marcador, cada consulta se analiza y se ejecuta con rdflib sobre `data/` (sin los ficheros de distribución), `vocabularios/` y `ontologias/` juntos. Informa del número de filas: son las de los datos sintéticos, no las del prototipo. Con los datos actuales, `mapeos` devuelve 0 filas, porque todos los destinos de los mapeos de `ot` son placeholders comentados.

## Ficheros sintéticos de distribución

```sh
uv run semantic/scripts/ficheros_sinteticos.py
```

Escribe `data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}` para cada distribución con `dct:accessRights` efectivo (el de la distribución o el de su versión) `PUBLIC` o `RESTRICTED`, y borra lo que sobre. Hay que ejecutarlo tras cambiar las distribuciones de `data/sintetico/`; `validate.py` falla si los ficheros no coinciden. Sin red, sin fechas ni azar: dos ejecuciones dan los mismos bytes. Los ficheros no contienen `BASE_URI`: se identifican por su clave de almacenamiento `{slug}/{version}/{dist}`. No reproducen tamaños, recuentos ni columnas del prototipo, que siguen como placeholder.

| Tipo de medio (`dcat:mediaType`) | Extensión | Contenido y marca |
|---|---|---|
| `application/vnd.tcpdump.pcap` | `.pcap` | libpcap clásico con un paquete Ethernet/IPv4/UDP entre direcciones de documentación (192.0.2.0/24, RFC 5737), marca de tiempo 0, y la marca en la carga útil. El formato clásico no admite comentarios ni nombres de interfaz (eso es pcapng, con otro tipo de medio). No es tráfico Modbus |
| `text/csv` | `.csv` | Columnas `sintetico,distribucion,nota` y una fila (RFC 4180, CRLF) |
| `application/json` | `.json` | Objeto con `sintetico: true`, `distribucion` y `nota` |
| `text/turtle` | `.ttl` | Comentario con la marca y un nodo en blanco con `rdfs:label` y `rdfs:comment`, sin IRIs propias |
| sin tipo IANA (NPZ, distribución `npz`) | `.npz` | Zip sin comprimir, como `numpy.savez`, con un array `SINTETICO` de `uint8` y la marca como comentario del zip. Se escribe sin NumPy |
| `application/vnd.apache.parquet` | `.parquet` | La misma tabla que el CSV (`sintetico` booleano, `distribucion` y `nota` texto, una fila) y la marca también en los metadatos clave-valor del esquema. Se escribe con `pyarrow==26.0.0` |

El Parquet es reproducible byte a byte porque el formato no guarda fechas de escritura y el generador fija todas las opciones que afectan a los bytes: formato 2.6, páginas de datos v1, sin compresión, sin diccionario, sin estadísticas, sin índice de páginas ni sumas de comprobación, sin el esquema Arrow serializado (`store_schema=False`) y un único grupo de filas. Lo único que depende del entorno es el campo `created_by` del pie (`parquet-cpp-arrow version 26.0.0`), así que el generador falla si la versión de pyarrow instalada no es la fijada (`PYARROW_VERSION`). Para cambiar de versión hay que actualizar a la vez las cabeceras PEP 723 de los dos scripts y `PYARROW_VERSION`, y regenerar.

`load-semantic` del backend los sube con la misma lógica que la API (`PUT …/distributions/{dist}/file`), con actor `cli`. El tipo de medio de la descarga sale del RDF, no del fichero.

## Etiquetas de Git (pipeline de publicación)

El catálogo solo publica versiones etiquetadas (`Plan.md`, sección 1). Cada etiqueta identifica un recurso y su versión, que es el `owl:versionInfo` del fichero:

| Recurso | Etiqueta | Ejemplo |
|---|---|---|
| Versión de ontología propia | `onto/{slug}/v{version}` | `onto/itot/v1.2.0` → `ontologias/itot/1.2.0.ttl` |
| Esquema de dominio | `vocab/{slug}/v{version}` | `vocab/ot/v1.0` → `vocabularios/ot.ttl` |
| Esquema corporativo | `vocab/corp/{slug}/v{version}` | `vocab/corp/financiacion/v2026.1` → `vocabularios/corp/financiacion.ttl` |

Al recibir una etiqueta, el workflow de publicación valida con `uv run semantic/scripts/validate.py` y crea una Release (decisión 37). **No carga nada en ningún entorno**: la carga es manual, con `load-semantic` del backend, que pone cada fichero en su grafo con nombre (ver «Ficheros, grafos con nombre y etiquetas Git» en `uris.md`). Las ontologías externas y los esquemas auxiliares de `data/vocab-minimo.ttl` no se etiquetan.

## Métricas OWL

El RDF **no lleva métricas** (clases, propiedades, axiomas, imports, perfil, consistencia): las calcula el backend en la ingesta (decisión del responsable, 2026-11-15). Las cifras del prototipo son de demostración. Al calcularlas hay que tener en cuenta que:

- Si una versión declara como `owl:Class` una clase externa que usa en un alineamiento (hoy ninguna), hay que contar solo las clases del espacio de nombres propio (`{BASE_URI}onto/{slug}#`).
- Los `owl:imports` (SOSA y SAREF en `itot`) apuntan a IRIs externas. Si el cálculo los resuelve, descarga esas ontologías de la red.

En local, sin imports, las cinco versiones cargan con owlready2 y son consistentes con Pellet y con HermiT (comprobación hecha al escribir la fase 3, no forma parte del CI).

Fase 4 (decisión 44): en `itot` 1.2.0, `itot:IED` pasa de `rdfs:subClassOf itot:Activo` a `rdfs:subClassOf itot:ActivoIndustrial`. Es una corrección de una versión ya publicada, así que el entorno local se recarga desde cero. Con `app.owl_metrics` del backend las métricas no cambian (13 clases, 8 axiomas lógicos, 2 imports, OWL 2 DL compatible con EL, QL y RL) y sigue siendo consistente con Pellet.

## `BASE_URI` en los ficheros RDF

Ningún `.ttl` declara `@base` ni escribe el dominio. Las URIs propias son relativas (`<dataset/modbus-tcp-testbed/2.1.0>`) y se resuelven contra `BASE_URI` al leer el fichero:

```python
graph.parse(path, format="turtle", publicID=base_uri)
```

El script toma `BASE_URI` del entorno y, si no está definida, usa el valor por defecto (`https://semantic.example.org/itot/`). Las formas quedan en `{BASE_URI}shapes#`, así que **el backend debe cargar formas y datos con la misma `BASE_URI`**.

## Catálogos y borrado lógico (decisión 49)

Varios catálogos, cada dataset en uno solo, y borrado lógico con 410. El patrón de URIs, la pertenencia, la lápida y qué pasa al borrar un catálogo con datasets están en «Catálogos y borrado lógico» de `uris.md`; todo es **[PROPUESTA]** pendiente de validar por el responsable. En resumen:

- `{BASE_URI}catalogo` conserva su URI y pasa a ser el catálogo raíz; los catálogos son `{BASE_URI}catalogo/{slug}` y las URIs de los datasets no cambian.
- El grafo que se ingesta con una serie lleva `<{BASE_URI}catalogo/{slug}> dcat:dataset <serie>` (forma `itsh:DatasetSeries-catalog`, exactamente uno).
- Un recurso dado de baja queda como lápida en el grafo `{BASE_URI}bajas` (no publicado): `rdf:type prov:Entity`, `dct:title`, `adms:status …/Withdrawn` y `prov:invalidatedAtTime` (forma cerrada `itsh:BajaShape`).
- **[PROPUESTA]** Un catálogo con datasets no se puede dar de baja (409): primero se mueven o se dan de baja sus datasets.

## Supuestos de validación

- Sin inferencia RDFS y sin la ontología DCAT en el grafo de datos (en DCAT 3, `dcat:DatasetSeries` es subclase de `dcat:Dataset`, y con esa jerarquía las reglas de versión se aplicarían también a las series).
- Las referencias a recursos que pueden estar en otro grafo (versión anterior, conceptos SKOS, serie) se comprueban como IRI, sin `sh:class`. Las distribuciones sí tienen que venir tipadas en el mismo grafo.

## Placeholders del prototipo

`[LICENCIA]`, `[CONTACTO]`, `[FECHA]` y `[PROYECTO]` no tienen valor real todavía. En ontologías y vocabularios se añaden `[AUTORES]`, `[REPOSITORIO GIT]`, `[VERSIÓN]` (D3FEND), `[RESPONSABLE]` y `[SISTEMA RRHH]` (esquemas corporativos), y los identificadores externos de los mapeos (`[QID]`, `[ID de activo]`, `[término]`…). Todos se **omiten** y quedan comentados donde irían. En los ejemplos, las propiedades que los llevarían (`dct:license`, `dcat:contactPoint`, `dct:issued`, `dct:modified`, `dct:isReferencedBy`) **se omiten** y quedan comentadas en su sitio. DCAT-AP espera IRIs o fechas en ellas: un literal `"[LICENCIA]"` rompería su rango y acabaría cargado en el triplestore como si fuera un dato. Cuando el responsable aporte los valores, se descomentan.
