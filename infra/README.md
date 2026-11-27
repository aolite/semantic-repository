# Infraestructura local

Entorno de desarrollo con Docker Compose (fases 1 y 2). Requiere Docker con Compose v2. El despliegue del piloto (fase 5) está en «Despliegue del piloto», al final.

## Arranque

```bash
cp .env.example .env          # edita los valores; .env no se versiona
# JWT_SECRET está vacío en el ejemplo: el backend no arranca sin él.
# Genéralo con: openssl rand -hex 32 (mínimo 32 caracteres) y pégalo en .env
docker compose up -d --build
docker compose ps             # espera a que todos estén healthy
```

Crear el primer administrador (cuando el backend esté healthy):

```bash
docker compose exec -it backend python -m app.cli create-admin --username <nombre>
```

Para scripts, `create-admin` admite `--password-stdin`.

Cargar los datos sintéticos en Fuseki (cuando el backend esté healthy):

```bash
docker compose exec backend python -m app.cli load-semantic
```

Carga `semantic/data/vocab-minimo.ttl`, `semantic/data/catalogo.ttl`, `semantic/data/sintetico/*.ttl`, y también `semantic/ontologias/` y `semantic/vocabularios/`, validando antes con las formas de `semantic/shapes/`.

Parar el entorno: `docker compose down`. Para borrar además los datos (PostgreSQL, Fuseki y distribuciones): `docker compose down -v`.

## Servicios

| Servicio | Imagen | Puerto en el host | Notas |
|---|---|---|---|
| `frontend` | build de `./frontend` | 127.0.0.1:5173 | Servidor de desarrollo de Vite |
| `backend` | build de `./backend` | 127.0.0.1:8000 | FastAPI; `GET /health` y `GET /health/ready`; aplica las migraciones al arrancar |
| `fuseki` | `secoresearch/fuseki:6.2.0` | 127.0.0.1:3030 | Dataset TDB2 persistente `itot`, creado desde `infra/fuseki/assembler.ttl` |
| `postgres` | `postgres:17.6-alpine` | 127.0.0.1:5432 | Usuarios y auditoría |
| `fuji` | build de `./infra/fuji` sobre la imagen oficial de F-UJI 4.0.1 (por digest) | ninguno | Evaluador FAIR; solo en la red interna `fuji-net`, sin salida a internet |

Los servicios con puerto solo escuchan en localhost; `fuji` no publica ninguno. Si un puerto está ocupado en tu máquina, define en `.env` (opcionales) la variable correspondiente:

| Variable | Servicio | Por defecto |
|---|---|---|
| `POSTGRES_HOST_PORT` | postgres | 5432 |
| `FUSEKI_HOST_PORT` | fuseki | 3030 |
| `BACKEND_HOST_PORT` | backend | 8000 |
| `FRONTEND_HOST_PORT` | frontend | 5173 |

Si cambias `BACKEND_HOST_PORT`, ajusta también `VITE_API_BASE_URL` (por ejemplo `http://localhost:8001`): es la URL que usa el navegador, no la red interna de Compose. Si cambias `FRONTEND_HOST_PORT`, ajusta `CORS_ORIGINS`.

La imagen del backend lleva un JRE (`openjdk-25-jre-headless`) para el razonador Pellet, por lo que pasa de unos 278 MB a 559 MB.

## Variables del backend añadidas en la fase 2

| Variable | Valor en `.env.example` | Descripción |
|---|---|---|
| `FUSEKI_USER` | `backend` (hasta la fase 3 era `admin`) | Usuario con el que el backend escribe en Fuseki |
| `FUSEKI_PASSWORD` | (no se define en `.env`) | Contraseña de escritura en Fuseki. `docker-compose.yml` la toma de `FUSEKI_BACKEND_PASSWORD` (hasta la fase 3, de `FUSEKI_ADMIN_PASSWORD`) |
| `SEMANTIC_DIR` | `/semantic` | Carpeta con formas SHACL y datos de ejemplo. Compose monta `./semantic` en `/semantic` en solo lectura y fija este valor |
| `REASONER_TIMEOUT_SECONDS` | `120` (comentada, opcional) | Tiempo máximo del razonador Pellet. Llega al backend por `env_file`; no hace falta tocar el Compose |
| `REASONER_JAVA_MEMORY_MB` | `1024` (comentada, opcional) | Memoria de la JVM del razonador, en MB |
| `INGEST_MAX_TRIPLES` | `100000` (comentada, opcional) | Tripletas máximas por ingesta |
| `SHACL_TIMEOUT_SECONDS` | `60` (comentada, opcional) | Tiempo máximo de la validación SHACL, que se ejecuta en un proceso hijo |
| `SHACL_MEMORY_MB` | `2048` (comentada, opcional) | Memoria máxima del proceso de validación SHACL (`RLIMIT_AS`, solo en Linux) |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | URL pública del frontend; el backend redirige con 303 a la ficha del dataset. Ajústala si cambias `FRONTEND_HOST_PORT` |

Si una ingesta supera estos límites, la API responde 422 con `kind=limit`. Detalle en el README del backend.

