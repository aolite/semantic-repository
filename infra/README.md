# Infraestructura local

Entorno de desarrollo con Docker Compose (fases 1 y 2). Requiere Docker con Compose v2.

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
| `FAIR_TARGET_BASE_URL` | `http://backend:8000/` | URL base que se pasa a F-UJI en lugar de `BASE_URI`. Vacío usa `BASE_URI` |
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

### Excepción de Trivy

El job `imagen-backend` analiza la imagen del backend con Trivy (v0.76.2) y falla con cualquier hallazgo crítico. Ignora una sola vulnerabilidad, declarada en `.trivyignore.yaml` y pasada con `trivyignores`: **CVE-2026-114820** (crítica, en `openjdk-25-jre-headless`, distrust de CA intermedias de eMudhra). No tiene corrección en Debian 13. La JRE solo existe para que owlready2 ejecute Pellet, que corre sin red (lo comprueban las pruebas de `backend/tests/test_security_g3.py`), así que el impacto es prácticamente nulo. Decisión del responsable: mantener Pellet y añadir la excepción.

La excepción caduca el **2027-02-15** (`expired_at`, propuesta de tres meses). Pasada esa fecha Trivy deja de ignorarla y el job vuelve a fallar. Al revisarla:

1. Comprueba si Debian ya corrige la CVE (reconstruye la imagen y ejecuta el job sin la excepción). Si está corregida, borra la entrada.
2. Si sigue sin corrección y la JRE sigue sin red, decide con el responsable ampliar `expired_at` o cambiar de solución.
3. Cualquier otra CVE crítica sigue haciendo fallar el job: no se añade al fichero sin decisión del responsable.

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
