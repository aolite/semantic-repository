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
| Esquema SKOS de dominio | `{BASE_URI}vocab/{esquema}` | `skos:ConceptScheme` | `{BASE_URI}vocab/ot` | derivado |
| Esquema SKOS corporativo | `{BASE_URI}vocab/corp/{esquema}` | `skos:ConceptScheme` | `{BASE_URI}vocab/corp/financiacion` | **decisión del responsable (2026-11-15)** |
| Concepto SKOS | `{URI del esquema}/{slug}` | `skos:Concept` | `{BASE_URI}vocab/ot/modbus-tcp`, `{BASE_URI}vocab/corp/trl/trl-1` | prototipo |
| Ontología propia | `{BASE_URI}onto/{slug}` | `owl:Ontology` | `{BASE_URI}onto/itot` | derivado |
| Versión de ontología (`owl:versionIRI`) | `{BASE_URI}onto/{slug}/{version}` | — | `{BASE_URI}onto/itot/1.2.0` | prototipo |
| Término de ontología propia (clase, propiedad) | `{BASE_URI}onto/{slug}#{Nombre}` | `owl:Class`, `owl:ObjectProperty`… | `{BASE_URI}onto/itot#Controlador` | prototipo (`https://[DOMINIO]/itot/onto/itot#`) |
| Ontología externa | Su IRI oficial | `owl:Ontology` | `https://saref.etsi.org/core/` | prototipo |
| Esquema de dominios del catálogo | `{BASE_URI}vocab/dominio` | `skos:ConceptScheme` | `{BASE_URI}vocab/dominio` | **[PROPUESTA del orquestador, fase 3]** |
| Dominio del catálogo | `{BASE_URI}vocab/dominio/{it\|ot\|pqc\|ia}` | `skos:Concept` | `{BASE_URI}vocab/dominio/ot` | **[PROPUESTA del orquestador, fase 3]** |
| Fichero de una distribución | `{BASE_URI}dataset/{slug}/{version}/{dist}/fichero` | — | `{BASE_URI}dataset/modbus-tcp-testbed/2.1.0/pcap/fichero` | **[PROPUESTA del orquestador, fase 4]** |
| Endpoint SPARQL | `{BASE_URI}sparql` | — | `{BASE_URI}sparql` | prototipo |
| Consulta de referencia | `{BASE_URI}consulta/{id}` | — | `{BASE_URI}consulta/ot-datasets` | **[PROPUESTA del orquestador, fase 4]** |
| Catálogo | `{BASE_URI}catalogo` | `dcat:Catalog` | `{BASE_URI}catalogo` (`dct:identifier "itot-catalogo"`) | **[PROPUESTA]** |
| Esquema de tipos de dataset | `{BASE_URI}vocab/tipo-dataset` | `skos:ConceptScheme` | `{BASE_URI}vocab/tipo-dataset` | **[PROPUESTA del orquestador]** |
| Tipo de dataset | `{BASE_URI}vocab/tipo-dataset/{slug}` | `skos:Concept` | `{BASE_URI}vocab/tipo-dataset/sintetico` | **[PROPUESTA del orquestador]** |
| Formas SHACL | `{BASE_URI}shapes#{Nombre}` | `sh:NodeShape`, `sh:PropertyShape` | `{BASE_URI}shapes#DatasetShape` | **[PROPUESTA]** |

Detalles:

- `{dist}` es un slug único dentro de la versión. En el prototipo coincide con el formato (`pcap`, `csv`, `parquet`); es una convención recomendada, no una obligación.
- `{esquema}` es un slug. Los de dominio salen del prefijo del prototipo (`it`, `ot`, `pqc`, `did`, `ia`) y los corporativos, del final de su espacio de nombres en el prototipo (`organizacion`, `financiacion`, `trl`, `sectores`). `corp`, `dominio` y `tipo-dataset` están reservados: no pueden ser el slug de un esquema de dominio.
- La versión de una ontología sigue `{version}` (semver). La de un esquema SKOS no forma parte de su URI y admite dos o tres números (`1.0`, `2026.1`), porque así la da el prototipo (ver «Vocabularios y ontologías»).
- Una serie y sus versiones comparten `{slug}`: la URI de una versión es siempre la de su serie seguida de `/{version}`. Así, `dcat:inSeries` de una versión apunta a la URI que resulta de quitar el último segmento.
- La versión de dataset y la de ontología siguen la misma regla `{version}`, y `dcat:version` u `owl:versionInfo` llevan exactamente esa cadena.
- El catálogo es único, así que su URI no lleva slug. El identificador del prototipo, «itot-catalogo», va en `dct:identifier`.