`FUSEKI_PASSWORD`, `FUSEKI_USER` y `SEMANTIC_DIR` se declaran en `environment` del servicio `backend`, que tiene prioridad sobre `env_file`. Fuera de Compose (por ejemplo, el backend en local con `uv`), define `FUSEKI_PASSWORD` a mano.

El servicio `frontend` tiene healthcheck (Vite responde en el 5173), así que `docker compose up --wait` espera también al frontend.

## Volúmenes

- `postgres-data`: base de datos.
- `fuseki-data`: triplestore (`/fuseki-base/databases`).
- `distributions`: distribuciones de datasets, montado en el backend en `/data/distributions`.

## Fuseki

Endpoints del dataset `itot`:

- Anónimos (solo lectura): `http://localhost:3030/itot/sparql` y `/itot/query`.
- Con autenticación Basic como `backend` (contraseña `FUSEKI_BACKEND_PASSWORD`, rol `writer`): `/itot/update`, `/itot/data` (también GET) y `/itot/shacl`. Es el usuario que usa la API. No puede usar la administración de Fuseki (`/$/...` y el resto de rutas dan 403).
- Con autenticación Basic como `admin` (contraseña `FUSEKI_ADMIN_PASSWORD`, roles `admin` y `writer`): lo anterior más `/$/...` y el resto de rutas. Es solo para administrar Fuseki.
- Sin credenciales, o con una contraseña incorrecta, las rutas de escritura devuelven 401.

Así solo el backend escribe en el triplestore. La política está en `infra/fuseki/shiro.ini` (plantilla) y en `fuseki:allowedUsers` de `infra/fuseki/assembler.ttl`. `infra/fuseki/entrypoint.sh` genera el `shiro.ini` real al arrancar con las dos contraseñas de las variables de entorno, que no pueden llevar `,` `=` `\` `#` ni `;` (formato de Shiro): si las llevan, Fuseki no arranca. Shiro no comprueba el nombre en `user[...]` (acepta a cualquier usuario autenticado), por eso la plantilla usa `roles[...]`.

### Migrar un entorno ya levantado (decisión 32)

Un entorno anterior a la fase 4 tiene `FUSEKI_USER=admin` y no tiene `FUSEKI_BACKEND_PASSWORD`. Sin tocar los volúmenes (no hace falta recargar datos):

1. Añade a tu `.env` las variables nuevas de `.env.example` (ver la tabla de abajo): como mínimo `FUSEKI_BACKEND_PASSWORD`, con un valor propio y sin los caracteres prohibidos de arriba, `FUJI_USERNAME` y `FUJI_PASSWORD`.
2. Cambia `FUSEKI_USER=admin` por `FUSEKI_USER=backend`. Si lo dejas en `admin`, el backend sigue escribiendo, pero con la contraseña de `FUSEKI_BACKEND_PASSWORD`, que no es la de admin: fallaría con 401. Mejor cambiarlo.
3. Reconstruye y recrea: `docker compose up -d --build`. Recrea `fuseki` (el `shiro.ini` se regenera en cada arranque; los datos están en el volumen `fuseki-data` y no se tocan), `backend` y construye `fuji`.
4. Comprueba: `curl -s -o /dev/null -w '%{http_code}' -u backend:<contraseña> -X POST http://127.0.0.1:3030/itot/update --data-urlencode 'update=INSERT DATA {}'` (no escribe nada) no debe dar 401 ni 403, y la misma petición sin `-u` debe dar 401.

Si `docker compose` se queja de una variable obligatoria sin definir (`FUSEKI_BACKEND_PASSWORD`, `FUJI_USERNAME`, `FUJI_PASSWORD`), falta en tu `.env`.

## F-UJI

Evaluador FAIR (servicio interno). Lo usa el backend; no se publica ningún puerto.

