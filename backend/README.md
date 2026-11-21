# Backend · API FastAPI

API del repositorio semántico IT&OT. Es el único componente que escribe en el triplestore y en el almacenamiento de distribuciones (ver `Plan.md`, sección 3.2).

**Estado (fase 4):** health checks, autenticación JWT, cuentas de usuario y auditoría en PostgreSQL (fase 1); cliente de Fuseki, ingesta DCAT-AP validada con SHACL, comando de carga de los datos sintéticos, lectura pública del catálogo y negociación de contenido en las URIs persistentes (fase 2); ingesta y lectura de ontologías (con métricas OWL de owlready2 y consistencia con Pellet) y de esquemas SKOS, y negociación en `/onto/…` y `/vocab/…` (fase 3); versiones inmutables, ficheros de distribución con acceso por rol (interfaz de almacenamiento), evaluación FAIR con F-UJI, SPARQL público con límites, consultas guardadas, bloqueo de login y revocación de tokens (fase 4, ver «Fase 4» más abajo); varios catálogos, CRUD de catálogos y datasets y borrado lógico con 410 (decisión 49, ver «Catálogos y bajas»).

## Requisitos

- [uv](https://docs.astral.sh/uv/). La versión de Python está fijada en `.python-version` (3.15) y uv la usa automáticamente.
- PostgreSQL y Fuseki para ejecutar la API completa. Las pruebas no necesitan ninguno de los dos.
- **Java 25 o superior** en el `PATH` para la consistencia OWL (Pellet). El Jena que owlready2 0.51 incluye para Pellet está compilado para Java 25: con una versión anterior Pellet no arranca. Sin Java (o con uno antiguo) la ingesta de ontologías funciona igual, pero guarda la consistencia como «no ejecutada» (`consistent: null` con el motivo en `detail`), y las pruebas que necesitan Pellet se saltan con ese motivo.

## Arranque en local

```sh
cd backend
uv sync
cp ../.env.example .env            # cuando exista (lo gestiona infra); o exporta las variables
uv run alembic upgrade head        # crea o actualiza las tablas
uv run python -m app.cli create-admin --username <nombre>   # primer admin
uv run uvicorn app.main:app --reload --port 8000
```

La documentación interactiva queda en `http://localhost:8000/docs`.

Con Docker Compose (lo gestiona `infra`), la imagen aplica las migraciones al arrancar. El primer admin se crea así:

```sh
docker compose exec -it backend python -m app.cli create-admin --username <nombre>
```

## Variables de entorno

Se leen del entorno o de un fichero `backend/.env` (que no se versiona). Los valores de ejemplo son ficticios.

| Variable | Obligatoria | Por defecto | Uso |
|---|---|---|---|
| `BASE_URI` | no | `https://semantic.example.org/itot/` | Base de todas las URIs persistentes. Si no termina en `/` o `#`, se le añade `/` |
| `DATABASE_URL` | **sí** | — | PostgreSQL de usuarios y auditoría, p. ej. `postgresql+psycopg://itot:changeme@postgres:5432/itot` |
| `FUSEKI_URL` | no | `http://fuseki:3030` | Fuseki |
| `FUSEKI_DATASET` | no | `itot` | Dataset de Fuseki. Consultas en `/{dataset}/query` (sin credenciales); escrituras en `/{dataset}/data` (Graph Store Protocol) |
| `FUSEKI_USER` | no al arrancar | — | Usuario de escritura en Fuseki (autenticación Basic). En Compose, `backend` (decisión 32; su contraseña llega como `FUSEKI_PASSWORD` desde `FUSEKI_BACKEND_PASSWORD`). El backend no usa los endpoints de administración `/$/…`. Sin él, la lectura funciona y la ingesta responde 503 con un mensaje que nombra la variable |
| `FUSEKI_PASSWORD` | no al arrancar | — | Contraseña de escritura en Fuseki. Nunca aparece en logs ni en errores |
| `FUSEKI_TIMEOUT_SECONDS` | no | `10` | Timeout de lectura de cada petición a Fuseki (la conexión tiene 3 s) |
| `SEMANTIC_DIR` | no | `../semantic` relativo a `backend/` | Carpeta `semantic/` (formas SHACL y datos). En el contenedor, `/semantic` (montada por infra, solo lectura). Una ruta relativa se resuelve contra `backend/` |
| `INGEST_MAX_BYTES` | no | `10485760` (10 MiB) | Tamaño máximo del RDF de `POST /datasets`, `POST /ontologies` y `POST /schemes` (413 si se supera) |
| `INGEST_MAX_TRIPLES` | no | `100000` | Tripletas máximas por ingesta (API y `load-semantic`). Se comprueba mientras se analiza: al superarlo, 422 `limit` |
| `SHACL_TIMEOUT_SECONDS` | no | `60` | Tiempo máximo de la validación SHACL de una ingesta (hasta 3600). Al superarlo se mata el proceso de validación y la ingesta responde 422 `limit` |
| `SHACL_MEMORY_MB` | no | `2048` | Memoria máxima (`RLIMIT_AS`) del proceso de validación SHACL (de 256 a 65536; solo en Linux). Al superarla, 422 `limit` |
| `REASONER_TIMEOUT_SECONDS` | no | `120` | Tiempo máximo de Pellet por versión de ontología (hasta 3600). Si se supera, se mata el proceso Java y la consistencia queda `null` con el motivo |
| `REASONER_JAVA_MEMORY_MB` | no | `1024` | Memoria máxima de la JVM de Pellet (`-Xmx`, de 256 a 65536) |
| `FRONTEND_BASE_URL` | no | `http://localhost:5173` | Frontend al que redirigen (303) las URIs persistentes cuando se pide HTML (fichas de dataset, ontología y vocabulario) |
| `JWT_SECRET` | **sí** | — | Secreto HMAC para firmar los JWT. Longitud mínima según el algoritmo: 32 bytes con HS256, 48 con HS384 y 64 con HS512. Sin él la API no arranca. Genera uno con `python -c "import secrets; print(secrets.token_urlsafe(64))"` (vale para los tres) |
| `JWT_ALGORITHM` | no | `HS256` | `HS256`, `HS384` o `HS512` |
| `JWT_EXPIRE_MINUTES` | no | `60` | Validez del token |
| `CORS_ORIGINS` | no | vacío (sin CORS) | Orígenes permitidos separados por comas; en local, `http://localhost:5173` |
| `STORAGE_BACKEND` | no | `disk` | `disk` o `r2`. **`r2` aún no está implementado**: cada operación con ficheros responde 503 con un mensaje claro (ver «Almacenamiento») |
| `STORAGE_DISK_PATH` | no | `/data/distributions` | Carpeta de las distribuciones en disco |
| `MAX_UPLOAD_MB` | no | `512` | Tamaño máximo de un fichero de distribución (413 si se supera) |
| `DOWNLOAD_LINK_TTL_SECONDS` | no | `60` | Validez de un enlace de descarga firmado (de 1 a 3600) |
| `FUJI_URL` | no | `http://fuji:1071/fuji/api/v1` | API de F-UJI (se llama a `{FUJI_URL}/evaluate`) |
| `FUJI_USERNAME`, `FUJI_PASSWORD` | no al arrancar | — | Autenticación Basic de F-UJI. Sin ellas las evaluaciones quedan `failed` con un motivo que nombra las variables; la API funciona igual |
| `FUJI_TIMEOUT_SECONDS` | no | `300` | Tiempo máximo de una evaluación |
| `FAIR_TARGET_BASE_URL` | no | vacío (= `BASE_URI`) | URL base con la que F-UJI alcanza el backend: se le pasa `{FAIR_TARGET_BASE_URL}datasets/{slug}/rdf?…` y `{FAIR_TARGET_BASE_URL}sparql`. En local, `http://backend:8000/` |
| `FAIR_WORKER_POLL_SECONDS` | no | `10` | Cada cuánto mira el trabajador FAIR si hay evaluaciones pendientes (además de despertarse al publicar). `0` lo desactiva (pruebas) |
| `SPARQL_TIMEOUT_SECONDS` | no | `10` | Tiempo máximo de una consulta del SPARQL público (504 al superarlo) |
| `SPARQL_MAX_ROWS` | no | `10000` | Filas (SELECT) o triples (CONSTRUCT/DESCRIBE) máximos; si se recorta, `X-Result-Truncated: true` |
| `SPARQL_RATE_ANON_PER_MIN` | no | `30` | Consultas por minuto y por IP (anónimos) |
| `SPARQL_RATE_AUTH_PER_MIN` | no | `60` | Consultas por minuto y por usuario (con JWT) |
| `SAVED_QUERIES_MAX_PER_USER` | no | `50` | Consultas personales por usuario (409 al superarlo) |
| `LOGIN_MAX_FAILURES` | no | `5` | Fallos de login por (usuario, IP) que bloquean ese par |
| `LOGIN_WINDOW_MINUTES` | no | `15` | Ventana en la que se cuentan los fallos |
| `LOGIN_LOCKOUT_MINUTES` | no | `15` | Duración del bloqueo (429 con `Retry-After`) |

Si falta una variable obligatoria o tiene un valor no válido, el arranque falla con un mensaje que nombra la variable, sin mostrar su valor.

## Endpoints (fase 1)

| Método y ruta | Acceso | Qué hace |
|---|---|---|
| `GET /health` | público | El proceso está vivo |
| `GET /health/ready` | público | Comprueba la base de datos (`SELECT 1`) y Fuseki (`ASK {}` sobre `FUSEKI_URL/FUSEKI_DATASET/query`). 200 si todo responde, 503 si no |
| `POST /auth/token` | público | Login OAuth2 *password* (formulario `username`, `password`). Devuelve `access_token`, `token_type`, `expires_in` y `role` |
| `GET /auth/me` | con cuenta | Datos de la cuenta autenticada |
| `GET /users` | admin | Lista las cuentas |
| `POST /users` | admin | Da de alta una cuenta (`username`, `password`, `role`) |
| `PATCH /users/{id}` | admin | Cambia `role` y/o `is_active` (baja y reactivación) |

## Endpoints (fase 2): catálogo

| Método y ruta | Acceso | Qué hace |
|---|---|---|
| `POST /datasets` | editor (y admin, que hereda) | Ingesta de una serie con sus versiones en Turtle (`text/turtle`) o JSON-LD (`application/ld+json`), con su triple de pertenencia a un catálogo o `?catalog={slug}` (decisión 49). 201 si la serie es nueva, 200 si se sustituye (`changed=false` si era idéntica), 422 con el informe si no es válida |
| `GET /datasets` | público | Tarjetas del catálogo. Filtros `q`, `domain` (`it`, `ot`, `pqc`, `ia`), `catalog` (slug del catálogo), `page` y `page_size` (máx. 100) |
| `GET /datasets/{slug}` | público | Ficha: serie, versión actual (o `?version=MAYOR.MENOR.PARCHE`), historial, distribuciones, cadena PROV y metadatos DCAT-AP |
| `GET /datasets/{slug}/rdf` | público | RDF de la versión (actual o `?version=`) en Turtle o JSON-LD, según `?format=turtle\|jsonld` o la cabecera `Accept` |
| `GET /dataset/{slug}` | público | URI persistente de la serie: Turtle, JSON-LD o RDF/XML según `Accept`; sin `Accept`, con `*/*` o con `text/html` (fase 4), 303 a `{FRONTEND_BASE_URL}/datasets/{slug}` |
| `GET /dataset/{slug}/{version}` | público | URI persistente de la versión: igual, con 303 a `{FRONTEND_BASE_URL}/datasets/{slug}?version={version}` |

Desde la fase 4, el 303 y el RDF de `/dataset/…` (serie, versión y distribución) llevan **signposting** (cabecera `Link`, RFC 8288): `rel="cite-as"` hacia la URI persistente y `rel="describedby"` hacia ella misma con cada `type` RDF (`text/turtle`, `application/ld+json`, `application/rdf+xml`).

El contrato completo está en [`openapi.json`](openapi.json). Los campos siguen la convención del resto de la API (`snake_case`: `version_notes`, `previous_version`, `in_series`…).

### Lectura

- **Campos sin valor en el RDF** se devuelven como `null` o lista vacía. Licencia, contacto, fechas (`issued`, `modified`) y proyecto (`is_referenced_by`) son placeholders del prototipo que aún no están en los datos: el frontend muestra el placeholder. La puntuación FAIR (fase 4) sale solo de F-UJI.
- **Versión actual:** `dcat:last` de la serie; si falta, la versión de mayor número.
- **Dominio (fase 3):** el `dct:subject` del esquema (`skos:inScheme`) de los temas de la versión actual, un concepto `{BASE_URI}vocab/dominio/{it|ot|pqc|ia}`. `uri` es ese concepto y `label`, su `skos:prefLabel` (del grafo `{BASE_URI}vocab/dominio`). «PQC e identidad» tiene dos esquemas (`pqc` y `did`) con el mismo dominio. Respaldos: si el esquema no declara `dct:subject` y es `{BASE_URI}vocab/{it|ot|pqc|ia}`, ese slug con la etiqueta del esquema; si el vocabulario no está cargado, el patrón de la URI del concepto (`{BASE_URI}vocab/{esquema}/{slug}`), con la etiqueta a `null`. `domain` es el primero de `domains`. La ficha de una versión antigua muestra el dominio de la serie.
- **Sintético:** `synthetic` es `true` si la serie (o la versión) tiene `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>`.
- **Acceso:** `access_rights` lleva la IRI de `dct:accessRights` y `code`, la entrada de la tabla europea (`PUBLIC`, `RESTRICTED`, `NON_PUBLIC`…). El texto visible lo decide el frontend.
- **Formatos:** el tipo de medio IANA (`text/csv`) de cada distribución de la versión actual o, si no tiene `dcat:mediaType`, su `dct:title` (caso de NPZ).
- **Historial:** de la versión más reciente a la más antigua. Incluye las versiones solo referenciadas por `dcat:previousVersion` (`described=false`), con el número sacado de la URI.
- **Procedencia:** cadena lineal desde el origen hasta la actividad que generó la versión (`prov:wasGeneratedBy` → `prov:used` → `prov:wasGeneratedBy`…), sin la versión misma. Los nodos en blanco tienen `uri=null`. Si una actividad usa varias entidades, se sigue la primera en orden de IRI.
- **Publisher:** se toma del grafo de cada serie (nodo en blanco con `foaf:name`); los agentes no se deduplican por nombre.
- **Búsqueda `q`:** en título y descripción (de la serie y de la versión actual) en `skos:prefLabel`/`skos:altLabel` de los temas y, desde la fase 4, en la URI de la serie sin `BASE_URI` (`dataset/{slug}`), sin distinguir mayúsculas ni acentos. **No llega a SPARQL**: se filtra en Python.
- **RDF de una versión:** sus triples y los de lo que cuelga de ella en el grafo de la serie (distribuciones, actividades, nodos en blanco y agentes), sin la serie ni las demás versiones. La URI de la serie devuelve el grafo completo de la serie.

### Ingesta (`POST /datasets` y `load-semantic`)

0. **Autenticación primero:** el token y el rol (editor o admin) se comprueban antes de mirar el `Content-Type` o leer el cuerpo. Un anónimo recibe 401 y un miembro 403, nunca 413 ni 415.
1. **Análisis**, con las IRIs relativas resueltas contra `BASE_URI`. En JSON-LD se rechazan los contextos remotos (`@context` con URL o `@import`) para que el servidor no descargue documentos externos.
   - **Anidamiento máximo: 64 niveles**, tanto de JSON en JSON-LD como de cadenas de nodos en blanco anidados (`[ p [ p … ] ]`) en cualquier formato; las listas RDF (`rdf:rest`) no cuentan. Un DCAT-AP real usa unos pocos niveles, y el límite queda lejos de la recursión de Python (1000) que usan analizadores y serializadores. Si se supera, 422 `syntax` (también si el analizador agota la recursión).
   - **IRIs válidas:** toda IRI del grafo (sujeto, predicado, objeto o tipo de dato de un literal) es absoluta y no contiene los caracteres que excluye la producción `IRIREF` de Turtle/N-Triples/SPARQL (espacio, controles, `<>"{}|^`` ` ``\`). Si no, 422 `uri` con la IRI en el `issue`, antes de SHACL y de escribir nada.
2. **Estructura y URIs** (`semantic/uris.md`): exactamente una `dcat:DatasetSeries` con URI `{BASE_URI}dataset/{slug}`; cada `dcat:Dataset` es `{serie}/{version}`, con `dcat:inSeries` hacia la serie y `dcat:version` igual al último segmento; cada distribución cuelga de su versión. Todo sujeto con IRI cuelga de `BASE_URI` y, en concreto, de la serie o de `{BASE_URI}actividad/`: una ingesta no puede reescribir otra serie, el vocabulario ni el catálogo. La única excepción es el triple de pertenencia `<{BASE_URI}catalogo/{slug}> dcat:dataset <serie>` (decisión 49): ningún otro triple con un catálogo como sujeto, y nunca con el raíz `{BASE_URI}catalogo`.
3. **SHACL** con pyshacl, en un proceso aparte con tiempo y memoria limitados (ver «Límites de la ingesta»): todas las formas de `SEMANTIC_DIR/shapes/*.ttl` y, como grafo de soporte, `SEMANTIC_DIR/data/vocab-minimo.ttl`. Sin inferencia y sin la ontología DCAT.
4. **Catálogo** (decisión 49, lo que SHACL no ve): el catálogo existe y no está dado de baja (si no, 422 `catalog`), la serie no está en **otro** catálogo (409 `catalog_conflict`; se mueve con `PATCH /datasets/{slug}`) y su slug no es de un dataset dado de baja (409 `withdrawn`).
5. **Guardado** en el grafo con nombre `{BASE_URI}dataset/{slug}`, **sin** el triple de pertenencia, que va al grafo del catálogo.

Si falla un paso, la respuesta es 422 con `kind` (`syntax`, `structure`, `uri`, `shacl`, `limit` o `catalog`), `detail`, `issues` (nodo, propiedad, valor, severidad, forma y mensaje) y, para SHACL, `report` con el informe de pyshacl en texto. No se escribe nada.

**Estrategia de sustitución:** cada ingesta sustituye **por completo** el grafo con nombre de la serie (`PUT` del Graph Store Protocol, atómico en Fuseki). Por eso se envía siempre la serie entera con todas sus versiones. Desde la fase 4 las versiones publicadas son **inmutables** (decisión 28): si falta una, 409 `version_removed`; si cambia, 409 `version_immutable` (ver «Fase 4»). Si el contenido es isomorfo al guardado, no se reescribe (`changed=false`). Las credenciales de escritura se exigen siempre, también cuando no hay cambios.

**Auditoría:** cada ingesta registra `dataset_published` con quién (`actor_*`, o `cli` desde el comando) y `details` con `series`, `slug`, `graph`, `versions`, `triples`, `created`, `changed` y `via` (`api` o `cli`). Se escribe primero en Fuseki y después se confirma la auditoría, para no registrar publicaciones que no han ocurrido.

### Grafos con nombre

| Grafo | Contenido |
|---|---|
| `{BASE_URI}dataset/{slug}` | Una serie con sus versiones, distribuciones y procedencia |
| `{BASE_URI}vocab/{slug}` y `{BASE_URI}vocab/corp/{slug}` | Un esquema SKOS con sus conceptos (`vocabularios/*.ttl`, `vocabularios/corp/*.ttl`). Los auxiliares `vocab/dominio` y `vocab/tipo-dataset` salen de `data/vocab-minimo.ttl`, repartido en un grafo por esquema |
| `{BASE_URI}onto/{slug}/{version}` | Una versión de ontología (su `owl:versionIRI`) |
| `{BASE_URI}onto/externas` | Las ontologías externas, solo por referencia (`ontologias/externas.ttl`) |
| `{BASE_URI}catalogo` | Catálogo raíz, `data/catalogo.ttl`: agrupa los catálogos con `dcat:catalog` y no lista series (decisión 49) |
| `{BASE_URI}catalogo/{slug}` | Un catálogo (`data/catalogos/{slug}.ttl` o creado por la API) con un `dcat:dataset` por serie |
| `{BASE_URI}bajas` | Lápidas de los catálogos y series dados de baja. **No se publica**: ni en SPARQL ni en los listados |

El grafo `{BASE_URI}vocab/` de la fase 2 ya no se escribe ni se lee. Si quedó en el Fuseki de una instalación anterior, no molesta (la lectura lo ignora) y se puede borrar a mano.

La lectura solo consulta grafos publicados a propósito, nombrados en cada patrón `GRAPH`, así que no depende de `tdb2:unionDefaultGraph`:

- **Series:** el grafo de una serie es su propia URI (`GRAPH ?s { ?s a dcat:DatasetSeries }`, bajo `{BASE_URI}dataset/`). Una serie guardada en cualquier otro grafo (otro nombre o el grafo de otra serie) no aparece ni en el listado ni en la ficha.
- **Vocabulario (fase 3):** las etiquetas de un concepto solo se leen del grafo de su esquema: un grafo bajo `{BASE_URI}vocab/` (filtro parametrizado `$vocab_ns`, literal escapado) cuyo nombre es el `skos:inScheme` del concepto y en cuyo espacio de nombres (`{esquema}/`) está la URI del concepto. La etiqueta del dominio sale solo del grafo `{BASE_URI}vocab/dominio` (`$dominio`). Un tema que apunte a un recurso descrito en otro grafo no expone sus etiquetas: aparece con `label` y `scheme` a `null`.
- **Ontologías y esquemas:** cada versión de ontología solo se lee de su grafo (`GRAPH ?g { ?o a owl:Ontology ; owl:versionIRI ?g }`, bajo `{BASE_URI}onto/` y con `?g` = `{?o}/…`), las externas solo de `{BASE_URI}onto/externas` y cada esquema solo del grafo de su URI.

### SPARQL seguro

El protocolo SPARQL no tiene parámetros enlazados. `app/sparql.py` serializa los valores como términos escapados (`iri()` valida la IRI y rechaza los caracteres que `IRIREF` no admite; `literal()` escapa comillas, barras y controles, y rechaza `\u`/`\U`), y `render()` solo acepta esos términos: pasarle un `str` es un error. Además, slugs y versiones se validan con su patrón antes de llegar a ninguna consulta (422 si no cumplen), y el texto libre `q` no llega a SPARQL.

### Comando de carga

```sh
uv run python -m app.cli load-semantic
docker compose exec backend python -m app.cli load-semantic
```

Carga desde `SEMANTIC_DIR`:

- `data/vocab-minimo.ttl` (obligatorio): esquemas auxiliares `vocab/dominio` y `vocab/tipo-dataset`, cada uno en el grafo de su URI.
- `vocabularios/*.ttl` y `vocabularios/corp/*.ttl`: un esquema por fichero. El nombre del fichero es el slug del esquema (`vocabularios/corp/trl.ttl` ↔ `{BASE_URI}vocab/corp/trl`).
- `ontologias/{slug}/{version}.ttl`: todas las versiones de cada ontología. La ruta tiene que coincidir con el `owl:versionIRI`.
- `ontologias/externas.ttl`: las externas, solo por referencia (ningún sujeto bajo `BASE_URI`).
- `data/catalogo.ttl` (obligatorio, catálogo raíz), `data/catalogos/{slug}.ttl` (un catálogo por fichero, decisión 49) y `data/sintetico/*.ttl` (al menos uno).

Con lo hecho desde la aplicación (decisión 49), `load-semantic` **conserva el estado del triplestore**: los catálogos y series dados de baja se omiten (con sus ficheros) y se avisa, sin error; una serie que ya está en un catálogo se queda en él aunque su fichero diga otro (un traslado no se deshace); los catálogos creados por la API siguen en el raíz, y los `dcat:dataset` de cada catálogo publicado se mantienen (los de `data/catalogos/*.ttl` no se copian: la pertenencia la aporta cada serie). Los metadatos (título, descripción…) sí salen de los ficheros, como siempre. Una serie nueva necesita que su catálogo se cargue en la misma ejecución o ya exista.

Valida todo antes de escribir (estructura, URIs, ruta del fichero, SHACL y grafos repetidos): si un fichero no es válido, muestra sus errores y no carga ninguno (código 1). Es idempotente: lo que no ha cambiado no se reescribe, y las métricas de una versión de ontología solo se recalculan si su contenido cambia. Audita cada esquema, ontología y serie con `actor_username = "cli"`. Necesita `FUSEKI_USER`, `FUSEKI_PASSWORD` y la base de datos (auditoría y métricas).

### URIs persistentes en el despliegue (fase 5)

Las URIs se construyen con `BASE_URI` (p. ej. `https://<dominio>/itot/`) y el backend las sirve en su raíz (`/dataset/{slug}`). En el despliegue, el proxy inverso del dominio de `BASE_URI` debe:

- Enviar `{BASE_URI}dataset/*` al backend quitando el prefijo de ruta de `BASE_URI` (`/itot/dataset/x` → `/dataset/x`) y conservando la cabecera `Accept`.
- Dejar que el backend responda 303 a `FRONTEND_BASE_URL` cuando se pide HTML. Si frontend y URIs comparten dominio, `FRONTEND_BASE_URL` es ese mismo origen.
- Respetar `Vary: Accept` en cualquier caché (el backend lo envía).

Lo mismo vale para `{BASE_URI}onto/*` y `{BASE_URI}vocab/*` (fase 3) y para `{BASE_URI}catalogo` y `{BASE_URI}catalogo/*` (decisión 49). El resto de patrones (`actividad/`, `sparql`) se resolverán igual cuando tengan ruta en el backend.

## Endpoints (fase 3): vocabularios y ontologías

| Método y ruta | Acceso | Qué hace |
|---|---|---|
| `POST /ontologies` | editor (y admin) | Ingesta de **una versión** de ontología en Turtle o JSON-LD. Calcula métricas y consistencia antes de escribir. 201 si la versión es nueva, 200 si se sustituye (`changed=false` si era idéntica), 422 con el informe si no es válida |
| `POST /schemes` | editor (y admin) | Ingesta de un esquema SKOS con sus conceptos. Mismos códigos |
| `GET /vocabularies` | público | Tarjetas de ontologías propias (versión actual), externas y esquemas SKOS. Filtros `q` (nombre, descripción, prefijo o URI del recurso sin `BASE_URI`; desde la fase 4 ya no el espacio de nombres), `kind` (`own`, `external`, `skos_corp`, `skos_domain`) y `domain` (`it`, `ot`, `pqc`, `ia`); `counts` por tipo, sin filtros |
| `GET /ontologies/{slug}` | público | Ficha: metadatos VANN y DCT, versionado e historial, métricas, perfil, consistencia, cobertura de documentación, imports, alineamientos, uso en el catálogo y esquemas SKOS usados. `?version=` para otra versión |
| `GET /ontologies/{slug}/rdf` | público | RDF de la versión (actual o `?version=`): `?format=turtle\|rdfxml\|jsonld` o `Accept` |
| `GET /schemes/{slug}` y `GET /schemes/corp/{slug}` | público | Metadatos, dominio y árbol de conceptos |
| `GET /schemes/{slug}/concepts/{concepto}` (y con `corp/`) | público | Etiquetas por idioma, definición, `broader`/`narrower`/`related`, mapeos y recursos que lo usan |
| `GET /schemes/{slug}/rdf` (y con `corp/`) | público | RDF del esquema |
| `GET /onto/{slug}`, `GET /onto/{slug}/{version}` | público | URI persistente de la ontología (versión actual) o de una versión. HTML: 303 a `{FRONTEND_BASE_URL}/ontologias/{slug}` (`?version=`). Los términos `{BASE_URI}onto/{slug}#Término` se resuelven con la ontología |
| `GET /vocab/{slug}`, `GET /vocab/{slug}/{concepto}` (y con `corp/`) | público | URI persistente del esquema o del concepto. HTML: 303 a `{FRONTEND_BASE_URL}/vocabularios/{slug}` o `/vocabularios/corp/{slug}` (`?concepto=`) |

**Descarga del RDF:** `GET /datasets/{slug}/rdf`, `GET /ontologies/{slug}/rdf` y `GET /schemes/…/rdf` aceptan `?download=true` (o `1`). Con él, la respuesta lleva `Content-Disposition: attachment; filename="…"`, con un nombre hecho solo de slugs y versiones validados: `{slug}-{versión}.ttl` para datasets y ontologías (la versión pedida o la actual), `{slug}-{versión}` o `corp-{slug}-{versión}` (`owl:versionInfo`) para esquemas, con extensión `.ttl`, `.jsonld` o `.rdf` según el formato. Sin el parámetro (o con `false`) el RDF se sirve en línea, como hasta ahora.

**Rutas de los esquemas:** igual que sus URIs. Los de dominio en `/schemes/{slug}` (`{BASE_URI}vocab/{slug}`) y los corporativos en `/schemes/corp/{slug}` (`{BASE_URI}vocab/corp/{slug}`). `corp` es un slug reservado (no puede haber un esquema de dominio con ese nombre) y `externas` lo es en las ontologías. Todas las URIs persistentes ofrecen Turtle, JSON-LD, RDF/XML y HTML (303); desde la fase 4, sin `Accept` o con `*/*` responden el 303 (decisión 31); un recurso inexistente da 404 en cualquier formato. RDF/XML no puede representar predicados cuyo nombre local no es un nombre XML (p. ej. `<http://x.example/p/1>` o `<urn:x:1>`): si el recurso tiene alguno, RDF/XML responde **406** con un mensaje que remite a Turtle o JSON-LD, en lugar de 500 (QA-G3-05). La ingesta los admite porque Turtle y JSON-LD sí los representan.

### Tipos y estados (contrato con `semantico`)

| Tipo (`kind`) | Cómo se reconoce en el RDF |
|---|---|
| `own` | `owl:Ontology` con `owl:versionIRI`, en el grafo de su versión |
| `external` | `owl:Ontology` del grafo `{BASE_URI}onto/externas` (sin `versionIRI`) |
| `skos_corp` | `skos:ConceptScheme` bajo `{BASE_URI}vocab/corp/` |
| `skos_domain` | `skos:ConceptScheme` bajo `{BASE_URI}vocab/` con `dct:subject` hacia un concepto de `{BASE_URI}vocab/dominio` |
| `auxiliary` | Solo en `GET /schemes/{slug}` (`SchemeDetail.kind`): los esquemas sin dominio fuera de `corp/`, es decir, `vocab/dominio` y `vocab/tipo-dataset`. No tienen tarjeta en `/vocabularies` |

- **Estado:** `adms:status` `…/UnderDevelopment` es `draft`; `…/Completed` (o cualquier otro valor, o ninguno) es `published`; las externas son siempre `referenced`.
- **Sintético:** `synthetic=true` si el recurso lleva `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>` (en ontologías, en la cabecera de la versión).
- **Prefijo y espacio de nombres:** `vann:preferredNamespacePrefix` y `vann:preferredNamespaceUri` (IRI o literal); si falta el espacio de nombres, `{ontología}#` o `{esquema}/`.
- **Versión:** de una ontología, el último segmento de su `owl:versionIRI`; de un esquema o una externa, `owl:versionInfo`.
- **Versión actual de una ontología:** la de mayor número de entre las cargadas.
- **Dominio de la tarjeta (`domain`):** el mismo `DomainRef` que en los datasets, solo para los esquemas de dominio (su `dct:subject`). Las ontologías (propias y externas) y los esquemas corporativos no tienen dominio en el RDF: `null`. No se deduce de los `dct:subject` de una ontología. Con el filtro `domain`, las tarjetas sin dominio no aparecen.
- **Responsable del esquema:** `responsible` es siempre `null` hasta que se decida (decisión abierta 11).
- **Placeholders:** licencia, autores, fechas… que no están en el RDF se devuelven como `null` o lista vacía.

### Ficha de ontología

- **Imports:** los `owl:imports` declarados, con título, prefijo y versión si la ontología importada está en las externas (`known`).
- **Alineamientos:** axiomas `rdfs:subClassOf`, `owl:equivalentClass`, `rdfs:subPropertyOf`, `owl:equivalentProperty`, `owl:sameAs` y `skos:exactMatch`/`closeMatch`/`broadMatch`/`narrowMatch`/`relatedMatch` de un término propio (`{ontología}#…`) hacia un término fuera de `BASE_URI`, agrupados por ontología destino y relación. La ontología destino es la externa (o el import) cuyo espacio de nombres contiene el término. `scope` sale del `rdfs:comment` o `dct:description` de la anotación del axioma (`owl:Axiom` con `owl:annotatedSource/Property/Target`), si existe. Las declaraciones de términos externos (`d3f:DefensiveTechnique a owl:Class`) no son alineamientos.
- **Versionado:** `owl:versionIRI`, `owl:priorVersion`, `owl:backwardCompatibleWith` e historial con `adms:versionNotes` (versiones solo referenciadas por `owl:priorVersion`: `described=false`).
- **Uso en el catálogo:** series con alguna versión con `dct:conformsTo` hacia la ontología o una de sus versiones.
- **Esquemas usados:** los `dct:subject` de la versión (esquemas o conceptos), con su etiqueta y su esquema.

### Navegador SKOS

- **Árbol:** se construye sin recursión y se sirve hasta 64 niveles (lo que admite la ingesta); cada nodo lleva `uri`, `slug`, `label`, `top_concept`, `alt_labels` (lista de `{value, lang}`, como en el concepto) y `children`. Raíces = conceptos con `skos:topConceptOf`/`skos:hasTopConcept` y los que no tienen padre dentro del esquema; hijos = `skos:narrower` más la inversa de `skos:broader`. Ordenado por etiqueta. Un ciclo no se recorre dos veces.
- **Concepto:** `pref_labels`, `alt_labels` y `definitions` como lista de `{value, lang}`; `broader`, `narrower` y `related` (en los dos sentidos) con etiqueta; `exact_match` y `close_match`; usos: series con versiones con `dcat:theme` hacia el concepto y ontologías propias con `dct:subject`.

### Límites de la ingesta

Valen para `POST /datasets`, `POST /ontologies`, `POST /schemes` y `load-semantic`. Superar cualquiera da 422 con `kind=limit` y no se escribe nada.

| Límite | Valor | Cuándo se comprueba |
|---|---|---|
| Tamaño del cuerpo | `INGEST_MAX_BYTES` (10 MiB; 413) | Al leer el cuerpo, antes de analizarlo |
| Anidamiento | 64 niveles (JSON y nodos en blanco) | Antes y después de analizar |
| Longitud de una IRI | 4096 caracteres | **Durante el análisis**, en cada tripleta |
| Tripletas | `INGEST_MAX_TRIPLES` (100 000) | Durante el análisis |
| Tamaño expandido (suma de la longitud de los términos de todas las tripletas) | 32 × tamaño del cuerpo + 1 MiB, y como mucho 32 Mi caracteres | Durante el análisis. Corta la «bomba de prefijos» (QA-G3-03): ~100 KB con un prefijo de 100 KB repetido ya no ocupan ~60 MB; el análisis se aborta en la primera IRI desmesurada. Un Turtle normal expande unas 2 veces |
| Profundidad de la jerarquía de un esquema | 64 niveles de `skos:broader`/`skos:narrower` | En la ingesta del esquema (QA-G3-04) |
| Validación SHACL | `SHACL_TIMEOUT_SECONDS` (60 s) y `SHACL_MEMORY_MB` (2048) | En un proceso hijo que se mata al agotar el tiempo: no quedan hilos ni procesos colgados (QA-G3-10) |
| Pellet | `REASONER_TIMEOUT_SECONDS` (120 s) y `REASONER_JAVA_MEMORY_MB` | Al agotarse, la ontología se publica con `consistent: null` |

Los límites se comprueban en el store en memoria del analizador (también JSON-LD, que escribe en el store sin pasar por `Graph.add`). La validación SHACL usa procesos de un *forkserver* de `multiprocessing` que ya tiene rdflib y pyshacl importados, así que crear uno cuesta milisegundos; el grafo y el informe viajan en N-Triples.

### Ingesta de ontologías y esquemas

Misma estrategia que `POST /datasets` (autenticación antes de leer el cuerpo, sin contextos JSON-LD remotos, IRIs válidas, anidamiento máximo de 64 niveles, nada se escribe si algo falla, y se sustituye el grafo completo salvo que sea isomorfo):

- **Ontología:** exactamente una `owl:Ontology` con URI `{BASE_URI}onto/{slug}` y **exactamente un `owl:versionIRI`** `{BASE_URI}onto/{slug}/{MAYOR.MENOR.PARCHE}` (la ingesta lo exige a toda ontología bajo `BASE_URI`: SHACL no puede, porque no conoce `BASE_URI`). `owl:versionInfo`, si está, es igual a la versión; `owl:priorVersion`, `owl:backwardCompatibleWith` y `owl:incompatibleWith` apuntan a versiones anteriores de la misma ontología. Bajo `BASE_URI` solo se pueden describir la ontología, su `versionIRI` y sus términos (`{ontología}#Término`); se admiten sujetos externos (las declaraciones de términos importados), que solo viven en el grafo de la versión. Se guarda en el grafo de su `versionIRI`.
- **Esquema:** exactamente un `skos:ConceptScheme` con URI `{BASE_URI}vocab/{slug}` o `{BASE_URI}vocab/corp/{slug}`; todo sujeto con IRI es el esquema o un concepto `{esquema}/{slug}`; la jerarquía tiene como mucho 64 niveles. Se guarda en el grafo de su URI. Los esquemas auxiliares `vocab/dominio` y `vocab/tipo-dataset` están reservados (QA-G3-06): la API los rechaza con 422 y solo los carga `load-semantic` desde `data/vocab-minimo.ttl`.
- **SHACL:** todas las formas de `SEMANTIC_DIR/shapes` (entre ellas `ontologias-vocabularios.ttl` de `semantico`), sin mezclar el grafo de soporte: una versión o un esquema se validan solos.
- **Métricas antes de escribir:** en la API y en `load-semantic` las métricas y la consistencia se calculan antes de tocar Fuseki. Si owlready2 no puede leer la ontología (p. ej. un literal que no cumple su tipo, `"abc"^^xsd:integer`), la respuesta es 422 `syntax` con los literales culpables y no se escribe nada; en `load-semantic`, no se carga ningún fichero (QA-G3-01).
- **Auditoría:** `ontology_published` (`ontology`, `slug`, `version`, `version_iri`, `graph`, `triples`, `created`, `changed`, `metrics_recomputed`, `consistent`, `via`) y `scheme_published` (`scheme`, `slug`, `corp`, `graph`, `concepts`, `triples`, `created`, `changed`, `via`).
- **Versiones publicadas (fase 4, decisión 28):** una `owl:versionIRI` ya publicada con otro contenido da 409 `version_immutable` (antes de calcular métricas); con el mismo contenido, la ingesta es idempotente y no recalcula métricas. Los esquemas SKOS no cambian: su versión no forma parte de la URI.

### Métricas OWL y consistencia

Decisión del responsable (2026-11-15): owlready2 para las métricas y Pellet (incluido en owlready2) para la consistencia. Se calculan **en la ingesta** (`POST /ontologies` y `load-semantic`), antes de escribir en Fuseki, y no en cada visita.

| Campo | Cómo se calcula |
|---|---|
| `classes`, `object_properties`, `data_properties`, `annotation_properties`, `individuals` | Entidades con nombre de owlready2 (`classes()`, `object_properties()`…, `individuals()` = `owl:NamedIndividual`) **del espacio de nombres propio** `{ontología}#`. Las declaraciones de términos externos (`d3f:DefensiveTechnique a owl:Class`, `dct:title a owl:AnnotationProperty`) no cuentan |
| `logical_axioms` | owlready2 no da un recuento de axiomas: se cuentan sobre el mismo grafo los triples que en el mapeo OWL 2 → RDF son axiomas lógicos (`rdfs:subClassOf`, `owl:equivalentClass`, `owl:disjointWith`, dominios y rangos de propiedades de objeto y de datos, características de propiedades, aserciones de clase y de propiedad, `owl:sameAs`…). Aproxima el `getLogicalAxiomCount` de la OWL API |
| `imports` | `owl:imports` **declarados** |
| `profile` | Aproximado por constructores: `OWL 2 Full` si una IRI es a la vez propiedad de objeto y de datos (o clase y tipo de datos); si no, `OWL 2 DL`. `compatible` lista EL, QL y RL salvo que aparezca un constructor que el perfil no admite (y, para RL, algunas posiciones en `rdfs:subClassOf` y cardinalidades máximas mayores que 1). No es un validador completo: puede declarar compatible un perfil que no lo es |
| `documentation` | Clases y propiedades (de objeto y de datos) propias con al menos un `rdfs:comment`, en número y porcentaje |
| `dl_expressivity` | No se calcula: siempre `null` |
| `consistency` | Pellet (`reasoner: "Pellet"`): `consistent` y número de clases insatisfacibles (equivalentes a `owl:Nothing`) con sus IRIs. Si Java falta o es anterior a la 25, si Pellet falla (por cualquier excepción) o si supera `REASONER_TIMEOUT_SECONDS`, `consistent` es `null` y `detail` da un motivo genérico; la traza de Java solo va al log del servidor (QA-G3-02). Una ontología inconsistente se acepta y se publica con `consistent: false` |

**Sin descargas remotas.** Los `owl:imports` (SOSA, SAREF…) **no se descargan nunca**: antes de pasar el grafo a owlready2 se quitan los triples `owl:imports`, y Pellet se lanza con `--ignore-imports`. Limitación: el razonamiento se hace **sin las ontologías importadas**, así que una inconsistencia que dependa de axiomas de SOSA o SAREF no se detecta y los términos externos se tratan como clases sin axiomas (`includes_imports: false` en la respuesta). Las pruebas cortan la red de Python y comprueban que el fichero que recibe Pellet no lleva `owl:imports`.

**Dónde se guardan:** en PostgreSQL, tabla `ontology_metrics` (migración `0002`), una fila por `versionIRI` con las métricas, la consistencia, la herramienta, la fecha y el SHA-256 del grafo canónico de la versión. Motivos: son datos derivados que calcula el backend, no parte del RDF versionado en Git, y así el grafo de la versión guarda exactamente el fichero publicado (la comparación isomorfa y el RDF que se sirve no cambian); no hay un vocabulario RDF decidido para describir métricas ni un patrón de URI para un grafo de metadatos por versión, y crearlos sería un cambio de contrato con `semantico`; y el hash permite no recalcular si el contenido no cambia. Contrapartida: las métricas no se pueden consultar por SPARQL y las lecturas de ontologías necesitan la base de datos.

Cada ejecución de Pellet usa un directorio temporal propio que se borra siempre, también si Pellet falla o se agota el tiempo (owlready2 solo borra su fichero temporal cuando todo va bien; QA-G3-07). Las ingestas se serializan al usar owlready2 (tiene estado global). Pellet tarda alrededor de un segundo por versión en las ontologías de demostración.

## Fase 4: FAIR, versiones, ficheros y SPARQL público

| Método y ruta | Acceso | Qué hace |
|---|---|---|
| `PUT /datasets/{slug}/versions/{version}/distributions/{dist}/file` | editor (y admin) | Sube el fichero de una distribución (`multipart/form-data`, campo `file`). 201, o 200 si ya estaba con el mismo SHA-256; 409 `file_exists` / `non_public`; 413 si supera `MAX_UPLOAD_MB` |
| `POST /datasets/{slug}/versions/{version}/distributions/{dist}/download-link` | con cuenta | Enlace firmado `{url, expires_at}` de un solo uso para descargar sin poner el JWT en la URL |
| `GET /dataset/{slug}/{version}/{dist}/fichero` | según `dct:accessRights` | El fichero, en streaming |
| `GET /dataset/{slug}/{version}/{dist}` | público | URI persistente de la distribución (RDF; HTML: 303 a la ficha `#distribuciones`) |
| `GET /datasets/{slug}/versions/{version}/fair/report` | público | Informe completo de F-UJI de la última evaluación `done`, sin URLs internas (404 si no hay) |
| `POST /datasets/{slug}/versions/{version}/fair` | editor (y admin) | Pide otra evaluación (202 con `FairSummary` en `pending`) |
| `GET /sparql`, `POST /sparql` | público (con JWT, límite de usuario) | SPARQL de solo lectura con límites |
| `GET /sparql/queries` | público (con JWT, también las personales) | Consultas de referencia y personales (lista `SavedQuery[]`) |
| `POST /sparql/queries`, `PUT`/`DELETE /sparql/queries/{id}` | con cuenta (solo el dueño) | Consultas personales |

### Versiones inmutables (decisión 28)

- `POST /datasets` y `load-semantic`: antes de escribir, cada versión del grafo publicado tiene que venir en la petición y su subgrafo (sus triples, los de sus distribuciones y su procedencia PROV, `catalog.version_subgraph`) debe ser **isomorfo** al publicado (`rdflib.compare.isomorphic`, que trata los nodos en blanco por estructura y no por etiqueta). Si falta, 409 `version_removed`; si cambia, 409 `version_immutable`. Las versiones afectadas van en `issues[].focus_node` de `IngestErrorResponse`. Los metadatos de la serie (título, `dcat:last`…) sí cambian.
- Un nodo compartido por varias versiones (el `publisher` en blanco, una actividad PROV con IRI) forma parte del subgrafo de cada versión que lo usa: cambiarlo cambia esas versiones (409).
- `POST /ontologies`: una `owl:versionIRI` ya publicada con otro contenido da 409 antes de calcular métricas.
- `load-semantic` valida la inmutabilidad (leyendo Fuseki) antes de escribir nada: si una versión cambia, no carga ningún fichero.
- `fichero` es un segmento reservado: no puede ser el slug de una distribución (422 `uri`). El último segmento de una distribución tiene que ser un slug.

### Catálogo (decisión 29)

Desde la decisión 49 el backend mantiene `<{BASE_URI}catalogo/{slug}> dcat:dataset <serie>` en el grafo del catálogo de cada serie (ya no en el raíz). Ver «Catálogos y bajas».

### Ficheros de distribución (decisiones 40 y 41)

- **Dónde:** el contenido, en la interfaz de almacenamiento (`app/storage.py`); tamaño, SHA-256, tipo de medio y quién lo subió, en la tabla `distribution_files`. El RDF publicado **no cambia**.
- **Clave:** `{slug}/{version}/{dist}`, sin extensión, igual en disco y en R2. Se construye solo con segmentos validados por su patrón, y el disco comprueba además que la ruta resuelta queda dentro de `STORAGE_DISK_PATH` (sin *path traversal*). Un enlace simbólico que sale de la raíz se trata como un fichero que no existe (404 al descargar, 503 al escribir).
- **Escritura:** la subida se lee en streaming del `multipart` a un temporal (en memoria hasta 1 MiB) y se corta en cuanto pasa de `MAX_UPLOAD_MB`, aunque no haya `Content-Length`. En disco se escribe a un temporal de la misma carpeta, con `fsync`, y se renombra (`os.replace`): un fichero a medias nunca se ve.
- **Inmutables:** otro contenido para la misma clave da 409 `file_exists`; el mismo, 200. El registro de `distribution_files` se inserta **antes** de escribir el fichero: con subidas simultáneas de la misma distribución, la clave primaria deja pasar a una (201) y las demás esperan a que termine y responden como una subida repetida (200 si el SHA-256 coincide, 409 `file_exists` si no), sin sobrescribir el fichero de la primera (QA-G4-05). Si la escritura falla, el registro se deshace.
- **Tipo de medio:** el `dcat:mediaType` del RDF, nunca el del cliente. Sin él (NPZ), `application/octet-stream`.
- **Estado en la ficha** (`DistributionRead`): `download` es `open` (PUBLIC con fichero), `authenticated` (RESTRICTED con fichero), `metadata_only` (NON_PUBLIC, nunca tiene fichero) o `unavailable` (sin fichero, u otro `accessRights`). El `accessRights` efectivo es el de la distribución o, si no tiene, el de su versión. `download_url` es la URI del fichero, `{BASE_URI}dataset/{slug}/{version}/{dist}/fichero`, solo con `open` o `authenticated`; `byte_size` y `sha256`, si hay fichero.
- **Descarga** (`GET /dataset/{slug}/{version}/{dist}/fichero`): `open`, cualquiera; `authenticated`, con `Authorization: Bearer` o con `?token=` de `download-link` (sin ellos 401); `metadata_only` y `unavailable`, 404. Respuesta en streaming con el `Content-Type` del RDF, `Content-Length` y `Content-Disposition: attachment; filename="{slug}-{version}-{dist}.{ext}"` (extensión por el tipo de medio y, si no se conoce, el slug de la distribución: `npz`). Las descargas `authenticated` se auditan (`distribution_downloaded`); las `open`, no.
- **Enlace firmado:** un JWT HMAC con `JWT_SECRET` y `aud` propio (el token de acceso no vale como enlace ni el enlace como token de acceso), ligado a `storage_key` y al usuario, válido `DOWNLOAD_LINK_TTL_SECONDS` y **de un solo uso** (su `jti` queda en `used_download_tokens`; vale con varios workers). Si la cuenta se da de baja o se revocan sus tokens, el enlace deja de valer. `url` es una ruta relativa a la API (`/dataset/…/fichero?token=…`).
- **`load-semantic`** sube `data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}` con las mismas reglas y actor `cli`, después de las series. Valida antes de escribir que la distribución existe, que no es NON_PUBLIC, el tamaño y que no cambia un fichero ya subido. Que falte el fichero de una distribución no es un error (queda `unavailable`). Los bytes se suben tal cual (el SHA-256 depende de ellos: `semantic/.gitattributes` los marca `-text`).

### Almacenamiento

`STORAGE_BACKEND=disk` (MVP) usa `STORAGE_DISK_PATH` (en la imagen, `/data/distributions`, del usuario sin privilegios). **`STORAGE_BACKEND=r2` todavía no está implementado:** falta decidir el cliente (p. ej. `boto3`, que sería una dependencia nueva) y los nombres de las variables de credenciales; hasta entonces responde 503 con un mensaje claro en cualquier operación con ficheros.

### Evaluación FAIR con F-UJI (decisión 45)

- Al publicar una versión **nueva** (API o `load-semantic`) se encola su evaluación (`fair_evaluations`, estado `pending`) sin bloquear la publicación. Una versión que ya tiene alguna evaluación no se reevalúa sola; un editor puede pedirlo con `POST …/fair`.
- Un **trabajador en segundo plano** (hilo que arranca con la API) reclama cada pendiente con un `UPDATE … WHERE status='pending'` atómico (con varios workers nadie evalúa dos veces lo mismo), se despierta al publicar y cada `FAIR_WORKER_POLL_SECONDS` (así recoge lo que encola `load-semantic`). Sobrevive a cualquier error. Una evaluación `running` huérfana (reinicio a mitad) pasa a `failed` pasado `FUJI_TIMEOUT_SECONDS` + 2 min.
- Petición a F-UJI: `POST {FUJI_URL}/evaluate` con Basic, `object_identifier` = `{FAIR_TARGET_BASE_URL}datasets/{slug}/rdf?version={version}&format=turtle`, `metadata_service_endpoint` = `{FAIR_TARGET_BASE_URL}sparql` con `metadata_service_type=sparql`, `metric_version=metrics_v0.5`, `use_datacite=false`, `use_github=false` y `test_debug=false`. La URL evaluada se guarda en `fair_evaluations.evaluated_url`.
- **Por qué el RDF y no la URI persistente (QA-G4-01):** F-UJI 4.0.1 pide el identificador con `Accept: text/html, */*`; la URI persistente responde 303 a la ficha del frontend (decisión 31) y F-UJI sigue la redirección. El frontend no está en la red de F-UJI (`fuji-net`, sin salida) y, aunque lo estuviera, es una aplicación de una sola página sin metadatos en el HTML. Sin página de destino, F-UJI no recoge ningún metadato (ni por negociación ni por SPARQL, donde manda `DESCRIBE <None>`) y la nota cae a 8.33. El signposting del 303 no lo evita: F-UJI solo lee las cabeceras `Link` de la respuesta final. La URL del RDF responde Turtle con cualquier `Accept` y el RDF identifica la versión con su URI persistente. Medido con F-UJI 4.0.1 real y los datos sintéticos: 52.08 en las versiones actuales (F 35.71, A 100, I 50, R 50).
- **Informe público** (`GET …/fair/report`): el informe se guarda tal cual, pero al servirlo la URL evaluada se sustituye por la URI persistente de la versión y cualquier otra aparición de `FAIR_TARGET_BASE_URL` por `BASE_URI`, para no publicar hosts internos (`http://backend:8000`).
- **Puntuaciones:** solo de la respuesta de F-UJI (esquema `FAIRResults` de su `openapi.yaml`): `summary.score_percent` `FAIR` (total), `F`, `A`, `I` y `R`, tal cual (F-UJI las redondea a dos decimales; aquí no se redondean más), y `summary.maturity.FAIR` como nivel, convertido a texto sin cambiarlo (`2.25` → `"2.25"`). `evaluator` es `F-UJI {software_version} ({metric_version})`. Si el resumen no trae el total o algún valor no es un número entre 0 y 100, la evaluación queda `failed` («La respuesta de F-UJI no es válida»).
- **Errores** (F-UJI caído, timeout, 4xx/5xx, respuesta no válida, sin credenciales): `failed` con un mensaje fijo, sin trazas ni rutas. La ficha nunca se rompe.
- **Ficha** (`VersionDetail.fair`, `FairSummary`): `status` es el de la evaluación más reciente (`not_evaluated` si no hay ninguna); puntuaciones, nivel, evaluador y `evaluated_at` son los de la última `done` (una reevaluación en curso sigue mostrando la anterior). `report_url` es la ruta relativa `/datasets/{slug}/versions/{version}/fair/report`. `DatasetCard.fair_total` es el total de la última `done` de la versión actual.
- Auditoría `fair_evaluated` al terminar, con su estado.

### SPARQL público (decisión 42)

- Validación con el analizador de rdflib **antes** de llamar a Fuseki: como mucho 20 KB (413); solo `SELECT`, `ASK`, `CONSTRUCT` y `DESCRIBE` (una actualización da 400 «solo lectura»); sin `SERVICE` en ningún punto (400); `FROM`/`FROM NAMED` solo hacia IRIs bajo `BASE_URI` (todos los grafos que escribe el backend están ahí y son públicos). Un error de sintaxis da 400 con línea y columna, sin trazas. Una consulta que Jena admite pero rdflib no sabe analizar también da 400.
- Se ejecuta contra `/{FUSEKI_DATASET}/query` (anónimo, solo lectura), con el grafo por defecto de Fuseki (`unionDefaultGraph`, como esperan las consultas de referencia). Tiempo máximo total `SPARQL_TIMEOUT_SECONDS` (también se pasa a Fuseki como `timeout`); al superarlo, o si Fuseki responde 503, **504**.
- Resultados recortados a `SPARQL_MAX_ROWS` con `X-Result-Truncated: true`. Todo se lee de Fuseki en streaming y se corta la conexión al llegar al límite: los triples (CONSTRUCT/DESCRIBE) en N-Triples, línea a línea; las filas (SELECT) en JSON, fila a fila. Lo procesado se acota además a 32 MiB: si se alcanza antes de `SPARQL_MAX_ROWS` filas, el resultado también se recorta con la misma cabecera (QA-G4-03); solo da 400 si una sola fila (o la cabecera) supera ese tope.
- Formatos por `Accept`: SELECT/ASK, `application/sparql-results+json` (por defecto) o `text/csv`; CONSTRUCT/DESCRIBE, `text/turtle` (por defecto), `application/ld+json`, `application/rdf+xml` (406 si el grafo tiene predicados que RDF/XML no representa) o `application/n-triples`. Con `Accept: application/sparql-results+json, text/turtle;q=0.9` (el del frontend) cada tipo de consulta recibe su formato. Sin ningún formato válido, 406.
- **Límite de frecuencia:** `SPARQL_RATE_ANON_PER_MIN` por IP y `SPARQL_RATE_AUTH_PER_MIN` por usuario, con ventana fija de un minuto guardada en PostgreSQL (`rate_limit_counters`, incremento atómico con `INSERT … ON CONFLICT`), así que vale con varios workers y réplicas. Al superarlo, 429 con `Retry-After`. En el peor caso la ventana fija admite el doble del límite en el cambio de minuto.
- **IP del cliente:** la de la conexión (`request.client`); `X-Forwarded-For` se ignora. uvicorn solo reescribe la IP con esa cabecera si la conexión llega desde una IP de `FORWARDED_ALLOW_IPS` (por defecto `127.0.0.1`); detrás de un proxy inverso (fase 5) esa variable de uvicorn es la configuración explícita de proxies de confianza.
- CORS expone `X-Result-Truncated`, `Retry-After` y `Content-Disposition`.

### Consultas guardadas (decisión 43)

- **De referencia:** `SEMANTIC_DIR/consultas/{id}.rq` (de `semantico`), en orden alfabético de `id`. Se leen las líneas `# title:` y `# hint:` del principio, se quitan del texto (el resto de comentarios se conserva) y `{BASE_URI}` se sustituye por `BASE_URI`. No se pueden cambiar ni borrar (404).
- **Personales:** tabla `saved_queries`; solo las ve, cambia (`PUT`, cuerpo completo) y borra su dueño. Las de otro usuario dan 404. `title` 1-120, `hint` 0-200, `query` hasta 20 KB, sin caracteres de control (salvo saltos de línea y tabuladores en la consulta). Como mucho `SAVED_QUERIES_MAX_PER_USER` (409). Se guarda el texto, no se ejecuta. Auditoría `saved_query_created` y `saved_query_deleted` con el id, nunca el texto.

### Migraciones

`0003` añade `users.tokens_valid_after` y las tablas `distribution_files`, `used_download_tokens`, `fair_evaluations`, `saved_queries`, `login_attempts` y `rate_limit_counters`.

## Catálogos y bajas (decisión 49)

Varios catálogos `{BASE_URI}catalogo/{slug}`, cada dataset (serie) en exactamente uno, y borrado lógico. Contrato en `semantic/uris.md` («Catálogos y borrado lógico»).

| Método y ruta | Acceso | Respuestas | Qué hace |
|---|---|---|---|
| `GET /catalogs` | público | 200 | Catálogos (sin el raíz ni las bajas), por título, con `dataset_count` |
| `GET /catalogs/{slug}` | público | 200, 404, 410 | Ficha del catálogo con sus datasets |
| `POST /catalogs` | editor, admin | 201, 401, 403, 409, 422 | Crea un catálogo vacío y lo añade al raíz (`dcat:catalog`). 409 con `kind` `slug_in_use` o `withdrawn` |
| `PATCH /catalogs/{slug}` | editor, admin | 200, 401, 403, 404, 410, 422 | Edita título, descripción o publicador (solo los campos presentes) |
| `DELETE /catalogs/{slug}` | editor, admin | 204, 401, 403, 404, 409, 410 | Da de baja un catálogo **vacío**; con datasets, 409 `kind=catalog_not_empty` con `datasets` |
| `POST /catalogs/{slug}/datasets` | editor, admin | 201, 401, 403, 404, 409, 410, 422 | Crea un dataset (serie sin versiones) en el catálogo. 409 con `kind` `slug_in_use` o `withdrawn` |
| `PATCH /datasets/{slug}` | editor, admin | 200, 401, 403, 404, 410, 422 | Edita los metadatos de la serie y, con `catalog`, la mueve de catálogo |
| `DELETE /datasets/{slug}` | editor, admin | 204, 401, 403, 404, 410 | Da de baja el dataset y elimina sus ficheros |
| `GET /catalogo`, `GET /catalogo/{slug}` | público | 200, 303, 404, 406, 410 | URIs persistentes del raíz y de un catálogo: RDF con `Accept` de RDF; si no, 303 a `{FRONTEND_BASE_URL}/` o `{FRONTEND_BASE_URL}/catalogos/{slug}` |

El catálogo raíz no se crea, edita ni borra por la API: cambia solo con `data/catalogo.ttl` y `load-semantic`.

**Formularios en JSON.** Los cuerpos de catálogos y datasets son JSON con los campos que exigen las formas (`slug`, `title`, `description`, `publisher_name`; `catalog` para mover), sin campos extra (422). El backend los convierte a RDF (`title` y `description` en `@es`; el publicador, un nodo en blanco `foaf:Agent` con `foaf:name`, porque los agentes aún no tienen URI) y los valida con **todas** las formas SHACL, igual que una ingesta. Las versiones se siguen publicando con `POST /datasets` en RDF, porque una versión DCAT-AP (distribuciones, procedencia PROV, temas) no cabe en un formulario plano y la inmutabilidad se comprueba sobre el RDF.

**Conflictos (409).** El cuerpo es `ConflictResponse`: `detail`, `kind` y `datasets`. `kind` distingue `slug_in_use` (ya existe un recurso con ese slug), `withdrawn` (el slug es de un recurso dado de baja y no se reutiliza) y `catalog_not_empty` (dar de baja un catálogo con datasets; `datasets` lleva sus URIs). En `POST /datasets` (RDF) los 409 siguen siendo `IngestErrorResponse`, con `kind` `withdrawn`, `catalog_conflict`, `version_removed` o `version_immutable`.

**Publicador de la serie.** `DatasetDetail.publisher` es el `dct:publisher` de la serie, con la misma forma que en el detalle del catálogo (`ResourceRef`: `label` es el `foaf:name` y `uri` es `null` si es un nodo en blanco). Es el valor que edita `publisher_name` en `PATCH /datasets/{slug}`; el de cada versión sigue en `version.metadata.publisher`.

**Editar no toca las versiones.** `PATCH /datasets/{slug}` cambia solo triples de la serie; las versiones publicadas siguen siendo inmutables (decisión 28). Mover un dataset quita el triple del catálogo de origen y lo añade al de destino; ninguna URI cambia.

**Baja (borrado lógico).** El grafo del recurso se borra, se quita el enlace desde su catálogo (o el `dcat:catalog` del raíz), los ficheros de distribución se eliminan del almacenamiento (y sus filas de `distribution_files`; las evaluaciones FAIR pendientes pasan a `failed`) y queda una lápida en `{BASE_URI}bajas` (`prov:Entity`, `dct:title`, `adms:status …/Withdrawn` y `prov:invalidatedAtTime` con la hora del servidor), validada con `itsh:BajaShape`. Quién la dio de baja va a la auditoría (`catalog_withdrawn`, `dataset_withdrawn`), no al RDF. Si no se puede borrar un fichero, la baja sigue y la clave queda en `files_not_deleted` del evento.

**410 Gone.** La URI de un catálogo o una serie dados de baja, y por prefijo las de sus versiones, distribuciones y ficheros (`/dataset/{slug}/…`), responden 410 con la ficha mínima: en la API JSON (`GoneResponse`: `uri`, `resource`, `title`, `withdrawn_at`) y en las URIs persistentes en HTML (sin `Accept`, `*/*` o `text/html`; aquí no hay 303, porque el frontend respondería 200) o en RDF (la lápida). Un slug dado de baja no se reutiliza: crear otro recurso con él da 409.

**Fuera de SPARQL.** El SPARQL público pasa a Fuseki la descripción del dataset en el protocolo (`default-graph-uri` y `named-graph-uri` con todos los grafos salvo `{BASE_URI}bajas`), así que ni el grafo por defecto ni `GRAPH ?g` ven las lápidas. Si la consulta trae `FROM`/`FROM NAMED`, el dataset es el que nombra, y `{BASE_URI}bajas` ahí da 400. Los listados no leen ese grafo.

**Auditoría.** `catalog_created`, `catalog_updated`, `catalog_withdrawn`, `dataset_created`, `dataset_updated` (con `moved_from`) y `dataset_withdrawn`.

**Concurrencia (QA-49-01).** Ninguna escritura de catálogos, pertenencias o lápidas lee un grafo entero para reescribirlo: añadir triples es un `POST` del Graph Store Protocol (`append_graph`, se añade sin tocar lo demás) y quitarlos, un SPARQL Update `DELETE DATA` o `DELETE … WHERE` solo con IRIs validadas; mover un dataset de catálogo es una sola petición de Update. Además, las operaciones que comprueban y escriben (slug libre y crear, catálogo vacío y dar de baja, editar metadatos, publicar una serie y la escritura de `load-semantic`) se serializan con `app.write_lock`: un **advisory lock** de PostgreSQL (`pg_advisory_lock`, en una conexión propia; vale entre workers y réplicas y con la CLI) más un `RLock` del proceso, reentrante en el mismo hilo. Es un único bloqueo global porque estas escrituras son pocas y tocan grafos compartidos (raíz, bajas, catálogo de origen y de destino); así no hay riesgo de interbloqueo. El usuario de Fuseki del backend necesita permiso en `/update` además de `/data` (el `infra/fuseki/assembler.ttl` actual ya lo da). `load-semantic` vuelve a leer las bajas dentro del bloqueo y omite lo que se haya dado de baja mientras validaba.

**Ficheros huérfanos (QA-49-02).** Al dar de baja un dataset se borran los ficheros con fila en `distribution_files` y, después, toda la carpeta `{slug}/` del almacenamiento (`Storage.delete_prefix`), también lo que no tenga fila. Solo ese slug: `prueba-otra/` no se toca al dar de baja `prueba`.

## Roles y autorización

- `lector`: anónimo, sin cuenta. Ve lo público.
- `miembro`, `editor` y `admin`: cuentas guardadas en PostgreSQL.

El JWT lleva `sub` (id de la cuenta), `username`, `role`, `iat`, `iat_us` (instante de emisión en microsegundos, fase 4) y `exp`. El rol del token es informativo para el frontend: en cada petición el backend vuelve a leer la cuenta de la base de datos, así que un cambio de rol o una baja tienen efecto inmediato. Además (fase 4, decisión 18), `users.tokens_valid_after` se fija al dar de baja una cuenta o cambiar su rol (y servirá para el cambio de contraseña cuando exista): un token emitido antes da 401, y reactivar la cuenta no revive los tokens viejos. `iat_us` evita que sobreviva un token emitido en el mismo segundo que la baja sin cambiar el `iat` estándar en segundos.

Para proteger rutas en las fases siguientes:

```python
from typing import Annotated
from fastapi import Depends
from app.deps import OptionalUser, require_role
from app.models import Role, User


@router.post("/datasets")
def publicar(user: Annotated[User, Depends(require_role(Role.EDITOR))]): ...  # admin hereda


@router.get("/datasets")
def listar(user: OptionalUser): ...  # None = lector anónimo
```

**Herencia de roles** (decisión del responsable, 2026-11-14): **admin hereda los permisos de editor**, y es la única herencia. Está declarada en `ROLE_INHERITS` (`app/deps.py`) y la aplica `require_role`: `require_role(Role.EDITOR)` admite a editor y admin; `require_role(Role.MIEMBRO)` solo a miembro; `require_role(Role.ADMIN)` solo a admin. Las pruebas de `tests/test_require_role.py` fijan la tabla completa.

Un admin no puede quitarse el rol de admin ni darse de baja a sí mismo (409), para que la unidad no se quede sin admin por error.

## Contraseñas y auditoría

- Contraseñas con argon2id (`pwdlib`). Mínimo 12 caracteres, sin caracteres de control. Nunca se devuelven ni se registran.
- El login responde igual (401, mismo mensaje) si el usuario no existe, la contraseña es incorrecta, la cuenta está de baja o el nombre de usuario contiene caracteres de control (NUL incluido). En este último caso no se consulta la cuenta y la auditoría registra el motivo `invalid_username`.
- **Bloqueo (fase 4, decisión 18):** los fallos se cuentan por (nombre normalizado —sin controles, sin espacios alrededor y en minúsculas—, IP de la conexión) en la tabla `login_attempts`, así que vale con varios workers. El fallo número `LOGIN_MAX_FAILURES` dentro de `LOGIN_WINDOW_MINUTES` responde aún 401 y bloquea el par; desde ahí, cualquier intento responde **429 con `Retry-After`** durante `LOGIN_LOCKOUT_MINUTES`, aunque la contraseña sea correcta (se audita `login_locked` una vez, al empezar el bloqueo; los intentos bloqueados no escriben auditoría, para que los reintentos no llenen `audit_events`). Un login correcto borra el contador del par. Al registrar cada fallo se borran los pares sin bloqueo vigente cuya ventana ya caducó, así que `login_attempts` no crece sin límite.
- Los nombres de usuario y las contraseñas con caracteres de control se rechazan en `POST /users` con 422.
- Las respuestas 422 siguen el formato de FastAPI (`detail` con `type`, `loc` y `msg`), pero nunca devuelven el valor enviado (`input`) ni el contexto (`ctx`), para no reflejar contraseñas.
- La tabla `audit_events` registra `login_success`, `login_failure` (con el motivo), `user_created`, `role_changed` (rol anterior y nuevo), `user_deactivated` y `user_reactivated`, con quién (`actor_*`), sobre quién (`target_*`) y cuándo (`occurred_at`, UTC). Las altas por CLI quedan con `actor_username = "cli"`.
- Fase 4: `login_failure` guarda siempre el nombre intentado en `target_username`, sin caracteres de control y truncado a 64 (con NUL u otros controles se guarda el nombre limpio, nunca el valor bruto). Acciones nuevas: `login_locked`, `distribution_uploaded`, `distribution_downloaded`, `fair_evaluated`, `saved_query_created` y `saved_query_deleted`. Nunca se guardan secretos, tokens ni el texto de las consultas. `audit_events.action` es texto: las acciones nuevas no necesitan migración.

## Primer admin (CLI)

```sh
uv run python -m app.cli create-admin --username <nombre>
```

Pide la contraseña de forma oculta y con confirmación. Para scripts, se puede pasar por stdin:

```sh
printf '%s\n' "$ADMIN_PASSWORD" | uv run python -m app.cli create-admin --username <nombre> --password-stdin
```

La contraseña no se acepta como argumento para que no quede en el historial de la shell ni en la lista de procesos. El resto de cuentas se crean desde la API (`POST /users`) con un token de admin.

## Migraciones

```sh
uv run alembic upgrade head                                  # aplicar
uv run alembic revision --autogenerate -m "descripción"      # nueva migración tras cambiar app/models.py
```

Alembic lee la URL de `DATABASE_URL`.

## Contrato OpenAPI

`openapi.json` es el contrato que consumen `frontend`, `qa` y `docs`. Se regenera con:

```sh
uv run python -m app.export_openapi            # escribe openapi.json
uv run python -m app.export_openapi --check    # falla si no está al día
```

Una prueba (`tests/test_openapi.py`) falla si el fichero versionado no coincide con el código. Cualquier cambio en el contrato va en una PR propia.

## Pruebas y linter

```sh
uv sync --frozen && uv run ruff check . && uv run pytest
```

Las pruebas usan **SQLite en memoria** por defecto: no necesitan servicios, son rápidas e iguales en local y en CI. Los modelos solo usan tipos portables (`Uuid`, `JSON`, `Enum` no nativo con restricción CHECK), y `tests/test_migrations.py` comprueba que las migraciones de Alembic aplican, revierten y producen exactamente el esquema de los modelos.

**Fuseki en las pruebas unitarias:** la dependencia `get_triplestore` se sustituye por `MemoryStore` (`app/triplestore.py`), un `rdflib.Dataset` en memoria con el mismo contrato que `FusekiStore` (`construct`, `get_graph`, `put_graph`): ejecuta las mismas consultas SPARQL con el motor de rdflib y guarda cada grafo con nombre por separado. Además registra las consultas recibidas, lo que permite comprobar que un slug malicioso o el texto de `q` nunca llegan a SPARQL. El cliente HTTP de Fuseki se prueba aparte con `httpx.MockTransport` (`tests/test_triplestore.py`).

**Datos de prueba:** `tests/fixtures/data/` es una copia de `semantic/data/` (datos sintéticos de G2, de `semantico`), y `tests/fixtures/semantic/` copia `semantic/vocabularios/`, `semantic/ontologias/` y `semantic/shapes/ontologias-vocabularios.ttl` (fase 3); `tests/test_contracts_fase2.py` comprueba que las copias son idénticas. `tests/fixtures/ontologia-recuentos.ttl` es una ontología propia de las pruebas, con recuentos conocidos, y `tests/fixtures/invalid-ontologias-vocabularios/` copia los ejemplos inválidos de `semantico`. Las formas SHACL no se copian: las pruebas montan un `SEMANTIC_DIR` temporal con las formas reales de `semantic/shapes/` y esos datos. Cuando `semantic/data/` llegue a `main`, la copia se puede sustituir por los ficheros originales.

**Fase 4:** `tests/fixtures/semantic/consultas/` copia las consultas de referencia de `semantic/consultas/`. `tests/fase4_data.py` define una serie propia de las pruebas con distribuciones PUBLIC, RESTRICTED, NON_PUBLIC y sin `dcat:mediaType` (los datos sintéticos de `semantic/` solo tienen RESTRICTED). F-UJI se simula con `httpx.MockTransport` y `tests/fixtures/fuji/evaluate-respuesta.json`, con el formato real de F-UJI 4.0.1: el envoltorio `FAIRResults` de su `fuji_server/yaml/openapi.yaml` y el `summary` grabado de una evaluación real que guarda su `tests/functional/test_evaluation.py` (el detalle `results` va vacío y los datos del envoltorio son de prueba). El SPARQL público se prueba con `MemoryQueryRunner` (rdflib con el grafo por defecto como unión) y el cliente de Fuseki con `httpx.MockTransport`. El trabajador FAIR no arranca en las pruebas (`FAIR_WORKER_POLL_SECONDS=0`): se llama a `fair.process_pending`.

### Pruebas contra un Fuseki real

`tests/test_fuseki_integration.py` se salta salvo que se le indique un Fuseki **desechable** (sustituye grafos):

```sh
docker run -d --rm --name fuseki-pruebas -p 127.0.0.1:<puerto>:3030 \
  -e ADMIN_PASSWORD=<contraseña-temporal> \
  -v "$PWD/../infra/fuseki/assembler.ttl:/fuseki-base/configuration/assembler.ttl:ro" \
  -v "$PWD/../infra/fuseki/shiro.ini:/shiro.ini.template:ro" \
  --entrypoint /bin/bash secoresearch/fuseki:6.2.0 \
  -c "cp /shiro.ini.template /fuseki-base/shiro.ini && exec /docker-entrypoint.sh java -cp '*:/javalibs/*' org.apache.jena.fuseki.main.cmds.FusekiServerCmd"

TEST_FUSEKI_URL=http://127.0.0.1:<puerto> TEST_FUSEKI_USER=admin \
  TEST_FUSEKI_PASSWORD=<contraseña-temporal> uv run pytest tests/test_fuseki_integration.py

docker stop fuseki-pruebas
```

Para pasar la misma batería contra un PostgreSQL de pruebas (vacío y desechable, porque las pruebas borran y crean las tablas):

```sh
TEST_DATABASE_URL=postgresql+psycopg://<usuario>@localhost:5432/<bd_de_pruebas> uv run pytest
```

## Imagen Docker

`Dockerfile` usa `python:3.15.2-slim`, instala un JRE headless fijado (`openjdk-25-jre-headless`, para Pellet) y las dependencias de `uv.lock` sin las de desarrollo, se ejecuta con un usuario sin privilegios (uid 10001), valida la configuración, aplica las migraciones y arranca uvicorn en el puerto 8000 con `--log-config app/log_config.json`: el formato de log de uvicorn de siempre, con un filtro (`app/log_filters.py`) que sustituye el valor de `token=` por `[oculto]`, para que los enlaces de descarga firmados no queden en el log de acceso (QA-G4-02). Si se le pasa un comando, lo ejecuta en lugar del arranque (útil para la CLI).

```sh
docker build -t itot-backend backend/
```

**Impacto de Java en la imagen:** el JRE y owlready2 (que trae los JAR de Pellet y HermiT) la llevan de unos 278 MB a unos 559 MB (medido en local, arm64). Es el coste de razonar dentro del backend sin otro servicio. Si Debian retira la versión fijada del JRE, el build falla y hay que actualizar `JRE_VERSION` en el `Dockerfile`.
