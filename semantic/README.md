# `semantic/`: modelo de datos semántico

Zona del agente `semantico`. Contiene contratos que consumen otras capas: el patrón de URIs, las formas SHACL y los datos de ejemplo. Cambiar cualquiera de ellos exige una PR propia (ver `Plan.md`, sección 4).

## Contenido

| Ruta | Qué es | Consumidores |
|---|---|---|
| `uris.md` | Patrón de URIs persistentes a partir de `BASE_URI` | `backend`, `frontend` |
| `shapes/dcat-ap-3-minimo.ttl` | Propiedades obligatorias de DCAT-AP 3 para `dcat:Dataset`, `dcat:DatasetSeries` y `dcat:Distribution` | `backend` (ingesta), `qa` |
| `shapes/itot-reglas.ttl` | Reglas propias de la unidad, cada una justificada en un comentario | `backend` (ingesta), `qa` |
| `shapes/ontologias-vocabularios.ttl` | Formas de `owl:Ontology` (propia y externa), `skos:ConceptScheme` y `skos:Concept`, cada regla justificada | `backend` (ingesta), `qa` |
| `examples/valid/` | Datos de ejemplo del prototipo que deben cumplir las formas | `backend`, `frontend`, `qa` |
| `examples/invalid/` | Un fichero por regla, que debe fallar exactamente en la forma indicada. En la raíz, los de datasets (los que pasan por la ingesta de datasets); en `ontologias-vocabularios/`, los de esquemas SKOS y ontologías | `backend`, `qa` |
| `data/sintetico/` | Datasets **sintéticos** del catálogo del prototipo para la puerta G2, un fichero por dataset (serie, versiones y distribuciones), marcados con `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>` | `backend` (comando de carga), `frontend`, `qa` |
| `data/vocab-minimo.ttl` | Esquemas **auxiliares** del catálogo: `vocab/dominio` (los cuatro dominios del filtro) y `vocab/tipo-dataset` (marca de sintético). Desde la fase 3 ya no lleva los esquemas de dominio ni los temas | `backend`, `frontend`, `qa` |
| `vocabularios/{slug}.ttl` | Esquemas SKOS **de dominio** sintéticos (`it`, `ot`, `pqc`, `did`, `ia`), uno por fichero con sus conceptos. `ot` tiene los 13 conceptos del prototipo | `backend` (carga), `frontend`, `qa` |
| `vocabularios/corp/{slug}.ttl` | Esquemas SKOS **corporativos** sintéticos (`organizacion`, `financiacion`, `trl`, `sectores`) | `backend` (carga), `frontend`, `qa` |
| `ontologias/{slug}/{version}.ttl` | Ontologías propias sintéticas, una versión por fichero: `itot` 1.0.0, 1.1.0 y 1.2.0; `pqcm` 0.4.0 (borrador); `didx` 1.0.0 | `backend` (carga y métricas), `frontend`, `qa` |
| `ontologias/externas.ttl` | Ontologías externas (SAREF, SOSA/SSN, D3FEND), solo por referencia y con su IRI oficial | `backend`, `frontend` |
| `data/catalogo.ttl` | El `dcat:Catalog` «itot-catalogo» con sus series | `backend`, `frontend` |
| `scripts/validate.py` | Validación de todo lo anterior | CI, `qa` |

## Validar

Desde la raíz del repositorio:

```sh
uv run semantic/scripts/validate.py
```

El script declara sus dependencias (rdflib y pyshacl) con metadatos PEP 723, así que no hace falta instalar nada aparte de uv. Comprueba la sintaxis de todos los `.ttl`, que las formas sean SHACL válido, que los ejemplos válidos las cumplan y que cada ejemplo inválido falle exactamente en las formas que indican sus líneas `# expect-violation: <NombreLocal>`. Sale con código 1 si algo falla. El CI usa este mismo comando.

Para `data/`, valida cada fichero de `data/sintetico/` por separado (tal como lo ingesta el backend) y después todo `data/**/*.ttl` en un grafo. Sobre ese grafo conjunto hace además comprobaciones de coherencia que no son SHACL, porque cruzan datos y vocabulario: cada tema es un concepto de un esquema de `vocabularios/` con dominio (`dct:subject`) y los de una versión son de un solo dominio; las series y versiones de `data/sintetico/` llevan la marca de sintético; `dcat:inSeries`, `dcat:previousVersion`, `dcat:first` y `dcat:last` apuntan a recursos descritos de la misma serie; las URIs de versiones y distribuciones siguen `uris.md`; `dcat:accessURL` es la URI de la propia distribución, y el catálogo lista todas las series. Son reglas de los datos de este repositorio, no del contrato de ingesta: el backend puede recibir versiones cuyos conceptos están en otro grafo.

Para `vocabularios/` y `ontologias/`, valida cada fichero por separado (un fichero es un grafo con nombre) y comprueba además:

- **Esquemas:** la URI sale de la ruta (`vocabularios/{slug}.ttl` → `{BASE_URI}vocab/{slug}`, `vocabularios/corp/{slug}.ttl` → `{BASE_URI}vocab/corp/{slug}`); un esquema por fichero y ningún recurso bajo `BASE_URI` que no sea él o uno de sus conceptos; los de dominio tienen exactamente un `dct:subject` de `vocab/dominio` y los corporativos ninguno; slugs reservados (`corp`, `dominio`, `tipo-dataset`); marca de sintético.
- **Ontologías propias:** URI, `owl:versionIRI` y `owl:versionInfo` según la ruta (`ontologias/{slug}/{version}.ttl`); prefijo VANN igual al slug; `owl:priorVersion` hacia la versión inmediatamente anterior del repositorio (la primera no lleva) y `owl:backwardCompatibleWith` hacia versiones anteriores; términos solo en `{BASE_URI}onto/{slug}#`; `owl:imports` hacia ontologías de `externas.ttl`; clases externas declaradas y del espacio de nombres de una ontología externa; `dct:subject` hacia conceptos de `vocabularios/`; marca de sintético.
- **Externas:** IRI fuera de `BASE_URI`, sin `owl:versionIRI` ni `adms:status`.
- **Prefijos VANN** únicos entre todos los esquemas y ontologías.

## Etiquetas de Git (pipeline de publicación)

El catálogo solo publica versiones etiquetadas (`Plan.md`, sección 1). Cada etiqueta identifica un recurso y su versión, que es el `owl:versionInfo` del fichero:

| Recurso | Etiqueta | Ejemplo |
|---|---|---|
| Versión de ontología propia | `onto/{slug}/v{version}` | `onto/itot/v1.2.0` → `ontologias/itot/1.2.0.ttl` |
| Esquema de dominio | `vocab/{slug}/v{version}` | `vocab/ot/v1.0` → `vocabularios/ot.ttl` |
| Esquema corporativo | `vocab/corp/{slug}/v{version}` | `vocab/corp/financiacion/v2026.1` → `vocabularios/corp/financiacion.ttl` |

Al recibir una etiqueta, el pipeline valida con `uv run semantic/scripts/validate.py` y el backend carga el fichero en su grafo con nombre (ver «Ficheros, grafos con nombre y etiquetas Git» en `uris.md`). Las ontologías externas y los esquemas auxiliares de `data/vocab-minimo.ttl` no se etiquetan.

## Métricas OWL

El RDF **no lleva métricas** (clases, propiedades, axiomas, imports, perfil, consistencia): las calcula el backend en la ingesta (decisión del responsable, 2026-11-15). Las cifras del prototipo son de demostración. Al calcularlas hay que tener en cuenta que:

- Cada versión declara como `owl:Class` las clases externas que usa en un alineamiento (p. ej. `d3f:DefensiveTechnique` en `itot` 1.2.0): hay que contar solo las clases del espacio de nombres propio (`{BASE_URI}onto/{slug}#`).
- Los `owl:imports` (SOSA y SAREF en `itot`) apuntan a IRIs externas. Si el cálculo los resuelve, descarga esas ontologías de la red.

En local, sin imports, las cinco versiones cargan con owlready2 y son consistentes con Pellet y con HermiT (comprobación hecha al escribir la fase 3, no forma parte del CI).

## `BASE_URI` en los ficheros RDF

Ningún `.ttl` declara `@base` ni escribe el dominio. Las URIs propias son relativas (`<dataset/modbus-tcp-testbed/2.1.0>`) y se resuelven contra `BASE_URI` al leer el fichero:

```python
graph.parse(path, format="turtle", publicID=base_uri)
```

El script toma `BASE_URI` del entorno y, si no está definida, usa el valor por defecto (`https://semantic.example.org/itot/`). Las formas quedan en `{BASE_URI}shapes#`, así que **el backend debe cargar formas y datos con la misma `BASE_URI`**.

## Supuestos de validación

- Sin inferencia RDFS y sin la ontología DCAT en el grafo de datos (en DCAT 3, `dcat:DatasetSeries` es subclase de `dcat:Dataset`, y con esa jerarquía las reglas de versión se aplicarían también a las series).
- Las referencias a recursos que pueden estar en otro grafo (versión anterior, conceptos SKOS, serie) se comprueban como IRI, sin `sh:class`. Las distribuciones sí tienen que venir tipadas en el mismo grafo.

## Placeholders del prototipo

`[LICENCIA]`, `[CONTACTO]`, `[FECHA]` y `[PROYECTO]` no tienen valor real todavía. En ontologías y vocabularios se añaden `[AUTORES]`, `[REPOSITORIO GIT]`, `[VERSIÓN]` (D3FEND), `[RESPONSABLE]` y `[SISTEMA RRHH]` (esquemas corporativos), y los identificadores externos de los mapeos (`[QID]`, `[ID de activo]`, `[término]`…). Todos se **omiten** y quedan comentados donde irían. En los ejemplos, las propiedades que los llevarían (`dct:license`, `dcat:contactPoint`, `dct:issued`, `dct:modified`, `dct:isReferencedBy`) **se omiten** y quedan comentadas en su sitio. DCAT-AP espera IRIs o fechas en ellas: un literal `"[LICENCIA]"` rompería su rango y acabaría cargado en el triplestore como si fuera un dato. Cuando el responsable aporte los valores, se descomentan.