- **Imagen:** la oficial del proyecto, `ghcr.io/pangaea-data-publisher/fuji`, tag `4.0.1` (publicada el 24 de septiembre de 2026), fijada por digest `sha256:2108f2e2f52fed4cc0f58f22d47644c5d015c5c66f3886e2440e216c533e6a9a`. Solo se publica para `linux/amd64`: en arm64 (Apple Silicon) corre emulada, y por eso el servicio declara `platform: linux/amd64`.
- **Por qué se construye:** la imagen oficial 4.0.1 (y `latest`) no arranca. F-UJI 4 inicia Chromium con Playwright al arrancar y la imagen no lo incluye (`Executable doesn't exist ... chrome-headless-shell`). `infra/fuji/Dockerfile` parte del digest y solo instala ese navegador (`playwright install chromium-headless-shell`, unos 90 s en amd64). Al construir se descarga el navegador del CDN de Playwright; en ejecución no se descarga nada. Al subir de versión, cambia el digest y comprueba si la imagen oficial ya lo arregla.
- **API:** puerto `1071`, base `/fuji/api/v1` (`FUJI_URL=http://fuji:1071/fuji/api/v1`). `POST /evaluate` evalúa; la interfaz Swagger está en `/fuji/api/v1/ui/` (la usa el healthcheck, sin credenciales). Con credenciales falsas, `/evaluate` da 401.
- **Autenticación:** HTTP Basic. La imagen trae un usuario de ejemplo público en `fuji_server/config/users.py`; `infra/fuji/users.py` lo sustituye (montado en solo lectura) por `FUJI_USERNAME` y `FUJI_PASSWORD`. Sin esas variables F-UJI no arranca, para no dejar nunca las credenciales por defecto.
- **Healthcheck:** Python (la imagen no trae `curl` ni `wget`) sobre la interfaz Swagger; `start_period` de 60 s.
- **El backend no depende de que F-UJI esté sano:** `depends_on` con `condition: service_healthy` y `required: false`. Si F-UJI no llega a estar sano, Compose avisa y arranca el backend igual (comprobado con un F-UJI roto). El backend debe tratar la falta de F-UJI como evaluación `failed` o `pending`.
- **Red:** `fuji` solo está en la red `fuji-net`, declarada `internal: true` (sin salida a internet), compartida con el backend. F-UJI alcanza al backend (`http://backend:8000/`) pero no puede salir. Con `FAIR_TARGET_BASE_URL` apuntando al backend por la red interna, una evaluación local funciona sin llamadas externas (comprobado: una evaluación de una versión de dataset tarda 1 s).
- Evaluar con `metric_version: metrics_v0.5`, el que trae por defecto; hay más en `fuji_server/yaml/`.

### Llamadas salientes de F-UJI (para validar la residencia de datos en la UE)

Solo documentación: la decisión de qué se permite es del responsable. Estado actual: ninguna es posible, porque `fuji-net` no tiene salida; los fallos de red se registran en el log de F-UJI y no impiden la evaluación. Si se quita `internal: true` de `fuji-net` (por ejemplo, para evaluar URLs públicas en el despliegue), F-UJI puede llamar a lo siguiente. Resultado de leer el código de la 4.0.1:

| Servicio | Cuándo | Qué envía | Se puede desactivar |
|---|---|---|---|
| La URL evaluada y las que descubre en ella (enlaces de signposting, vocabularios, distribuciones, `owl:imports`, contextos JSON-LD, endpoint SPARQL/OAI-PMH/CSW) | Siempre, es la evaluación | La petición HTTP normal a esas URLs; no es un servicio de terceros salvo que el dato lo esté | No: es lo que evalúa |
| `api.datacite.org` (DataCite) | Si el identificador es un DOI y `use_datacite` es `true` (por defecto) | El DOI | Sí, enviando `use_datacite: false` en la petición (el backend debería hacerlo: nuestros identificadores no son DOI) |
| `doi.org/ra/{prefijo}` | Solo con DOI de un prefijo no incluido en su lista local | El prefijo del DOI | No hay opción; no aplica a URI no DOI |
| `api.datasearch.elsevier.com` (Mendeley Data) | Si el identificador no está en DataCite: **para cualquier identificador**, también URIs que no son DOI | El identificador y la URL de la página | No hay opción en la configuración ni en la petición. Solo bloqueando la red |
| Búsqueda de Google (`google.com/search`, `customsearch.googleapis.com`) | Solo si existe la base `google_cache.db` (no viene en la imagen) o se configuran `google_custom_search_id` y `google_custom_search_api_key` (vacíos por defecto) | La URL | Sí, no configurándolo (estado por defecto): no hay llamada |
| `re3data.org/api/beta` | Solo si el identificador es un DOI de un repositorio registrado en re3data (consulta de DataCite) | El identificador del repositorio | No hay opción; no aplica a URI no DOI |
| `publicsuffix.org` y `raw.githubusercontent.com/publicsuffix/list` (GitHub) | La primera vez que se procesa una URL (biblioteca `tldextract`) | Ninguno de nuestros datos: descarga la lista de sufijos públicos | No por configuración; si falla, usa la copia incluida en la biblioteca (comprobado: la evaluación funciona sin salida) |
| `api.datacite.org/repositories` | Al arrancar, si su lista local de repositorios tiene más de 24 h | Ninguno de nuestros datos | Sí: el servicio hace `touch` del fichero antes de arrancar, así que usa la lista incluida y no llama |
| `raw.github.com/spdx/license-list-data` (GitHub) | Al arrancar, solo si `debug_mode = false` | Ninguno de nuestros datos | Sí: la imagen trae `debug_mode = true` y usa la lista SPDX incluida |
| `raw.githubusercontent.com/jshttp/mime-db` | Código presente pero desactivado en 4.0.1 | Nada | No se ejecuta |
| LOV y LOD Cloud (`lov_api`, `lod_cloudnet` en `server.ini`) | Definidos en la configuración pero la 4.0.1 no los lee | Nada | No se usan |
| `f-uji.net` | Solo son identificadores de espacios de nombres en el informe | No es una llamada | No aplica |

