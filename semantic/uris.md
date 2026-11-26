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
| Catálogo raíz | `{BASE_URI}catalogo` | `dcat:Catalog` | `{BASE_URI}catalogo` (`dct:identifier "itot-catalogo"`) | **[PROPUESTA]** (fase 1); raíz fijo: **Decidido (2026-11-21, decisión 49)** |
| Catálogo | `{BASE_URI}catalogo/{slug}` | `dcat:Catalog` | `{BASE_URI}catalogo/sintetico`, `{BASE_URI}catalogo/vocabularios-sinteticos` | **Decidido (2026-11-21, decisión 49)**; el segundo ejemplo, **decisión 50 (2026-11-22)** |
| Grafo de bajas (lápidas) | `{BASE_URI}bajas` | — | `{BASE_URI}bajas` | **Decidido (2026-11-21, decisión 49)** |
| Esquema de tipos de dataset | `{BASE_URI}vocab/tipo-dataset` | `skos:ConceptScheme` | `{BASE_URI}vocab/tipo-dataset` | **[PROPUESTA del orquestador]** |
| Tipo de dataset | `{BASE_URI}vocab/tipo-dataset/{slug}` | `skos:Concept` | `{BASE_URI}vocab/tipo-dataset/sintetico` | **[PROPUESTA del orquestador]** |
| Formas SHACL | `{BASE_URI}shapes#{Nombre}` | `sh:NodeShape`, `sh:PropertyShape` | `{BASE_URI}shapes#DatasetShape` | **[PROPUESTA]** |

Detalles:

- `{dist}` es un slug único dentro de la versión. En el prototipo coincide con el formato (`pcap`, `csv`, `parquet`); es una convención recomendada, no una obligación.
- `{esquema}` es un slug. Los de dominio salen del prefijo del prototipo (`it`, `ot`, `pqc`, `did`, `ia`) y los corporativos, del final de su espacio de nombres en el prototipo (`organizacion`, `financiacion`, `trl`, `sectores`). `corp`, `dominio` y `tipo-dataset` están reservados: no pueden ser el slug de un esquema de dominio.
- La versión de una ontología sigue `{version}` (semver). La de un esquema SKOS no forma parte de su URI y admite dos o tres números (`1.0`, `2026.1`), porque así la da el prototipo (ver «Vocabularios y ontologías»).
- Una serie y sus versiones comparten `{slug}`: la URI de una versión es siempre la de su serie seguida de `/{version}`. Así, `dcat:inSeries` de una versión apunta a la URI que resulta de quitar el último segmento.
- La versión de dataset y la de ontología siguen la misma regla `{version}`, y `dcat:version` u `owl:versionInfo` llevan exactamente esa cadena.
- El catálogo raíz no lleva slug: es el de la fase 1, que conserva su URI y su `dct:identifier` «itot-catalogo». Los demás catálogos llevan `{slug}` (ver «Catálogos y borrado lógico»).
- Las URIs de los esquemas SKOS y de las ontologías propias **no llevan el catálogo**, igual que las de los datasets: moverlos de catálogo no rompe ninguna URI (ver «Vocabularios y ontologías en los catálogos»).

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

## Catálogos y borrado lógico (decisión 49)

Decidido por el responsable (2026-11-21): varios `dcat:Catalog`, cada dataset en **un solo** catálogo, creados, editados y borrados desde la aplicación por el editor y el admin; borrado **lógico**, con 410 Gone y ficha mínima en la URI, y los ficheros eliminados. Las versiones publicadas siguen siendo inmutables (decisión 28). El responsable validó el mismo día las propuestas de `semantico` sobre el catálogo raíz fijo, el patrón `catalogo/{slug}`, las URIs de los datasets sin catálogo, el catálogo «sintetico» con su título y el 409 al borrar un catálogo con datasets, y después la lápida del borrado lógico (grafo `bajas`, solo para catálogo y serie, 410 por prefijo y slugs no reutilizables): van marcadas **Decidido (2026-11-21, decisión 49)**. Lo demás de esta sección sigue siendo **[PROPUESTA]** de `semantico`.

### Patrón de URIs de los catálogos · Decidido (2026-11-21, decisión 49)

| Recurso | URI | Grafo con nombre | Fichero en `semantic/` |
|---|---|---|---|
| Catálogo raíz | `{BASE_URI}catalogo` | `{BASE_URI}catalogo` | `data/catalogo.ttl` |
| Catálogo | `{BASE_URI}catalogo/{slug}` | `{BASE_URI}catalogo/{slug}` | `data/catalogos/{slug}.ttl` **[PROPUESTA]** |
| Lápidas de los recursos dados de baja | — | `{BASE_URI}bajas` | ninguno (los escribe el backend) |

