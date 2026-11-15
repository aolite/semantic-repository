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

Carga `semantic/data/vocab-minimo.ttl`, `semantic/data/catalogo.ttl` y `semantic/data/sintetico/*.ttl`, validando antes con las formas de `semantic/shapes/`.

Parar el entorno: `docker compose down`. Para borrar además los datos (PostgreSQL, Fuseki y distribuciones): `docker compose down -v`.

## Servicios

| Servicio | Imagen | Puerto en el host | Notas |
|---|---|---|---|
| `frontend` | build de `./frontend` | 127.0.0.1:5173 | Servidor de desarrollo de Vite |
| `backend` | build de `./backend` | 127.0.0.1:8000 | FastAPI; `GET /health` y `GET /health/ready`; aplica las migraciones al arrancar |
| `fuseki` | `secoresearch/fuseki:6.2.0` | 127.0.0.1:3030 | Dataset TDB2 persistente `itot`, creado desde `infra/fuseki/assembler.ttl` |
| `postgres` | `postgres:17.6-alpine` | 127.0.0.1:5432 | Usuarios y auditoría |

Todos los servicios solo escuchan en localhost. Si un puerto está ocupado en tu máquina, define en `.env` (opcionales) la variable correspondiente:

| Variable | Servicio | Por defecto |
|---|---|---|
| `POSTGRES_HOST_PORT` | postgres | 5432 |
| `FUSEKI_HOST_PORT` | fuseki | 3030 |
| `BACKEND_HOST_PORT` | backend | 8000 |
| `FRONTEND_HOST_PORT` | frontend | 5173 |

Si cambias `BACKEND_HOST_PORT`, ajusta también `VITE_API_BASE_URL` (por ejemplo `http://localhost:8001`): es la URL que usa el navegador, no la red interna de Compose. Si cambias `FRONTEND_HOST_PORT`, ajusta `CORS_ORIGINS`.

F-UJI (evaluador FAIR) se añadirá en la fase 4.

## Variables del backend añadidas en la fase 2

| Variable | Valor en `.env.example` | Descripción |
|---|---|---|
| `FUSEKI_USER` | `admin` | Usuario con el que el backend escribe en Fuseki |
| `FUSEKI_PASSWORD` | (no se define en `.env`) | Contraseña de escritura en Fuseki. `docker-compose.yml` la toma de `FUSEKI_ADMIN_PASSWORD` para no duplicarla |
| `SEMANTIC_DIR` | `/semantic` | Carpeta con formas SHACL y datos de ejemplo. Compose monta `./semantic` en `/semantic` en solo lectura y fija este valor |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | URL pública del frontend; el backend redirige con 303 a la ficha del dataset. Ajústala si cambias `FRONTEND_HOST_PORT` |

`FUSEKI_PASSWORD`, `FUSEKI_USER` y `SEMANTIC_DIR` se declaran en `environment` del servicio `backend`, que tiene prioridad sobre `env_file`. Fuera de Compose (por ejemplo, el backend en local con `uv`), define `FUSEKI_PASSWORD` a mano.

El servicio `frontend` tiene healthcheck (Vite responde en el 5173), así que `docker compose up --wait` espera también al frontend.

## Volúmenes

- `postgres-data`: base de datos.
- `fuseki-data`: triplestore (`/fuseki-base/databases`).
- `distributions`: distribuciones de datasets, montado en el backend en `/data/distributions`.

## Fuseki

Endpoints del dataset `itot`:

- Anónimos (solo lectura): `http://localhost:3030/itot/sparql` y `/itot/query`.
- Con autenticación Basic (usuario `admin`, contraseña `FUSEKI_ADMIN_PASSWORD`): `/itot/update`, `/itot/data` (también GET) y `/itot/shacl`, además de `/$/...` y el resto de rutas. Sin credenciales devuelven 401.

Así solo el backend escribe en el triplestore. La política está en `infra/fuseki/shiro.ini` (plantilla que se copia al arrancar) y en `fuseki:allowedUsers` de `infra/fuseki/assembler.ttl`. Evita `/`, `&` y `\` en `FUSEKI_ADMIN_PASSWORD`, porque la imagen la aplica con `sed`.

## CI

`.github/workflows/ci.yml` se ejecuta en cada PR y en cada push a `main`. Los jobs `backend`, `frontend` y `semantic` se saltan si la carpeta de su capa aún no existe. El job `compose` valida `docker compose config` con un `.env` copiado de `.env.example`. Las acciones están fijadas por SHA de commit.

El job `e2e` (propuesta pendiente de decisión del responsable) ejecuta `uv run --project backend pytest tests/e2e -v` con `E2E_REQUIRE_DOCKER=1`: levanta el Compose real con puertos y secretos aleatorios (ver `tests/e2e/README.md`). Tiene un límite de 30 minutos porque construye las imágenes del backend y del frontend.

## Publicar una versión de ontología o vocabulario (fase 3)

«Publicar» significa crear una **Release de GitHub**. Se hace empujando una etiqueta de Git sobre un commit que ya esté en `main`; la etiqueta la crea y empuja quien tiene permiso para ello, tras fusionar la PR con el RDF.

| Qué | Etiqueta | Fichero que debe existir |
|---|---|---|
| Ontología | `onto/{slug}/v{version}` | `semantic/ontologias/{slug}/{version}.ttl` |
| Vocabulario SKOS | `vocab/{slug}/v{version}` | `semantic/vocabularios/{slug}.ttl` |
| Vocabulario corporativo | `vocab/corp/{slug}/v{version}` | `semantic/vocabularios/corp/{slug}.ttl` |

`{slug}` y `{version}` siguen `semantic/uris.md` (`MAYOR.MENOR.PARCHE`, sin `v` en el fichero ni en el RDF; la `v` solo va en la etiqueta).

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
   - SKOS: la propiedad indicada por la variable `SKOS_VERSION_PREDICATE` en cada `skos:ConceptScheme` (por defecto `owl:versionInfo`; `none` desactiva la comprobación). **Pendiente de que `semantico` fije dónde va la versión del esquema.**
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

Hoy `load-semantic` solo carga `semantic/data/`. Que además ingiera `semantic/ontologias/` y `semantic/vocabularios/` es un cambio del backend (pendiente de confirmar); este flujo no lo modifica.