En resumen: lo que sale de verdad en una evaluación de una URI propia, si hay salida a internet, son las peticiones a la URL evaluada y, sobre todo, las consultas a Mendeley Data (Elsevier) con el identificador y la URL de la página, que no se pueden desactivar por configuración. Por eso `fuji-net` es `internal`. Si el despliegue necesita que F-UJI evalúe URLs públicas, hay que decidir si se acepta esa consulta, o se mantiene la red cerrada y se evalúa por la red interna. No se ha verificado en qué región alojan sus servidores Mendeley/Elsevier, DataCite ni Google: es lo que debe validar el responsable.

## Variables nuevas de la fase 4

Todas están en `.env.example` con valores ficticios o por defecto. Llegan al backend por `env_file`, salvo `FUSEKI_USER` y `FUSEKI_PASSWORD`, que `docker-compose.yml` fija en su `environment`.

| Variable | Defecto | Uso |
|---|---|---|
| `FUSEKI_BACKEND_PASSWORD` | ficticio | Contraseña del usuario `backend` de Fuseki. Obligatoria |
| `FUJI_URL` | `http://fuji:1071/fuji/api/v1` | Backend a F-UJI |
| `FUJI_USERNAME`, `FUJI_PASSWORD` | `fuji-backend`, ficticia | Autenticación Basic de la API de F-UJI. Obligatorias |
| `FUJI_TIMEOUT_SECONDS` | `300` | Tiempo máximo de una evaluación |
| `FAIR_TARGET_BASE_URL` | `http://backend:8000/` | URL base que se pasa a F-UJI en lugar de `BASE_URI`. El Compose la fija a `http://backend:8000/` si `.env` no la define; vacía usa `BASE_URI`, que F-UJI no alcanza sin salida a internet |
| `SPARQL_TIMEOUT_SECONDS` | `10` | SPARQL público |
| `SPARQL_MAX_ROWS` | `10000` | SPARQL público |
| `SPARQL_RATE_ANON_PER_MIN` | `30` | Por IP |
| `SPARQL_RATE_AUTH_PER_MIN` | `60` | Por usuario |
| `LOGIN_MAX_FAILURES` | `5` | Bloqueo de login |
| `LOGIN_WINDOW_MINUTES` | `15` | Ventana de recuento de fallos |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Duración del bloqueo |
| `DOWNLOAD_LINK_TTL_SECONDS` | `60` | Validez del enlace firmado de descarga |
| `MAX_UPLOAD_MB` | `512` | Tamaño máximo de un fichero de distribución |
| `SAVED_QUERIES_MAX_PER_USER` | `50` | Consultas SPARQL guardadas por usuario |

`FUJI_USERNAME`, `FUJI_PASSWORD` y `FUSEKI_BACKEND_PASSWORD` no tienen valor por defecto en el Compose: si faltan en `.env`, `docker compose` se detiene con un mensaje claro.

## CI

`.github/workflows/ci.yml` se ejecuta en cada PR y en cada push a `main`. Los jobs `backend`, `frontend` y `semantic` se saltan si la carpeta de su capa aún no existe. El job `compose` valida `docker compose config` con un `.env` copiado de `.env.example`. Las acciones están fijadas por SHA de commit.

El job `e2e` (propuesta pendiente de decisión del responsable) ejecuta `uv run --project backend pytest tests/e2e -v` con `E2E_REQUIRE_DOCKER=1`: levanta el Compose real con puertos y secretos aleatorios (ver `tests/e2e/README.md`). Tiene un límite de 30 minutos porque construye las imágenes del backend, del frontend y de F-UJI; desde la fase 4 el Compose incluye F-UJI y la e2e lo levanta con el resto.

El job `browser` (decisión 34) ejecuta las pruebas de pantallas con Playwright y Chromium:

1. Se salta, y pasa en verde, mientras no exista `tests/browser/package.json`. Se eligió esto en lugar de dejarlo desactivado a mano para que se active solo al integrar las pruebas de `qa`, sin otra PR de CI.
2. Si existe: genera un `.env` desde `.env.example` con secretos aleatorios, levanta el Compose (con F-UJI) con `docker compose up -d --build --wait`, carga los datos con `load-semantic`, instala las dependencias de `tests/browser/` con `npm ci` y Chromium con `npx playwright install --with-deps chromium`, y ejecuta `npx playwright test` desde esa carpeta.
3. Contrato con `qa`: `tests/browser/` es un proyecto npm con `package.json`, `package-lock.json` y `playwright.config.*`. Las pruebas reciben `BASE_URL` (`http://localhost:5173`) y `API_URL` (`http://localhost:8000`), y `CI=true`. Cualquier cuenta de prueba la crean ellas (por ejemplo, con `docker compose exec backend python -m app.cli create-admin`). El informe HTML debe quedar en `tests/browser/playwright-report/` y las trazas en `tests/browser/test-results/`.
4. Sube ese informe y las trazas como artefacto (7 días) solo si falla, y siempre apaga el Compose con `docker compose down -v`.
5. Permisos mínimos (`contents: read` para todo el workflow) y acciones fijadas por commit.

## Publicar una versión de ontología o vocabulario (fase 3)