- **El catálogo actual no rompe su URI.** `{BASE_URI}catalogo` sigue existiendo, sigue siendo un `dcat:Catalog` con el mismo título, descripción e identificador, y se convierte en el **catálogo raíz**: el de todo el repositorio. Ya no lista series con `dcat:dataset`; agrupa los catálogos con `dcat:catalog` (DCAT 3 y DCAT-AP 3 lo prevén para catálogos dentro de un catálogo). Las series siguen siendo alcanzables desde él: raíz → `dcat:catalog` → `dcat:dataset`.
- El raíz es **único y fijo**: no se crea, edita ni borra desde la aplicación; cambia solo con `data/catalogo.ttl` y `load-semantic`. Al crear un catálogo, el backend añade `<{BASE_URI}catalogo> dcat:catalog <{BASE_URI}catalogo/{slug}>` al grafo del raíz; al darlo de baja, lo quita.
- **[PROPUESTA]** **Un solo nivel**: los catálogos `catalogo/{slug}` no agrupan otros catálogos (sin `dcat:catalog`) y el raíz no lista series.
- `{slug}` sigue la regla general y lo fija quien crea el catálogo; una vez creado **no cambia**. Nada cuelga de `catalogo/{slug}/`.
- **Las URIs de los datasets no llevan el catálogo.** `{BASE_URI}dataset/{slug}` no cambia, así que un dataset se puede mover de catálogo sin romper ninguna URI, y el slug de un dataset es único en todo el repositorio, no por catálogo.
- Alternativas descartadas: (a) dejar `{BASE_URI}catalogo` como un catálogo más, sin slug, con los datasets actuales, y crear los nuevos en `catalogo/{slug}`: el backend tendría que tratar para siempre un catálogo sin slug, y si se borrara, `catalogo/{slug}` colgaría de una URI que responde 410; (b) `{BASE_URI}catalogo/{slug}` para todos, también el actual: rompe la URI persistente del catálogo de la fase 1; (c) meter el catálogo en la URI del dataset (`catalogo/{slug}/dataset/{slug}`): moverlo de catálogo rompería todas sus URIs.
- **[PROPUESTA]** Un catálogo `{slug}` contiene: `dct:title`, `dct:description` y `dct:publisher` (obligatorios en DCAT-AP 3, forma `itsh:CatalogShape`) y un `dcat:dataset` por serie (forma `itsh:ItotCatalogShape`). Puede estar vacío: DCAT-AP 3 no exige `dcat:dataset`.

### Pertenencia de un dataset a su catálogo **[PROPUESTA]**

Que cada dataset pertenece a un solo catálogo es de la decisión 49; cómo se expresa en RDF y en la ingesta es **[PROPUESTA]**.

- El dataset que pertenece al catálogo es la **serie** (`dcat:DatasetSeries`, la ficha). Sus versiones pertenecen a él por `dcat:inSeries` y no se listan en el catálogo.
- Se expresa con `<{BASE_URI}catalogo/{slug}> dcat:dataset <{BASE_URI}dataset/{slug}>`. DCAT no define la relación inversa, así que **el grafo que se ingesta lleva ese triple** y la forma `itsh:DatasetSeries-catalog` exige exactamente uno por serie (`sh:inversePath dcat:dataset`, 1..1). El backend lo guarda en el grafo del catálogo, no en el de la serie; si la API recibe el catálogo como parámetro, puede añadir el triple antes de validar.
- Que la serie no esté ya en **otro** catálogo del triplestore lo comprueba el backend: SHACL solo ve el grafo que valida.
- **Mover un dataset de catálogo** es editar metadatos de la serie: se quita el triple del catálogo de origen y se añade al de destino. No cambia ninguna URI ni ninguna versión publicada.

### Borrado lógico: la lápida · Decidido (2026-11-21, decisión 49)

Al dar de baja un catálogo o un dataset, su descripción sale de los grafos publicados (el grafo de la serie o del catálogo se borra, y el triple que lo enlazaba desde su catálogo o desde el raíz se quita), sus ficheros se eliminan y queda una **lápida** en el grafo `{BASE_URI}bajas`. Ese grafo no está entre los publicados: no aparece en SPARQL (decisión 42) ni en los listados. Solo lo lee el backend para responder 410.

```turtle
<dataset/modbus-tcp-testbed>
    a prov:Entity ;
    dct:title "Tráfico Modbus/TCP del banco de pruebas OT"@es ;
    adms:status <http://purl.org/adms/status/Withdrawn> ;
    prov:invalidatedAtTime "…"^^xsd:dateTime .
```

| Triple | Vocabulario | Para qué |
|---|---|---|
| `prov:invalidatedAtTime` (1, `xsd:dateTime`) | PROV-O | Fecha de baja. Identifica la lápida (la forma `itsh:BajaShape` se aplica a todo sujeto que la tenga) |
| `adms:status <http://purl.org/adms/status/Withdrawn>` (1) | Estados de ADMS, el mismo vocabulario de las ontologías y los esquemas | Estado «retirado» |
| `dct:title` (1..n) | Dublin Core | Título que tenía, para la ficha mínima |
| `rdf:type prov:Entity` (solo ese) | PROV-O | Dominio de `prov:invalidatedAtTime` |

