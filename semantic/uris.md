# Patrón de URIs persistentes

Contrato entre `semantico`, `backend` y `frontend`. Cambiarlo exige una PR propia.

## Base

Todas las URIs se construyen a partir de la variable de entorno `BASE_URI`.

- Valor por defecto: `https://semantic.example.org/itot/` (decisión de la fase 1 en `Plan.md`).
- Termina **siempre** en `/`. Si llega sin la barra final, se le añade antes de construir nada.
- El placeholder `[DOMINIO]` del prototipo (`https://[DOMINIO]/itot/`) equivale a `BASE_URI`.
- Nadie escribe el dominio a mano: ni en código, ni en RDF, ni en pruebas.

En este documento, `{BASE_URI}` representa ese valor y las llaves `{…}` son variables.

## Reglas de los segmentos

| Segmento | Regla | Expresión regular | Ejemplos |
|---|---|---|---|
| `{slug}` | Minúsculas ASCII, dígitos y guiones. Sin acentos, espacios, guiones bajos, guiones al principio o al final, ni guiones dobles | `^[a-z0-9]+(-[a-z0-9]+)*$` | `modbus-tcp-testbed`, `purdue-nivel-1` |
| `{version}` | Versión semántica `MAYOR.MENOR.PARCHE`, sin prefijo `v` ni ceros a la izquierda | `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$` | `2.1.0`, `1.2.0` |

- El slug **no se deriva mecánicamente del título**: el prototipo usa `extraccion-caracteristicas` para la actividad «Extracción de características y etiquetado». Lo fija quien publica el recurso y, una vez publicado, **no cambia**.
- Las versiones preliminares (`-rc.1`) y los metadatos de compilación (`+abc`) de SemVer no están admitidos por ahora (ver «Pendiente»).

## Patrones

Los patrones marcados con *(prototipo)* aparecen literalmente en la pantalla «Ficha de dataset». Los marcados con *(derivado)* no aparecen, pero se deducen de los anteriores, y los marcados con **[PROPUESTA]** son una decisión de `semantico` que se revisa en la PR.

| Recurso | Patrón | Tipo RDF | Ejemplo | Origen |
|---|---|---|---|---|
| Dataset (serie) | `{BASE_URI}dataset/{slug}` | `dcat:DatasetSeries` | `{BASE_URI}dataset/modbus-tcp-testbed` | prototipo |
| Versión de dataset | `{BASE_URI}dataset/{slug}/{version}` | `dcat:Dataset` | `{BASE_URI}dataset/modbus-tcp-testbed/2.1.0` | prototipo |
| Distribución | `{BASE_URI}dataset/{slug}/{version}/{dist}` | `dcat:Distribution` | `{BASE_URI}dataset/modbus-tcp-testbed/2.1.0/pcap` | prototipo |
| Actividad PROV | `{BASE_URI}actividad/{slug}` | `prov:Activity` | `{BASE_URI}actividad/extraccion-caracteristicas` | prototipo |
| Esquema SKOS | `{BASE_URI}vocab/{esquema}` | `skos:ConceptScheme` | `{BASE_URI}vocab/ot` | derivado |
| Concepto SKOS | `{BASE_URI}vocab/{esquema}/{slug}` | `skos:Concept` | `{BASE_URI}vocab/ot/modbus-tcp` | prototipo |
| Ontología propia | `{BASE_URI}onto/{slug}` | `owl:Ontology` | `{BASE_URI}onto/itot` | derivado |
| Versión de ontología (`owl:versionIRI`) | `{BASE_URI}onto/{slug}/{version}` | — | `{BASE_URI}onto/itot/1.2.0` | prototipo |
| Endpoint SPARQL | `{BASE_URI}sparql` | — | `{BASE_URI}sparql` | prototipo |
| Formas SHACL | `{BASE_URI}shapes#{Nombre}` | `sh:NodeShape`, `sh:PropertyShape` | `{BASE_URI}shapes#DatasetShape` | **[PROPUESTA]** |

Detalles:

- `{dist}` es un slug único dentro de la versión. En el prototipo coincide con el formato (`pcap`, `csv`, `parquet`); es una convención recomendada, no una obligación.
- `{esquema}` es un slug. Los esquemas de dominio del prototipo usan nombres cortos (`ot`); los nombres del resto de esquemas los fija `semantico` en la fase 3.
- Una serie y sus versiones comparten `{slug}`: la URI de una versión es siempre la de su serie seguida de `/{version}`. Así, `dcat:inSeries` de una versión apunta a la URI que resulta de quitar el último segmento.
- La versión de dataset y la de ontología siguen la misma regla `{version}`, y `dcat:version` u `owl:versionInfo` llevan exactamente esa cadena.

## Prefijos usados en el prototipo

| Prefijo | Espacio de nombres |
|---|---|
| `itotd:` | `{BASE_URI}dataset/` |
| `itota:` | `{BASE_URI}actividad/` |
| `ot:` | `{BASE_URI}vocab/ot/` |

Atención: en Turtle un nombre con prefijo no puede contener `/` sin escapar, así que `itotd:modbus-tcp-testbed/2.1.0` (tal como aparece en el prototipo) **no es Turtle válido**. Hay que escribir `itotd:modbus-tcp-testbed\/2.1.0` o la IRI completa (o relativa, ver abajo).

## Cómo se aplica `BASE_URI` a los ficheros RDF

Los ficheros `.ttl` de `semantic/` **no declaran `@base`** y escriben las URIs propias como IRIs relativas (`<dataset/modbus-tcp-testbed/2.1.0>`, `@prefix itotd: <dataset/> .`). Quien los lee les pasa `BASE_URI` como IRI base:

```python
graph.parse(path, format="turtle", publicID=base_uri)  # rdflib
```

Con Apache Jena: `riot --base="$BASE_URI" fichero.ttl`. Las IRIs absolutas (vocabularios externos, IANA, tablas de autoridad de la UE) no se ven afectadas.

## Pendiente

- URI de agentes (`dct:publisher`, `prov:wasAssociatedWith`): el prototipo muestra «Eurecat · Unidad IT&OT Security» pero no da su URI. Por ahora, los ejemplos usan un nodo en blanco.
- URIs de entidades PROV intermedias (p. ej. «Capturas PCAP en bruto») y de actividades sin URI en el prototipo («Captura en banco de pruebas»): nodos en blanco por ahora.
- Espacio de nombres de los términos de la ontología `itot` (`{BASE_URI}onto/itot#Clase` o `{BASE_URI}onto/itot/Clase`): se decide en la fase 3.
- Si se admiten versiones preliminares de SemVer.
- Qué devuelve cada URI al resolverla (negociación de contenido HTML / Turtle / JSON-LD) y cómo se sirve la descarga de una distribución restringida: lo decide `backend`.