«Publicar» significa crear una **Release de GitHub**. Se hace empujando una etiqueta de Git sobre un commit que ya esté en `main`; la etiqueta la crea y empuja quien tiene permiso para ello, tras fusionar la PR con el RDF.

| Qué | Etiqueta | Fichero que debe existir |
|---|---|---|
| Ontología | `onto/{slug}/v{version}` | `semantic/ontologias/{slug}/{version}.ttl` |
| Vocabulario SKOS | `vocab/{slug}/v{version}` | `semantic/vocabularios/{slug}.ttl` |
| Vocabulario corporativo | `vocab/corp/{slug}/v{version}` | `semantic/vocabularios/corp/{slug}.ttl` |

`{slug}` sigue `semantic/uris.md`. La versión de una ontología es semver de 3 números (`1.2.0`). La de un esquema SKOS lleva 2 o 3 números (`1.0`, `2026.1`). La `v` solo va en la etiqueta, no en el fichero ni en el RDF.

```bash
git switch main && git pull
git tag onto/itot/v1.2.0
git push origin onto/itot/v1.2.0
```

Si una etiqueta sale mal y la Release aún no existe, bórrala con `git push --delete origin <etiqueta>` y `git tag -d <etiqueta>`. Si la Release ya se creó, bórrala también desde GitHub.

### Qué hace `.github/workflows/publicar.yml`

1. Comprueba que el commit de la etiqueta está en `main`.
2. Valida con `uv run semantic/scripts/validate.py` (todo `semantic/`).
3. `infra/scripts/publicar.py` deduce tipo, slug y versión de la etiqueta; falla si no existe el fichero o si la versión no coincide con la del RDF:
   - ontologías: `owl:versionInfo` y/o `owl:versionIRI` (que debe terminar en `/{version}`); debe haber al menos uno y un único `owl:Ontology`;
   - SKOS: la propiedad indicada por la variable `SKOS_VERSION_PREDICATE` en cada `skos:ConceptScheme` (por defecto `owl:versionInfo`; `none` desactiva la comprobación). `semantico` lo fijó así: `owl:versionInfo` en el `skos:ConceptScheme`.
4. Los `.ttl` usan IRIs relativas sin `@base`. El script los lee con rdflib y `publicID=BASE_URI`, de modo que las IRIs relativas quedan expandidas, y serializa los artefactos ya expandidos. `BASE_URI` es la variable de repositorio del mismo nombre; si no existe, vale `https://semantic.example.org/itot/` (hasta que se fije el dominio real en la fase 5).
5. Documentación:
   - ontologías: **WIDOCO 1.4.26** (JAR oficial con dependencias, JDK 17, fijado por versión y SHA-256) sobre el RDF/XML expandido, con idioma `WIDOCO_LANG` (por defecto `es`; con varios idiomas la 1.4.26 falla en LODE) y vista WebVOWL. WIDOCO resuelve los `owl:imports` por red al cargar la ontología y no tiene opción para desactivarlo; si una ontología importa otras, hay que valorar vendorizarlas.
   - SKOS: una página HTML sencilla (`index.html`) con una tabla de conceptos (etiqueta, IRI, concepto más general, definición), generada con rdflib. Sustituible por algo más elaborado más adelante.
6. Crea la Release (job con `contents: write`, el resto con `contents: read`) con estos ficheros, donde `{nombre}` es la etiqueta sin la `v` y con `/` cambiado por `-` (por ejemplo `onto-itot-1.2.0`):
   - `{nombre}.ttl` y `{nombre}.jsonld` (todos) y `{nombre}.rdf` (solo ontologías);
   - `{nombre}-docs.zip`, con la documentación (`index.html` en la raíz).

Variables de repositorio opcionales (Settings > Secrets and variables > Actions > Variables): `BASE_URI`, `SKOS_VERSION_PREDICATE`, `WIDOCO_LANG`. No hay más secretos que el `GITHUB_TOKEN` automático.

### Probar el script en local

```bash
uv run infra/scripts/publicar.py --tag onto/itot/v1.2.0 --out /tmp/salida
```

### Cargar la Release en un entorno

El despliegue automático llega en la fase 5. Mientras, la carga se hace con `load-semantic` desde un checkout de la etiqueta (no descarga la Release):

```bash
git switch --detach onto/itot/v1.2.0     # el árbol de esa versión
docker compose exec backend python -m app.cli load-semantic
```

`load-semantic` carga también `semantic/ontologias/` y `semantic/vocabularios/`; este flujo no lo modifica.

## Despliegue del piloto

Fase 5. El **mismo Docker Compose** del entorno local, con `docker-compose.prod.yml` encima. Esta sección es un resumen operativo; la guía de operación completa está en [`docs/operacion-piloto.md`](../docs/operacion-piloto.md). Todo lo que ves aquí está probado en local con hosts ficticios; no se ha desplegado en ningún servidor. Los valores (`example.org`) son ficticios: los hosts y el email reales van solo en el `.env` del servidor, que no se versiona.

### Qué cambia respecto al local