- La forma es **cerrada**: la lápida no lleva nada más. Ni descripción, ni distribuciones, ni quién la borró (eso va a la auditoría de PostgreSQL, no al RDF).
- **Pierde su tipo DCAT** (`dcat:Catalog`, `dcat:DatasetSeries`): con él, las formas de DCAT-AP le exigirían descripción, catálogo, etc. Qué era se deduce de la URI: `catalogo/{slug}` es un catálogo y `dataset/{slug}`, un dataset.
- Solo tienen lápida el catálogo y la serie, que son lo que se borra. Las URIs que cuelgan de una serie dada de baja (`dataset/{slug}/{version}`, `…/{dist}` y `…/{dist}/fichero`) responden también 410, con la ficha de la serie: el backend las resuelve por el prefijo.
- Las versiones no se borran una a una: son inmutables (decisión 28).
- **El slug de un recurso dado de baja no se reutiliza**: su URI responde 410 para siempre. Crear un catálogo o un dataset con ese slug da 409.
- `Withdrawn` solo se admite en las lápidas: las ontologías y los esquemas siguen limitados a `Completed` y `UnderDevelopment` (ver «Estado»), un `dcat:Catalog`, una `dcat:DatasetSeries` o un `dcat:Dataset` vivo no puede llevarlo (formas `itsh:Catalog-status`, `itsh:DatasetSeries-status` e `itsh:Dataset-status`) y todo sujeto con `adms:status` `Withdrawn` necesita `prov:invalidatedAtTime` (forma `itsh:RetiradoShape`), así que no hay lápidas sin fecha.

### Qué comprueban las formas y qué comprueba el backend

Las formas SHACL no conocen `BASE_URI` (los patrones literales no se resuelven contra ella) ni ven más que el grafo que validan. Lo que cabe en SHACL está en las formas:

| Regla | Forma |
|---|---|
| La URI de un catálogo termina en `/catalogo` o `/catalogo/{slug}` | `itsh:CatalogUriShape` |
| La URI de una lápida termina en `/catalogo/{slug}` o `/dataset/{slug}` (desde la decisión 50, también `/vocab/{slug}`, `/vocab/corp/{slug}` u `/onto/{slug}`) | `itsh:BajaUriShape` |
| El título de una lápida no está vacío | `itsh:Baja-title` (`sh:minLength 1`) |
| Cada serie, en exactamente un catálogo del grafo | `itsh:DatasetSeries-catalog` |
| `Withdrawn` solo en lápidas, y siempre con fecha | `itsh:*-status`, `itsh:RetiradoShape` |

**Reglas que el backend tiene que comprobar** en la ingesta y en el CRUD, porque no son SHACL (`semantic/scripts/validate.py` comprueba las que aplican sobre `semantic/data/`, pero no es contrato de ingesta):

1. Las URIs de catálogos y lápidas **empiezan por `BASE_URI`**: `{BASE_URI}catalogo`, `{BASE_URI}catalogo/{slug}` o `{BASE_URI}dataset/{slug}`, con `{slug}` válido.
2. El catálogo raíz es único y fijo: la API no lo crea, ni lo edita, ni lo borra, y **no lista series** (`dcat:dataset`).
3. **[PROPUESTA]** **Un solo nivel**: solo el raíz lleva `dcat:catalog`, y solo hacia catálogos `catalogo/{slug}` existentes.
4. `dcat:dataset` sale **solo de un catálogo `catalogo/{slug}` existente** y apunta a una serie existente.
5. La serie no está ya en **otro** catálogo del triplestore (SHACL solo ve el grafo que valida).
6. Al dar de baja, la lápida sustituye a la descripción: el backend escribe `prov:invalidatedAtTime` con la hora del servidor, que **no puede ser futura**, y `dct:title` con el título que tenía el recurso (no vacío).
7. Una URI o un slug dados de baja no se reutilizan (409).
8. Un catálogo con datasets no se da de baja (409).

### Borrar un catálogo que tiene datasets · Decidido (2026-11-21, decisión 49)

Se **rechaza con 409 Conflict** mientras el catálogo tenga algún `dcat:dataset`. Antes hay que mover sus datasets a otro catálogo o darlos de baja uno a uno. Solo se puede dar de baja un catálogo vacío.

Alternativas descartadas:

- **Baja en cascada** de todos sus datasets: borra ficheros de forma irreversible con una sola acción y sin ver qué datasets caen.
- **Mover sus datasets a un catálogo por defecto**: obliga a mantener un catálogo especial que no se puede borrar y deja datasets en un sitio que nadie eligió.

### Los datasets sintéticos · Decidido (2026-11-21, decisión 49)

Los tres datasets sintéticos van al catálogo `{BASE_URI}catalogo/sintetico` («Datasets sintéticos de demostración», `data/catalogos/sintetico.ttl`), separado de los reales del piloto: así se distinguen en los listados y, cuando sobren, se retiran juntos (moviendo o dando de baja sus datasets y luego el catálogo). El slug y el título no salen del prototipo y los validó el responsable; la descripción sigue siendo **[PROPUESTA]**. Cada fichero de `data/sintetico/` lleva su triple de pertenencia.

## Vocabularios y ontologías en los catálogos (decisión 50)

