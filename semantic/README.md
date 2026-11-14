# `semantic/`: modelo de datos semántico

Zona del agente `semantico`. Contiene contratos que consumen otras capas: el patrón de URIs, las formas SHACL y los datos de ejemplo. Cambiar cualquiera de ellos exige una PR propia (ver `Plan.md`, sección 4).

## Contenido

| Ruta | Qué es | Consumidores |
|---|---|---|
| `uris.md` | Patrón de URIs persistentes a partir de `BASE_URI` | `backend`, `frontend` |
| `shapes/dcat-ap-3-minimo.ttl` | Propiedades obligatorias de DCAT-AP 3 para `dcat:Dataset`, `dcat:DatasetSeries` y `dcat:Distribution` | `backend` (ingesta), `qa` |
| `shapes/itot-reglas.ttl` | Reglas propias de la unidad, cada una justificada en un comentario | `backend` (ingesta), `qa` |
| `examples/valid/` | Datos de ejemplo del prototipo que deben cumplir las formas | `backend`, `frontend`, `qa` |
| `examples/invalid/` | Un fichero por regla, que debe fallar exactamente en la forma indicada | `qa` |
| `data/sintetico/` | Datasets **sintéticos** del catálogo del prototipo para la puerta G2, un fichero por dataset (serie, versiones y distribuciones), marcados con `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>` | `backend` (comando de carga), `frontend`, `qa` |
| `data/vocab-minimo.ttl` | Esquemas de dominio (`it`, `ot`, `pqc`, `ia`), conceptos usados como temas y esquema de tipos de dataset. Mínimo hasta el SKOS de la fase 3 | `backend`, `frontend`, `qa` |
| `data/catalogo.ttl` | El `dcat:Catalog` «itot-catalogo» con sus series | `backend`, `frontend` |
| `scripts/validate.py` | Validación de todo lo anterior | CI, `qa` |

## Validar

Desde la raíz del repositorio:

```sh
uv run semantic/scripts/validate.py
```

El script declara sus dependencias (rdflib y pyshacl) con metadatos PEP 723, así que no hace falta instalar nada aparte de uv. Comprueba la sintaxis de todos los `.ttl`, que las formas sean SHACL válido, que los ejemplos válidos las cumplan y que cada ejemplo inválido falle exactamente en las formas que indican sus líneas `# expect-violation: <NombreLocal>`. Sale con código 1 si algo falla. El CI usa este mismo comando.

Para `data/`, valida cada fichero de `data/sintetico/` por separado (tal como lo ingesta el backend) y después todo `data/**/*.ttl` en un grafo. Sobre ese grafo conjunto hace además comprobaciones de coherencia que no son SHACL, porque cruzan datos y vocabulario: cada tema es un concepto de un esquema de dominio y los de una versión son de un solo dominio; las series y versiones de `data/sintetico/` llevan la marca de sintético; `dcat:inSeries`, `dcat:previousVersion`, `dcat:first` y `dcat:last` apuntan a recursos descritos de la misma serie; las URIs de versiones y distribuciones siguen `uris.md`; `dcat:accessURL` es la URI de la propia distribución, y el catálogo lista todas las series. Son reglas de los datos de este repositorio, no del contrato de ingesta: el backend puede recibir versiones cuyos conceptos están en otro grafo.

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

`[LICENCIA]`, `[CONTACTO]`, `[FECHA]` y `[PROYECTO]` no tienen valor real todavía. En los ejemplos, las propiedades que los llevarían (`dct:license`, `dcat:contactPoint`, `dct:issued`, `dct:modified`, `dct:isReferencedBy`) **se omiten** y quedan comentadas en su sitio. DCAT-AP espera IRIs o fechas en ellas: un literal `"[LICENCIA]"` rompería su rango y acabaría cargado en el triplestore como si fuera un dato. Cuando el responsable aporte los valores, se descomentan.