## `dcat:accessURL` de las distribuciones

`dcat:accessURL` de cada distribución es **la URI de la propia distribución** (decisión del responsable, 2026-11-14): `{BASE_URI}dataset/{slug}/{version}/{dist}`. El prototipo no da URL de acceso. Desde la fase 4, al resolverla el backend devuelve los metadatos de la distribución (RDF por negociación de contenido, o 303 a la ficha HTML) y no el fichero. El fichero se descarga en `…/{dist}/fichero`, donde se aplica el control de acceso según el `dct:accessRights` efectivo (ver más abajo). `semantic/scripts/validate.py` comprueba que los datos de `semantic/data/` cumplen esta regla.

## Ficheros de distribución y derechos de acceso (fase 4)

### Ruta del fichero **[PROPUESTA del orquestador, fase 4]**

- `{BASE_URI}dataset/{slug}/{version}/{dist}/fichero` es la descarga del fichero de una distribución. Es su `dcat:downloadURL` **solo si** existe fichero, pero **no se escribe en el RDF publicado**: el RDF no cambia al subir un fichero, y la API la devuelve en `download_url`.
- `fichero` es un segmento fijo y queda reservado **[PROPUESTA]** de `semantico`: no puede ser el slug `{dist}` de una distribución, porque `{BASE_URI}dataset/{slug}/{version}/fichero` se confundiría con una distribución.
- Clave de almacenamiento: `{slug}/{version}/{dist}`, sin extensión, igual en disco y en R2. La extensión del nombre de descarga sale del `dcat:mediaType`.

### Qué significa cada `dct:accessRights` (decisión 40)

El `dct:accessRights` efectivo de una distribución es el suyo o, si no tiene, el de su versión. Los tres valores admitidos son los de la tabla europea `http://publications.europa.eu/resource/authority/access-right/` (la forma `itsh:Dataset-accessRights` ya obliga a declararlo en cada versión, así que no hace falta forma nueva):

| Valor | Significado | Fichero |
|---|---|---|
| `access-right/PUBLIC` | Abierto: cualquiera, también un lector anónimo, descarga el fichero | Sí, si se ha subido |
| `access-right/RESTRICTED` | Descarga directa para usuarios autenticados (miembro o superior), auditada | Sí, si se ha subido |
| `access-right/NON_PUBLIC` | Dataset de **defensa**: solo metadatos. El fichero nunca se sube, ni se sirve, ni está en este repositorio; queda en infraestructura de Eurecat | **Nunca** |

Los tres datasets sintéticos son hoy `RESTRICTED` en todas sus versiones; ninguno es `PUBLIC` ni `NON_PUBLIC`.

### Ficheros sintéticos

`semantic/data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}`: un fichero mínimo y marcado como sintético por cada distribución `PUBLIC` o `RESTRICTED` de `semantic/data/sintetico/`, generado sin red por `semantic/scripts/ficheros_sinteticos.py` (ver `semantic/README.md`). Ninguno para las `NON_PUBLIC`.

## Consultas de referencia (fase 4)

- Fichero `semantic/consultas/{id}.rq`, con `{id}` slug. Identificador `{BASE_URI}consulta/{id}` **[PROPUESTA del orquestador, fase 4]**: solo identifica la consulta, no se resuelve.
- Cabecera de metadatos en las primeras líneas, en comentarios: `# title: …` y `# hint: …`. Después pueden ir más comentarios.
- Los IRIs propios se escriben con el marcador literal `{BASE_URI}` (`<{BASE_URI}vocab/ot>`), que el backend sustituye al servirlas. Es el único marcador admitido.
- Las tres del prototipo (Consola SPARQL): `ot-datasets`, `sin-definicion` y `mapeos`. En el prototipo el esquema OT es `<https://[DOMINIO]/itot/vocab/ot/>`, con barra final; en el modelo es `{BASE_URI}vocab/ot`, sin ella.

## Dominios y esquemas de dominio

Los cuatro dominios del filtro de la pantalla Catálogo son conceptos del esquema auxiliar `{BASE_URI}vocab/dominio`, en `semantic/data/vocab-minimo.ttl` **[PROPUESTA del orquestador, fase 3]**:

| Dominio (prototipo) | Concepto | Esquemas de dominio |
|---|---|---|
| Seguridad IT | `{BASE_URI}vocab/dominio/it` | `{BASE_URI}vocab/it` |
| OT / ICS | `{BASE_URI}vocab/dominio/ot` | `{BASE_URI}vocab/ot` |
| PQC e identidad | `{BASE_URI}vocab/dominio/pqc` | `{BASE_URI}vocab/pqc` y `{BASE_URI}vocab/did` |
| IA adversaria | `{BASE_URI}vocab/dominio/ia` | `{BASE_URI}vocab/ia` |