| Tema | Local (`docker-compose.yml`) | Piloto (`+ docker-compose.prod.yml`) |
|---|---|---|
| Puertos en el host | 5173, 8000, 3030 y 5432 en `127.0.0.1` | Solo **80 y 443** del proxy (`!reset` quita el resto). Fuseki y PostgreSQL no se exponen nunca; el SPARQL público va por el backend |
| Proxy | no hay | `caddy` (2.11.9) con HTTPS automático de Let's Encrypt |
| Frontend | servidor de desarrollo de Vite | build estático de Vite servido por un Caddy ligero (`infra/frontend/`), sin privilegios y de solo lectura |
| F-UJI | red `fuji-net` interna (sin internet), evalúa el backend | `fuji-net` con salida a internet; `FAIR_TARGET_BASE_URL` vacío: evalúa la `BASE_URI` pública (decisión 47) |
| URLs | `.env` | `BASE_URI`, `FRONTEND_BASE_URL`, `CORS_ORIGINS` y `VITE_*` se derivan de `FRONTEND_HOST` y `API_HOST` |
| Memoria y logs | sin límites | límites por contenedor, heap de JVM fijado, logs `json-file` de 10 MB x 5 ficheros |

Requiere **Docker Compose 2.24.4 o superior** (etiquetas `!reset` y `!override`).

**Hosts.** Frontend y API van en dos hosts (`FRONTEND_HOST`, `API_HOST`) porque comparten rutas (`/datasets/{slug}`). `BASE_URI` es `https://{API_HOST}/semanticrepository/`: las URIs persistentes las resuelve el backend.

**Cómo se resuelve `/semanticrepository/`.** El backend no monta ese prefijo: sirve en la raíz (`/dataset/...`, `/catalogo/...`, `/onto/...`, `/vocab/...`, `/sparql`, `/auth`, `/docs`...). El proxy lo quita en el host de la API (`handle_path /semanticrepository/*`), así que `https://{API_HOST}/semanticrepository/dataset/x` llega al backend como `/dataset/x`. La API sigue accesible sin prefijo en la raíz del mismo host. No hace falta tocar el backend. El 303 de las URIs persistentes va a `https://{FRONTEND_HOST}/datasets/...` (`FRONTEND_BASE_URL`).

**Cabeceras.** HSTS, `X-Content-Type-Options`, `Referrer-Policy` y `Permissions-Policy` en los dos hosts. CSP: en el frontend, `default-src 'self'` más `connect-src` hacia el host de la API y `style-src 'unsafe-inline'` (React usa estilos en línea); en la API, `default-src 'none'`, salvo en `/docs` y `/redoc` (decisión 24), que permiten solo `cdn.jsdelivr.net` y scripts en línea. No se permiten Google Fonts ni el favicon de `fastapi.tiangolo.com` que piden ReDoc y Swagger (se ven con fuentes del sistema). El token de las URL de descarga firmadas se oculta en el registro de acceso del proxy.

**Tamaño de petición.** `PROXY_MAX_BODY_RDF` (11 MiB; `INGEST_MAX_BYTES` es 10 MiB por defecto) para RDF, JSON y SPARQL, y `PROXY_MAX_BODY_UPLOAD` (520 MiB; `MAX_UPLOAD_MB` es 512) solo para la subida de ficheros de distribución. Si cambias esos límites del backend, cambia también estas variables.

**Memoria** (máximos por contenedor, para 8 GB; suman unos 6,4 GB y dejan el resto al sistema y a la caché de disco):

| Servicio | Límite | Notas |
|---|---|---|
| `fuseki` | 2 GB | `JAVA_TOOL_OPTIONS=-Xms256m -Xmx1g` |
| `backend` | 2,5 GB | Pellet con `REASONER_JAVA_MEMORY_MB=1024`; la validación SHACL conserva su `SHACL_MEMORY_MB` |
| `fuji` | 1,25 GB | Chromium; en reposo ronda 450 MB |
| `postgres` | 512 MB | |
| `caddy` / `frontend` | 128 MB / 64 MB | |

Son cifras de partida, sin carga real: ajústalas en el piloto con `docker stats`. Un contenedor que supera su límite se reinicia (`restart: unless-stopped`).

**IP del cliente.** Detrás del proxy, el backend recibe la IP real en `X-Forwarded-For`. Caddy, el backend y el frontend comparten la red `proxy-net` (subred fija `10.254.77.0/24`, fuera de los rangos habituales de Docker; si choca con una red del servidor, cámbiala en `docker-compose.prod.yml`), y Caddy está solo en ella con la IP fija `10.254.77.2`. El backend lleva `FORWARDED_ALLOW_IPS=10.254.77.2` (nunca `*`): uvicorn solo acepta la cabecera de esa IP, de modo que ningún otro contenedor (F-UJI, que tiene salida a internet, ni los demás) puede elegir su IP. Caddy sustituye el `X-Forwarded-For` del cliente (no se configura `trusted_proxies`). Así el límite de SPARQL anónimo y el bloqueo de login son por cliente y no del proxy entero. Comprobado en local: con el proxy el backend ve la IP del cliente aunque este mande un `X-Forwarded-For` falso, y una petición directa a `backend:8000` desde F-UJI con la cabecera falsificada se registra con la IP de F-UJI.