Decidido por el responsable (2026-11-22): cada esquema SKOS y cada ontología propia pertenece a **un solo** catálogo, como los datasets, y aparece en su ficha; CRUD completo desde la aplicación (publicar, editar metadatos y **dar de baja** con lápida y 410, igual que los datasets), con permisos de editor y admin; las versiones de ontología publicadas siguen siendo inmutables (decisión 28). Validado el mismo día, a propuesta de `semantico`: el catálogo `vocabularios-sinteticos`, el tratamiento de los corporativos como los de dominio, las externas y los auxiliares fuera de los catálogos, la aplicación como fuente de verdad del catálogo, los traslados y las bajas, y los dos 409 (baja de un recurso en uso y republicar un esquema sin conceptos que ya estaban). El responsable validó el 2026-11-25 las ocho propuestas de `semantico` (PR #45), marcadas **Validado (2026-11-25)**, y decidió además el contenido de los esquemas en `load-semantic`, los sustitutos de un concepto retirado, el rechazo de temas retirados y la no reutilización de prefijos VANN (ver «Decisiones del 2026-11-25»). El 2026-11-26 validó, a propuesta de `backend` (PR #46) y `qa` (PR #47), los códigos de error y los usos que faltaban, marcados **Validado (2026-11-26)** (ver «Decisiones del 2026-11-26»).

### Qué está en un catálogo y qué no

| Recurso | ¿En un catálogo? | Se gestiona desde la aplicación |
|---|---|---|
| Esquema SKOS de dominio `{BASE_URI}vocab/{slug}` | Sí, en exactamente uno | Sí |
| Esquema SKOS corporativo `{BASE_URI}vocab/corp/{slug}` | Sí, en exactamente uno (como los de dominio) | Sí |
| Ontología propia `{BASE_URI}onto/{slug}` (no sus versiones) | Sí, en exactamente uno | Sí |
| Ontologías externas (`ontologias/externas.ttl`, grafo `{BASE_URI}onto/externas`) | No | No |
| Esquemas auxiliares `{BASE_URI}vocab/dominio` y `{BASE_URI}vocab/tipo-dataset` | No | No |

Lo que pertenece al catálogo es la **ontología** (`{BASE_URI}onto/{slug}`), no cada versión (`owl:versionIRI`), igual que en los datasets pertenece la serie y no sus versiones. Un catálogo puede tener a la vez datasets, esquemas y ontologías; los sintéticos están separados porque así lo decidió el responsable.

### Propiedad de pertenencia: `dcat:resource` · **Validado (2026-11-25)**

```turtle
<catalogo/vocabularios-sinteticos> dcat:resource <vocab/ot> , <vocab/corp/trl> , <onto/itot> .
```

`dcat:resource` es la propiedad de DCAT 3 para «un recurso que lista el catálogo» (dominio `dcat:Catalog`, rango `dcat:Resource`); `dcat:dataset`, `dcat:service` y `dcat:catalog` son subpropiedades suyas. Motivos:

- Los esquemas (`skos:ConceptScheme`) y las ontologías (`owl:Ontology`) **no son `dcat:Dataset` en este modelo** y no tienen que serlo: `dcat:resource` no obliga a cambiarles el tipo.
- `dcat:dataset` ya significa «serie de dataset» en todo el sistema: la forma `itsh:DatasetSeries-catalog`, `validate.py`, la API, el listado de la pantalla Catálogo y F-UJI. Con otra propiedad, nada de eso cambia ni confunde un esquema con un dataset.
- Es DCAT estándar, así que un consumidor que conozca DCAT 3 sigue viendo qué lista cada catálogo.

Pendiente de confirmar contra el texto oficial de DCAT-AP 3 (decisión 22). Alternativas que se consideraron:

| Opción | A favor | En contra |
|---|---|---|
| **`dcat:resource`** (la validada) | Lo anterior | Es de DCAT 3; no tengo confirmado que DCAT-AP 3 la recoja entre las propiedades de `dcat:Catalog`, y conviene revisarlo con la decisión 22. Un consumidor que solo lea `dcat:dataset` no verá los esquemas ni las ontologías |
| `dcat:dataset` | Cualquier recolector DCAT-AP lo entiende; DCAT admite catalogar un vocabulario como dataset | Habría que tipar esquemas y ontologías como `dcat:Dataset` para que DCAT-AP los entienda, y entonces les aplican `itsh:ItotDatasetShape` y las formas de DCAT-AP (`dcat:version`, `dcat:inSeries`, `dct:accessRights`…). Además, el backend, la API, el frontend y `validate.py` tratan hoy todo `dcat:dataset` de un catálogo como una serie |
| `dct:hasPart` | Genérica y conocida | Relación parte/todo sin tipo de miembro; no es la propiedad de DCAT para lo que lista un catálogo |

### Dónde vive la pertenencia · **Validado (2026-11-25)**

- El triple `<{BASE_URI}catalogo/{slug}> dcat:resource <recurso>` se guarda **en el grafo del catálogo**, igual que `dcat:dataset` en la decisión 49.
- **No va en los ficheros de `vocabularios/` ni de `ontologias/`.** A diferencia de las series de `data/sintetico/`, que repiten su triple, esos ficheros son lo que archiva la etiqueta de Git (Release + WIDOCO, decisión 37) y las versiones de ontología son inmutables (decisión 28): si el triple estuviera en la versión, mover la ontología de catálogo cambiaría una versión publicada, y la Release diría un catálogo que la aplicación puede cambiar. La pertenencia de los sintéticos está solo en `data/catalogos/vocabularios-sinteticos.ttl`, y `validate.py` comprueba que ningún fichero de `vocabularios/` ni de `ontologias/` lleve `dcat:resource`.
- En la **ingesta** (API o `load-semantic`), el grafo que se valida es el del fichero **más** el triple de su catálogo: la API recibe el catálogo como parámetro y el backend añade el triple antes de validar, como ya puede hacer con las series. Las formas exigen exactamente uno; después el backend guarda el triple en el grafo del catálogo, no en el del esquema ni en el de la versión.

### Formas

| Regla | Forma | Fichero |
|---|---|---|
| Cada esquema de dominio o corporativo, en exactamente un catálogo, identificado por IRI; los auxiliares (`…/vocab/dominio`, `…/vocab/tipo-dataset`), en ninguno | `itsh:ConceptSchemeCatalogShape` | `shapes/ontologias-vocabularios.ttl` |
| Cada ontología propia (sujeto de `owl:versionIRI`), en exactamente un catálogo, identificado por IRI | `itsh:OwnOntology-catalog` (en `itsh:OwnOntologyShape`) | `shapes/ontologias-vocabularios.ttl` |
| Una ontología externa (sin `owl:versionIRI`), en ningún catálogo | `itsh:ExternalOntologyCatalogShape` | `shapes/ontologias-vocabularios.ttl` |
| `dcat:resource` de un catálogo es una IRI que termina en `/onto/{slug}`, `/vocab/{slug}` o `/vocab/corp/{slug}`, y no en `/vocab/corp`, `/vocab/dominio` ni `/vocab/tipo-dataset` (así no lista versiones, conceptos ni auxiliares) | `itsh:Catalog-resource` | `shapes/itot-reglas.ttl` |
| `owl:deprecated` de un concepto, si aparece, es uno y `xsd:boolean` | `itsh:Concept-deprecated` | `shapes/ontologias-vocabularios.ttl` |
| `dct:isReplacedBy` de un concepto es una IRI (cero o más) | `itsh:Concept-isReplacedBy` | `shapes/ontologias-vocabularios.ttl` |
| `dct:isReplacedBy` solo en conceptos con `owl:deprecated true`, y nunca hacia el propio concepto | `itsh:Concept-isReplacedBy-retirado` | `shapes/ontologias-vocabularios.ttl` |
| Lápida de un esquema o una ontología: URI `/vocab/{slug}`, `/vocab/corp/{slug}` u `/onto/{slug}`, no auxiliar | `itsh:BajaUriShape` (ampliada) | `shapes/itot-reglas.ttl` |

Como en la decisión 49, las formas no conocen `BASE_URI`: los esquemas auxiliares se reconocen por el final de la URI y el backend comprueba que todo empiece por `BASE_URI`.

### Bajas: la lápida y el 410

Igual que en la decisión 49: la descripción sale de los grafos publicados, queda una lápida (`rdf:type prov:Entity`, `dct:title`, `adms:status …/Withdrawn` y `prov:invalidatedAtTime`, forma cerrada `itsh:BajaShape`) en el grafo `{BASE_URI}bajas` y el slug **no se reutiliza**.

| Se da de baja | Lleva lápida | Grafos que se borran | Responden 410 por arrastre (prefijo) · **Validado (2026-11-25)** |
|---|---|---|---|
| Esquema SKOS | `{BASE_URI}vocab/{slug}` o `{BASE_URI}vocab/corp/{slug}` | El del esquema (con sus conceptos), y el triple `dcat:resource` del grafo del catálogo | Sus conceptos, `{URI del esquema}/{slug}` |
| Ontología propia | `{BASE_URI}onto/{slug}` | **Todos** los de sus versiones, `{BASE_URI}onto/{slug}/{version}`, y el triple `dcat:resource` del grafo del catálogo | Sus versiones `{BASE_URI}onto/{slug}/{version}`; sus términos `{BASE_URI}onto/{slug}#{Nombre}` ya caen en la URI de la ontología, porque el fragmento no llega al servidor |

- **Validado (2026-11-25)** Solo el esquema y la ontología tienen lápida. Los conceptos no se dan de baja uno a uno: se retiran con `owl:deprecated` (ver abajo). Las versiones de ontología tampoco: son inmutables (decisión 28), como las de los datasets.
- La lápida pierde `skos:ConceptScheme` u `owl:Ontology` (ejemplo inválido `examples/invalid/bajas/baja-conserva-tipo-skos.ttl`); qué era se deduce de su URI. Su `dct:title` es el título que tenía (en una ontología, el de su última versión).
- Las ontologías y los esquemas vivos siguen limitados a `Completed` y `UnderDevelopment`; `Withdrawn` solo en lápidas (ver «Estado»).
- Los esquemas auxiliares, el segmento reservado `vocab/corp` y las ontologías externas no se dan de baja (`itsh:BajaUriShape` rechaza las lápidas con URI de auxiliar).

### Reglas que comprueba el backend (dependen de este contrato)

SHACL solo ve el grafo que valida. Estas reglas son del backend, en la ingesta y en el CRUD; las marcadas **Decidido (2026-11-22, decisión 50)** salen literalmente de la decisión, las marcadas **Validado (2026-11-25)** eran propuestas de `semantico` y las marcadas **Decidido (2026-11-25)** son las respuestas del responsable a las preguntas de la PR #45 y las marcadas **Validado (2026-11-26)** eran propuestas de `backend` (PR #46) y `qa` (PR #47); las que no llevan marca se deducen de las anteriores:

1. Las URIs de esquemas, ontologías y sus lápidas **empiezan por `BASE_URI`** (`{BASE_URI}vocab/{slug}`, `{BASE_URI}vocab/corp/{slug}`, `{BASE_URI}onto/{slug}`) con `{slug}` válido y no reservado (`corp`, `dominio`, `tipo-dataset` en `vocab/`).
2. `dcat:resource` sale **solo de un catálogo `catalogo/{slug}` existente** (nunca del raíz) y apunta a un esquema o una ontología propia existentes.
3. El recurso no está ya en **otro** catálogo del triplestore. **Validado (2026-11-25)** Publicar un esquema o una versión de ontología que ya está en otro catálogo da **409**, como con los datasets (la regla de `backend` validada en la decisión 49): mover es explícito.
4. **Mover** un esquema o una ontología de catálogo es editar sus metadatos: se quita el triple del catálogo de origen y se añade al de destino. No cambia ninguna URI ni ninguna versión publicada. **Validado (2026-11-26):** **editar un esquema** cambia solo los literales en español (`@es`) de los campos que se editan; los de otros idiomas (`@ca`, `@en`) no se tocan. Sus conceptos no cambian al editar: se cambian republicando (regla 9).
5. **Decidido (2026-11-22, decisión 50):** las ontologías externas y los esquemas auxiliares **no se gestionan desde la aplicación**: la API no los crea, ni los edita, ni los da de baja, ni los mete en un catálogo. Solo cambian con sus ficheros y `load-semantic`. El código de error es el de la regla 12.
6. Al dar de baja, la lápida sustituye a la descripción (fecha del servidor, no futura; título no vacío) y se borran los grafos de la tabla anterior.
7. **Decidido (2026-11-22, decisión 50):** un slug dado de baja **no se reutiliza**: publicar un esquema o una ontología con esa URI da **409**. `vocab/{slug}`, `vocab/corp/{slug}` y `onto/{slug}` son URIs distintas: la baja de `vocab/ot` no bloquea `vocab/corp/ot`. **Decidido (2026-11-25):** tampoco se reutiliza el **prefijo VANN** (`vann:preferredNamespacePrefix`) de un esquema o una ontología dados de baja: publicar otro recurso con ese prefijo da **409**. Como la lápida es cerrada y no guarda el prefijo, el backend tiene que conservarlo aparte (por ejemplo, en la auditoría de PostgreSQL) para poder comprobarlo.
8. **Decidido (2026-11-22, decisión 50):** dar de baja un esquema o una ontología que **usan recursos vivos** da **409** (**Validado (2026-11-26):** `in_use`). Qué cuenta como «uso» está **Validado (2026-11-25)**, con lo que añade **Validado (2026-11-26)** (lo vivo es lo que está en los grafos publicados, no en `{BASE_URI}bajas`):
   - **Esquema:** algún concepto suyo (`skos:inScheme`) es `dcat:theme` de una versión de un dataset vivo, `dct:subject` de una versión de una ontología propia viva, o destino de `skos:related`, `skos:exactMatch`, `skos:closeMatch`, `skos:broadMatch`, `skos:narrowMatch` o `skos:relatedMatch` desde un concepto de otro esquema vivo.
   - **Esquema, Validado (2026-11-26):** además, el **esquema mismo** (su URI, no un concepto) es `dct:subject` de una versión de una ontología propia viva, o algún concepto suyo es destino de `dct:isReplacedBy` desde un concepto de **otro** esquema vivo (QA-50-02: si no, el otro esquema se quedaría con un sustituto que ya no existe y no se podría republicar, porque la regla 9 exige sustitutos vivos). Se deduce que el `dct:isReplacedBy` entre conceptos del mismo esquema no cuenta: se van con él.
   - **Ontología:** su URI o una de sus versiones es `owl:imports` de una versión de otra ontología propia viva, o algún término suyo (`{BASE_URI}onto/{slug}#…`) aparece en una versión de otra ontología propia viva.
   - **Ontología, Validado (2026-11-26):** además, su URI o una de sus versiones es `dct:conformsTo` de una versión de un dataset vivo (los datos sintéticos apuntan a la versión: `dataset/modbus-tcp-testbed/2.1.0` → `onto/itot/1.2.0`).
   - Como las versiones de dataset y de ontología son inmutables, un esquema usado por una versión publicada solo se puede dar de baja después de dar de baja el dataset o la ontología que lo usa. La respuesta 409 debería decir qué recursos lo usan.
9. **Decidido (2026-11-22, decisión 50):** **republicar un esquema** sin algún concepto que ya estaba publicado da **409**: el conjunto de conceptos (`skos:inScheme`) de la nueva versión tiene que contener todos los publicados. Un concepto se retira marcándolo `owl:deprecated "true"^^xsd:boolean` (forma `itsh:Concept-deprecated`), sin perder su URI, su esquema ni su lugar en el árbol (sigue necesitando `skos:topConceptOf` o `skos:broader`). **Decidido (2026-11-25):** el concepto retirado indica los que lo sustituyen con `dct:isReplacedBy` (cero o más, IRIs; formas `itsh:Concept-isReplacedBy` e `itsh:Concept-isReplacedBy-retirado`, que solo lo admiten en conceptos con `owl:deprecated true` y nunca hacia sí mismo). Que cada sustituto sea un `skos:Concept` vivo (de este u otro esquema) lo comprueba el backend, porque puede estar en otro grafo. **Reactivar** un concepto retirado (volver de `true` a `false` o quitar `owl:deprecated`) queda **fuera del piloto**: no se contempla. **Validado (2026-11-26):** republicar un esquema que reactiva un concepto retirado da **409 `concept_reactivated`**. Ejemplo válido: `examples/valid/esquema-en-catalogo.ttl`.
10. **Validado (2026-11-25)** Un catálogo con algún dataset, esquema u ontología (`dcat:dataset` o `dcat:resource`) no se da de baja (**409**), extendiendo la regla de la decisión 49.
11. **Decidido (2026-11-25):** una versión de dataset nueva cuyo `dcat:theme` apunta a un concepto **retirado** (`owl:deprecated true`) **se rechaza, avisando al editor** de qué temas están retirados y, si los hay, de sus sustitutos (`dct:isReplacedBy`). Las versiones ya publicadas no cambian (decisión 28). **Validado (2026-11-26):** la respuesta es **422 `deprecated_theme`**, con los temas retirados y sus sustitutos.
12. **Decidido (2026-11-25):** el código de error al intentar crear, editar, dar de baja o catalogar una ontología externa o un esquema auxiliar (regla 5) lo propone `backend` en el OpenAPI. **Validado (2026-11-26):** es **403 `not_managed`**, con cualquier rol. Las ontologías externas solo se pueden sustituir (con su fichero y `load-semantic`, regla 5).
13. **Validado (2026-11-26, QA-50-03):** una versión de dataset nueva cuyo `dcat:theme` apunta a un concepto de un **esquema dado de baja** o a un **concepto que no existe** en los grafos publicados da **422**. SHACL no lo ve: solo comprueba que el tema sea una IRI, porque el concepto está en otro grafo (ver «Supuestos de validación» del README). En los datos del repositorio lo comprueba `validate.py` (cada tema es un concepto de un esquema de `vocabularios/`). El `kind` de la respuesta lo fija `backend` en el OpenAPI.
14. **Validado (2026-11-26, QA-50-01):** publicar un esquema o una ontología con un **prefijo VANN** (`vann:preferredNamespacePrefix`) que ya usa **otro recurso vivo** da **409**. Completa la regla 7 (prefijos de recursos dados de baja): un prefijo identifica a un solo recurso, vivo o dado de baja. Se deduce que una versión nueva de la misma ontología o la republicación del mismo esquema conservan su prefijo y no chocan consigo mismas. SHACL no lo ve, porque el otro recurso está en otro grafo; en el repositorio lo comprueba `validate.py` (prefijos únicos entre todos los esquemas y ontologías). El `kind` de la respuesta lo fija `backend` en el OpenAPI.

### La aplicación manda; Git solo versiona y archiva · Decidido (2026-11-22, decisión 50)

- La **aplicación** es la fuente de verdad del catálogo de cada esquema y ontología, de los traslados y de las bajas.
- La **etiqueta de Git** (`onto/{slug}/v{version}`, `vocab/[corp/]{slug}/v{version}`, decisión 37) solo valida, versiona y archiva: crea la Release con el RDF y la documentación WIDOCO, **sin cargar nada** en ningún entorno. Como la pertenencia no está en los ficheros (ver arriba), la Release no lleva el catálogo.
- En `load-semantic` (**Validado (2026-11-25)**), siguiendo lo validado para los datasets en la decisión 49: un esquema u ontología con lápida se omite; uno que ya está en un catálogo del triplestore se queda en él (un traslado hecho en la aplicación no se deshace), y uno nuevo va al catálogo que le da `data/catalogos/`, que tiene que cargarse en la misma ejecución o estar ya publicado. Para validar cada fichero, `load-semantic` le añade el triple de su catálogo.
- **Decidido (2026-11-25): manda la aplicación también en el contenido de los esquemas.** Si la aplicación ha añadido conceptos a un esquema publicado, `load-semantic` **no los quita** y no da 409 por eso (la regla 9 es de la API): el esquema que queda tiene los conceptos del fichero más los añadidos desde la aplicación.

### Decisiones del 2026-11-25

Respuestas del responsable a las preguntas de la PR #45, recogidas arriba: el contenido de los esquemas en `load-semantic` (manda la aplicación), los sustitutos de un concepto retirado (`dct:isReplacedBy`, regla 9), la reactivación fuera del piloto (regla 9), el rechazo de temas retirados (regla 11), los prefijos VANN no reutilizables (regla 7) y el código de error de los recursos no gestionables (regla 12).

### Decisiones del 2026-11-26

Validado por el responsable, a propuesta de `backend` (PR #46) y `qa` (PR #47), y recogido arriba: 403 `not_managed` para las ontologías externas y los esquemas auxiliares (regla 12); 422 `deprecated_theme` con los sustitutos (regla 11); 409 `concept_reactivated` al reactivar un concepto retirado (regla 9); editar un esquema cambia solo los literales en español (regla 4); 409 `in_use` y los usos nuevos que bloquean la baja: `dct:subject` hacia el esquema mismo, `dct:isReplacedBy` desde otro esquema vivo (QA-50-02) y `dct:conformsTo` de una versión de dataset viva hacia una ontología (regla 8); 422 por un tema de un esquema dado de baja o inexistente (QA-50-03, regla 13), y 409 por un prefijo VANN que ya usa otro recurso vivo (QA-50-01, regla 14). Ninguna necesita formas SHACL nuevas: todas cruzan grafos (el publicado, las bajas o la auditoría) y las comprueba el backend.

### Los esquemas y ontologías sintéticos · Decidido (2026-11-22, decisión 50)

`{BASE_URI}catalogo/vocabularios-sinteticos`, título «Vocabularios y ontologías sintéticos de demostración», en `data/catalogos/vocabularios-sinteticos.ttl` y agrupado por el raíz con `dcat:catalog`. Lista con `dcat:resource` los nueve esquemas (`it`, `ot`, `pqc`, `did`, `ia` y los corporativos `organizacion`, `financiacion`, `trl` y `sectores`) y las tres ontologías propias (`itot`, `pqcm` y `didx`). La descripción está **Validado (2026-11-25)**. Fuera de él: `ontologias/externas.ttl` y `data/vocab-minimo.ttl`.

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

Un fichero describe un solo esquema (con todos sus conceptos) o una sola versión de ontología. En la etiqueta Git, `{version}` es el `owl:versionInfo` del fichero (`onto/itot/v1.2.0`, `vocab/ot/v1.0`, `vocab/corp/financiacion/v2026.1`). Cada esquema tiene un fichero, el de su última versión, y las anteriores quedan en el historial de Git. Las ontologías tienen un fichero por versión porque la ficha muestra el historial con `owl:priorVersion`. Ningún fichero lleva el catálogo al que pertenece su esquema u ontología: esa pertenencia está en `data/catalogos/` (decisión 50, ver «Vocabularios y ontologías en los catálogos»).

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

Lo llevan las ontologías propias (cada versión) y todos los esquemas. Las formas SHACL no admiten otros valores (`Deprecated`, `Withdrawn`) hasta que la interfaz los contemple. `Withdrawn` se usa solo en las lápidas de los recursos dados de baja (decisiones 49 y 50, ver «Catálogos y borrado lógico» y «Vocabularios y ontologías en los catálogos»): la lápida de un esquema o de una ontología ya no es un `skos:ConceptScheme` ni una `owl:Ontology`. Un **concepto** retirado no cambia de estado: lleva `owl:deprecated "true"^^xsd:boolean` y, si los tiene, sus sustitutos en `dct:isReplacedBy` (decisión 50). En la ficha de ontología, «Actual» o «Sustituida» no es un estado: una versión está sustituida si otra la cita como `owl:priorVersion`.

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

En `semantic/data/sintetico/`, un fichero por dataset con la serie, todas sus versiones, sus distribuciones y su pertenencia al catálogo `{BASE_URI}catalogo/sintetico`: Decidido (2026-11-21, decisión 49). Los slugs de las series 2 y 3 son **[PROPUESTA]** de `semantico`.

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
- Decisión 49: lo que sigue marcado **[PROPUESTA]** en «Catálogos y borrado lógico» (pertenencia en el grafo de ingesta, un solo nivel de catálogos, fichero por catálogo y descripción del catálogo «sintetico»).
- Decisión 50: confirmar `dcat:resource` contra el texto oficial de DCAT-AP 3 (decisión 22). Los códigos de las reglas 11 y 12 ya están validados (2026-11-26); el `kind` de los errores de las reglas 13 y 14 lo fija `backend` en el OpenAPI.
- Qué devuelve cada URI al resolverla (negociación de contenido HTML / Turtle / JSON-LD) y cómo se sirve la descarga de una distribución restringida: lo implementa `backend` según el contrato de la fase 4 (decisiones 31 y 40).