- Cada esquema de dominio declara **un** `dct:subject` hacia su dominio. Los corporativos no llevan dominio.
- Los temas de los datasets (`dcat:theme`) son conceptos de esquemas de dominio, y **el dominio de un dataset es el `dct:subject` del esquema (`skos:inScheme`) de sus temas**. Los temas de una versión son de un solo dominio, aunque vengan de dos esquemas (`pqc` y `did`).
- **Cambio respecto a la fase 2:** el dominio ya no es el esquema. Su etiqueta es el `skos:prefLabel` del concepto de `vocab/dominio`, no la del esquema: `vocab/ot` se titula ahora «Protocolos y arquitectura OT», no «OT / ICS».

Las URIs de los conceptos de tema que ya usan los datasets no cambian:

| Concepto | `skos:prefLabel` @es | Esquema |
|---|---|---|
| `{BASE_URI}vocab/it/cwe` | CWE | `it` |
| `{BASE_URI}vocab/it/control-iso-27001` | Control ISO/IEC 27001 | `it` |
| `{BASE_URI}vocab/ot/modbus-tcp` | Modbus/TCP | `ot` |
| `{BASE_URI}vocab/ot/purdue-nivel-1` | Nivel 1 · Control básico | `ot` |
| `{BASE_URI}vocab/ia/evasion` | Evasión | `ia` |
| `{BASE_URI}vocab/ia/caja-blanca` | Caja blanca | `ia` |

Los slugs `it/cwe`, `it/control-iso-27001`, `ia/evasion` e `ia/caja-blanca` fueron **[PROPUESTA]** de `semantico` en la fase 2; los de `ot` salen del prototipo.

## Vocabularios y ontologías (fase 3)

### Ficheros, grafos con nombre y etiquetas Git

| Recurso | Fichero | Grafo con nombre | Etiqueta Git |
|---|---|---|---|
| Versión de ontología propia | `semantic/ontologias/{slug}/{version}.ttl` | su `owl:versionIRI`, `{BASE_URI}onto/{slug}/{version}` | `onto/{slug}/v{version}` |
| Ontologías externas (todas) | `semantic/ontologias/externas.ttl` | `{BASE_URI}onto/externas` | — |
| Esquema de dominio | `semantic/vocabularios/{slug}.ttl` | `{BASE_URI}vocab/{slug}` | `vocab/{slug}/v{version}` |
| Esquema corporativo | `semantic/vocabularios/corp/{slug}.ttl` | `{BASE_URI}vocab/corp/{slug}` | `vocab/corp/{slug}/v{version}` |
| Esquemas auxiliares (`dominio`, `tipo-dataset`) | `semantic/data/vocab-minimo.ttl` | cada esquema en el grafo de su URI: `{BASE_URI}vocab/dominio` y `{BASE_URI}vocab/tipo-dataset` | — |

Un fichero describe un solo esquema (con todos sus conceptos) o una sola versión de ontología. En la etiqueta Git, `{version}` es el `owl:versionInfo` del fichero (`onto/itot/v1.2.0`, `vocab/ot/v1.0`, `vocab/corp/financiacion/v2026.1`). Cada esquema tiene un fichero, el de su última versión, y las anteriores quedan en el historial de Git. Las ontologías tienen un fichero por versión porque la ficha muestra el historial con `owl:priorVersion`.

**Limpieza tras la fase 2:** en un Fuseki cargado en la fase 2 queda el grafo antiguo `{BASE_URI}vocab/`, que tenía `vocab-minimo.ttl` entero. La lectura ya no lo consulta y se puede borrar.

### Ontologías propias