### Requisitos del VPS

Linux (Debian o Ubuntu LTS reciente), 4 vCPU, 8 GB de RAM y 240 GB de NVMe (los volúmenes de Docker y las copias van en ese disco; las copias en la misma máquina no protegen de perder el VPS: copia también fuera de él). Una IP pública, dos nombres DNS (`FRONTEND_HOST` y `API_HOST`) que apunten a ella (registros A, y AAAA si hay IPv6) **antes** del primer arranque, y los puertos 80 y 443 libres. Salida a internet (Let's Encrypt, F-UJI y la construcción de las imágenes); los usuarios cargan `cdn.jsdelivr.net` en `/docs` y `/redoc`.

### Preparar el servidor

1. Actualiza el sistema. Instala Docker Engine y el plugin Compose desde el repositorio oficial de Docker (comprueba `docker compose version` >= 2.24.4).
2. Crea un usuario sin root (por ejemplo `itot`), añádelo al grupo `docker` y entra por SSH con clave; desactiva el acceso SSH de root y por contraseña.
3. Cortafuegos con solo 22, 80 y 443 (con `ufw`: `ufw default deny incoming`, `ufw allow 22/tcp`, `ufw allow 80/tcp`, `ufw allow 443`, `ufw enable`). Ojo: Docker publica sus puertos saltándose `ufw`; por eso el Compose solo publica 80 y 443 y no hay nada más que proteger. Comprueba desde otra máquina que el resto de puertos no responden.
4. Clona el repositorio en el servidor (por ejemplo en `/srv/semantic-repository`).

### Variables

`cp .env.example .env` y cambia, como mínimo:

- los secretos: `JWT_SECRET` (`openssl rand -hex 32`), `POSTGRES_PASSWORD` (y la misma en `DATABASE_URL`), `FUSEKI_ADMIN_PASSWORD`, `FUSEKI_BACKEND_PASSWORD`, `FUJI_PASSWORD`;
- `FRONTEND_HOST` y `API_HOST` (solo el nombre, sin `https://`);
- `CADDY_TLS`: el **email de contacto de Let's Encrypt**. El valor del ejemplo, `internal`, es el certificado de la CA interna de Caddy y solo vale para pruebas: los navegadores lo rechazan;
- opcionales: `PROXY_*`, `BACKUP_DIR`, `BACKUP_RETENTION_DAYS` (ver `.env.example`).

`chmod 600 .env`. Las demás variables (`BASE_URI`, `FRONTEND_BASE_URL`, `CORS_ORIGINS`, `VITE_*`) las sustituye `docker-compose.prod.yml`. `FRONTEND_HOST` y `API_HOST` se incrustan en el build del frontend: si cambian, hay que reconstruir (`up -d --build`).

Atajo para no repetir los ficheros en cada comando:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
export APP_COMMIT=$(git rev-parse --short HEAD)   # opcional: commit desplegado
```

### Primer arranque

```bash
docker compose config -q                         # valida; falla si falta una variable obligatoria
docker compose up -d --build --wait --wait-timeout 900
docker compose ps                                # todos healthy
docker compose exec -T backend python -m app.cli load-semantic
docker compose exec -it backend python -m app.cli create-admin --username <nombre>
```

La primera vez, Caddy pide los certificados a Let's Encrypt (tarda unos segundos; los DNS tienen que apuntar ya al servidor). `load-semantic` carga los datos sintéticos, ontologías y vocabularios (el piloto es solo con datos sintéticos). Los certificados se guardan en el volumen `caddy-data`: no lo borres, porque Let's Encrypt limita las emisiones por dominio. Let's Encrypt solo emite certificados y no recibe datos del repositorio.

Comprobaciones: `https://{FRONTEND_HOST}` carga; `https://{API_HOST}/health/ready` da `ok`; `curl -i https://{API_HOST}/semanticrepository/dataset/<slug>` da 303 al frontend y con `-H 'Accept: text/turtle'` da el RDF; `https://{API_HOST}/docs` se ve; el login funciona. La prueba de humo de `tests/smoke` automatiza buena parte (ver su README; con `SMOKE_API_URL=https://{API_HOST}` sin prefijo y `SMOKE_BASE_URI=https://{API_HOST}/semanticrepository/`).

### Actualizar

```bash
git pull                                         # o: git switch --detach <etiqueta>
export APP_COMMIT=$(git rev-parse --short HEAD)
infra/scripts/backup.sh                          # copia antes de actualizar
docker compose up -d --build --wait --wait-timeout 900
```

Las migraciones de la base de datos las aplica el backend al arrancar. Si la actualización cambia datos semánticos, vuelve a lanzar `load-semantic`.

### Copias de seguridad y restauración

`infra/scripts/backup.sh` guarda en `BACKUP_DIR/<fecha UTC>/` un `pg_dump` de PostgreSQL, un volcado N-Quads de todos los grafos de Fuseki (por su API de administración, con el usuario admin, dentro del contenedor: Fuseki no tiene puertos) y un tar del volumen de distribuciones, con `SHA256SUMS`. Puede lanzarse las veces que haga falta (cada ejecución crea su carpeta; si falla no deja una copia a medias y sale con error), usa un bloqueo para no solaparse y borra las copias de más de `BACKUP_RETENTION_DAYS` días (14 por defecto), conservando siempre la más reciente. De `.env` solo lee `BACKUP_DIR` y `BACKUP_RETENTION_DAYS` (sin hacer `source` del fichero; una variable del entorno tiene prioridad) y no guarda secretos: las credenciales las toma del entorno de los contenedores. **No copia el volumen `caddy-data`** (certificados y clave de cuenta ACME): Caddy los vuelve a emitir solo la primera vez que arranca en un servidor nuevo. Let's Encrypt limita las emisiones por dominio, así que no repitas arranques desde cero sin necesidad; para las pruebas usa `CADDY_TLS=internal`.

Cron diario (`crontab -e` del usuario `itot`):

```
30 3 * * * cd /srv/semantic-repository && infra/scripts/backup.sh >> $HOME/itot-backup.log 2>&1
```

Restaurar (**destructivo**: sustituye los datos actuales) desde una carpeta de copia:

```bash
infra/scripts/restore.sh --yes ~/itot-backups/2026-01-01T033000Z
```

Comprueba las sumas, para el backend y el proxy, restaura PostgreSQL (`pg_restore --clean`), vacía Fuseki y carga el N-Quads, vacía y restaura las distribuciones, y arranca de nuevo los servicios. Probado en local: copia, borrado de los tres almacenes y restauración, con los mismos recuentos de cuádruples, usuarios y ficheros y el login funcionando. **Restaurar en un servidor nuevo.** Prepara el servidor como en «Preparar el servidor», copia el `.env` (por tu canal seguro; no está en las copias) y la carpeta de la copia (`scp -r`), levanta la pila vacía con el «Primer arranque» **sin** `load-semantic` ni `create-admin`, y ejecuta `restore.sh --yes <carpeta>` sobre ella. Los usuarios, los datos y las distribuciones vuelven con la copia. Los DNS tienen que apuntar ya al servidor nuevo (Caddy emite certificados nuevos). Probado en local: pila borrada con sus volúmenes, levantada vacía y restaurada desde una carpeta copiada (895 cuádruples, 1 usuario, 9 ficheros, login y RDF correctos). Usa el mismo `JWT_SECRET` que el servidor viejo si quieres que las sesiones abiertas sigan valiendo.

**Marcha atrás de una actualización.** Antes de actualizar, `backup.sh` (ya forma parte de «Actualizar»). Si la versión nueva falla:

```bash
git switch --detach <etiqueta-o-commit-anterior>
export APP_COMMIT=$(git rev-parse --short HEAD)
docker compose up -d --build --wait --wait-timeout 900
```

Esto vuelve al código anterior conservando los datos, y vale si la actualización no cambió el esquema de la base de datos. Las migraciones de Alembic solo avanzan: si la versión nueva aplicó una migración, el código viejo no funcionará con ese esquema, y entonces hay que volver a la versión anterior **y** restaurar la copia previa a la actualización con `restore.sh` (se pierden los cambios hechos desde esa copia). Probado en local: cambio a un commit anterior y vuelta con la pila funcionando y los datos intactos; la restauración, como arriba. No se ha probado una migración real hacia atrás.

Las copias están en el mismo disco que los datos: sincronízalas a otro sitio dentro de la UE (decisión pendiente del responsable).

### Probar el despliegue en local

Con hosts ficticios y el certificado interno de Caddy (`CADDY_TLS=internal`), sin tocar la pila de desarrollo (`-p itot-prod`):

```bash
# .env con FRONTEND_HOST=repositorio.localhost, API_HOST=api.localhost y CADDY_TLS=internal.
# Los dominios *.localhost resuelven a 127.0.0.1 en la mayoría de sistemas; si no, añade
# "127.0.0.1 repositorio.localhost api.localhost" a /etc/hosts.
docker compose -p itot-prod -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
docker compose -p itot-prod -f docker-compose.yml -f docker-compose.prod.yml cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
curl --cacert ./caddy-root.crt https://api.localhost/health/ready
```

Usa los puertos 80 y 443 del equipo (o `PROXY_HTTP_PORT` y `PROXY_HTTPS_PORT`; con puertos distintos de 80 y 443 la redirección de HTTP a HTTPS pierde el puerto). Con 4 GB para Docker no caben a la vez las pilas `itot` e `itot-prod`: para una con `docker compose -p itot stop`. F-UJI no confía en la CA interna, así que las evaluaciones FAIR no funcionan con `tls internal`.

### CI del despliegue

El job `compose-prod` valida `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`, comprueba que solo el proxy publica puertos (80 y 443) y ejecuta `caddy validate` sobre los dos Caddyfile. El job `smoke-prod` (propuesta de `qa`, pendiente de decisión) levanta la pila de producción con `tls internal` en el runner y le pasa `tests/smoke`; se salta mientras no exista esa carpeta.