- URI `{BASE_URI}onto/{slug}`, `owl:versionIRI {BASE_URI}onto/{slug}/{version}`, `owl:versionInfo "{version}"`, `owl:priorVersion` hacia la versión anterior (la primera no lleva) y, si procede, `owl:backwardCompatibleWith`.
- VANN: `vann:preferredNamespacePrefix "{slug}"` y `vann:preferredNamespaceUri <{BASE_URI}onto/{slug}#>`. El espacio de nombres es una **IRI**, no un literal: los ficheros usan IRIs relativas a `BASE_URI` y un literal no se resolvería. Que el prefijo sea el slug es **[PROPUESTA]**; así lo hace el prototipo (`itot`, `pqcm`, `didx`).
- Términos en `{BASE_URI}onto/{slug}#{Nombre}`. Solo lo que sale del prototipo (decisión del responsable, 2026-11-15): clases con `rdfs:label` en español (las traducciones en y ca son **[PROPUESTA]**), sin `rdfs:comment`, sin propiedades inventadas y con jerarquía solo cuando un texto del prototipo o una decisión del responsable la respalda, citado en un comentario. La única por decisión es `itot:IED rdfs:subClassOf itot:ActivoIndustrial` en `itot` 1.2.0 (decisión 44, fase 4).
- Si una versión usa una clase externa como destino de un alineamiento, la declara `owl:Class` en el propio fichero, para que sea OWL 2 DL sin cargar los imports. Hoy ninguna lo hace (los alineamientos con D3FEND son placeholder). **Al contar clases, el backend debe contar solo las del espacio de nombres propio.**
- `dct:subject` hacia los conceptos SKOS que usa la ontología (el navegador SKOS los muestra en «Recursos que usan este concepto»).
- Notas de versión en `adms:versionNotes`, como en los datasets.
- Las propiedades de metadatos (Dublin Core, ADMS, VANN, FOAF) se declaran `owl:AnnotationProperty`, y el publicador es un nodo en blanco solo con `foaf:name`.

### Ontologías externas

Solo por referencia, con su IRI oficial, en `semantic/ontologias/externas.ttl`: `dct:title`, `dct:description`, `owl:versionInfo` (la versión que muestra el prototipo), VANN y `dct:publisher`. **No llevan `owl:versionIRI` ni `adms:status`.**

### Tipo: cómo se deduce

| Tipo (prototipo) | En el RDF | Ubicación |
|---|---|---|
| Ontología propia | `owl:Ontology` con `owl:versionIRI` y URI bajo `{BASE_URI}onto/` | `ontologias/{slug}/{version}.ttl`; grafo `{BASE_URI}onto/{slug}/{version}` |
| Ontología externa | `owl:Ontology` sin `owl:versionIRI`, con IRI fuera de `BASE_URI` | `ontologias/externas.ttl`; grafo `{BASE_URI}onto/externas` |
| SKOS de dominio | `skos:ConceptScheme` con `dct:subject` hacia `{BASE_URI}vocab/dominio/…` | `vocabularios/{slug}.ttl`; grafo `{BASE_URI}vocab/{slug}` |
| SKOS corporativo | `skos:ConceptScheme` con URI bajo `{BASE_URI}vocab/corp/` y sin `dct:subject` | `vocabularios/corp/{slug}.ttl`; grafo `{BASE_URI}vocab/corp/{slug}` |

Los esquemas auxiliares `vocab/dominio` y `vocab/tipo-dataset` no tienen dominio ni cuelgan de `vocab/corp/`: no son de ningún tipo y **no se listan** en «Vocabularios y ontologías».

### Estado **[PROPUESTA]**

`adms:status` con el vocabulario de estados de ADMS (`http://purl.org/adms/status/`), limitado a los dos valores que el prototipo muestra para recursos propios:

| Estado (prototipo) | Valor |
|---|---|
| Publicada | `adms:status <http://purl.org/adms/status/Completed>` |
| Borrador | `adms:status <http://purl.org/adms/status/UnderDevelopment>` |
| Referenciada | Sin `adms:status`: es el estado de toda ontología externa |

Lo llevan las ontologías propias (cada versión) y todos los esquemas. Las formas SHACL no admiten otros valores (`Deprecated`, `Withdrawn`) hasta que la interfaz los contemple. En la ficha de ontología, «Actual» o «Sustituida» no es un estado: una versión está sustituida si otra la cita como `owl:priorVersion`.

### Versión de los esquemas SKOS **[PROPUESTA]**

`owl:versionInfo` con la versión del prototipo sin la «v» (`1.0`, `1.1`, `2026.1`, `0.3`). No es semver y no forma parte de la URI del esquema.

### Responsable de un esquema corporativo **[PROPUESTA]**

El valor es `[RESPONSABLE]` (decisión abierta 11), así que se **omite** y queda comentado en cada fichero corporativo con el patrón de atribución cualificada de DCAT 3:

```turtle
prov:qualifiedAttribution [
    a prov:Attribution ;
    prov:agent [RESPONSABLE] ;
    dcat:hadRole <http://inspire.ec.europa.eu/metadata-codelist/ResponsiblePartyRole/custodian>
] ;
```

## Marca de sintético **[PROPUESTA del orquestador]**

Los datasets de demostración de la puerta G2 llevan `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>` en la serie y en **cada** versión. El concepto tiene `skos:prefLabel "Dataset sintético"@es` y está en el esquema `{BASE_URI}vocab/tipo-dataset`. Los datos reales, que llegan en el piloto, no llevan esta marca.

Desde la fase 3, las ontologías propias (en la cabecera de cada versión) y los esquemas SKOS sintéticos llevan el **mismo** `dct:type`. Se reutiliza en lugar de crear un concepto hermano porque en DCAT un vocabulario también se cataloga como dataset y porque así el backend comprueba una sola IRI en todo el catálogo **[PROPUESTA]**. Las ontologías externas no la llevan: son reales.

## Datasets sintéticos (fase 2)

En `semantic/data/sintetico/`, un fichero por dataset con la serie, todas sus versiones y sus distribuciones. Los slugs de las series 2 y 3 son **[PROPUESTA]** de `semantico`.

| Serie | Slug | Dominio | Versiones | Distribuciones |
|---|---|---|---|---|
| Tráfico Modbus/TCP del banco de pruebas OT | `modbus-tcp-testbed` (prototipo) | `ot` | 1.0.0, 2.0.0, 2.1.0 | 1.0.0: `pcap`, `csv`. 2.0.0: ninguna. 2.1.0: `pcap`, `csv`, `parquet` |
| Hallazgos de auditorías y pruebas de intrusión | `hallazgos-auditorias-intrusion` | `it` | 1.3.0 | `csv`, `rdf` |
| Corpus de ejemplos adversarios en visión | `ejemplos-adversarios-vision` | `ia` | 0.9.0 | `npz`, `json` |

## Prefijos usados en el prototipo

| Prefijo | Espacio de nombres |
|---|---|
| `itotd:` | `{BASE_URI}dataset/` |
| `itota:` | `{BASE_URI}actividad/` |
| `ot:` | `{BASE_URI}vocab/ot/` |

| `itot:`, `pqcm:`, `didx:` | `{BASE_URI}onto/{itot\|pqcm\|didx}#` |
| `it:`, `pqc:`, `did:`, `ia:` | `{BASE_URI}vocab/{it\|pqc\|did\|ia}/` |
| `ecorg:`, `ecfund:`, `ectrl:`, `ecsec:` | `{BASE_URI}vocab/corp/{organizacion\|financiacion\|trl\|sectores}/` (en el prototipo, `https://[DOMINIO]/eurecat/vocab/…`; ver «Patrones») |
| `saref:`, `sosa:`, `d3f:` | Los oficiales: `https://saref.etsi.org/core/`, `http://www.w3.org/ns/sosa/`, `http://d3fend.mitre.org/ontologies/d3fend.owl#` |

Cada esquema y cada ontología declara su prefijo en `vann:preferredNamespacePrefix`, y `semantic/scripts/validate.py` comprueba que no se repitan.

Atención: en Turtle un nombre con prefijo no puede contener `/` sin escapar, así que `itotd:modbus-tcp-testbed/2.1.0` (tal como aparece en el prototipo) **no es Turtle válido**. Hay que escribir `itotd:modbus-tcp-testbed\/2.1.0` o la IRI completa (o relativa, ver abajo).

## Cómo se aplica `BASE_URI` a los ficheros RDF

Los ficheros `.ttl` de `semantic/` **no declaran `@base`** y escriben las URIs propias como IRIs relativas (`<dataset/modbus-tcp-testbed/2.1.0>`, `@prefix itotd: <dataset/> .`). Quien los lee les pasa `BASE_URI` como IRI base:

```python
graph.parse(path, format="turtle", publicID=base_uri)  # rdflib
```

Con Apache Jena: `riot --base="$BASE_URI" fichero.ttl`. Las IRIs absolutas (vocabularios externos, IANA, tablas de autoridad de la UE) no se ven afectadas.

## Pendiente

- URI de agentes (`dct:publisher`, `prov:wasAssociatedWith`): el prototipo muestra «Eurecat · Unidad IT&OT Security» pero no da su URI. Por ahora, los ejemplos usan un nodo en blanco, uno por fichero; al cargar varios ficheros en el triplestore quedan como agentes distintos con el mismo `foaf:name`. Lo mismo pasa con el publicador de las ontologías y los esquemas.
- URIs de entidades PROV intermedias (p. ej. «Capturas PCAP en bruto») y de actividades sin URI en el prototipo («Captura en banco de pruebas»): nodos en blanco por ahora.
- Si la versión de los esquemas SKOS debe ser semver, como la de las ontologías.
- Si se admiten versiones preliminares de SemVer.
- Qué devuelve cada URI al resolverla (negociación de contenido HTML / Turtle / JSON-LD) y cómo se sirve la descarga de una distribución restringida: lo implementa `backend` según el contrato de la fase 4 (decisiones 31 y 40).
