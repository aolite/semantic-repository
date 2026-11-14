# Backend · API FastAPI

API del repositorio semántico IT&OT. Es el único componente que escribe en el triplestore y en el almacenamiento de distribuciones (ver `Plan.md`, sección 3.2).

**Estado (fase 2):** health checks, autenticación JWT, cuentas de usuario y auditoría en PostgreSQL (fase 1); cliente de Fuseki, ingesta DCAT-AP validada con SHACL, comando de carga de los datos sintéticos, lectura pública del catálogo y negociación de contenido en las URIs persistentes (fase 2). Solo hay metadatos: F-UJI, el acceso a distribuciones, las métricas OWL y la interfaz de almacenamiento llegan en fases posteriores.

## Requisitos

- [uv](https://docs.astral.sh/uv/). La versión de Python está fijada en `.python-version` (3.15) y uv la usa automáticamente.
- PostgreSQL y Fuseki para ejecutar la API completa. Las pruebas no necesitan ninguno de los dos.

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
| `FUSEKI_USER` | no al arrancar | — | Usuario de escritura en Fuseki (autenticación Basic). Sin él, la lectura funciona y la ingesta responde 503 con un mensaje que nombra la variable |
| `FUSEKI_PASSWORD` | no al arrancar | — | Contraseña de escritura en Fuseki. Nunca aparece en logs ni en errores |
| `FUSEKI_TIMEOUT_SECONDS` | no | `10` | Timeout de lectura de cada petición a Fuseki (la conexión tiene 3 s) |
| `SEMANTIC_DIR` | no | `../semantic` relativo a `backend/` | Carpeta `semantic/` (formas SHACL y datos). En el contenedor, `/semantic` (montada por infra, solo lectura). Una ruta relativa se resuelve contra `backend/` |
| `INGEST_MAX_BYTES` | no | `10485760` (10 MiB) | Tamaño máximo del RDF de `POST /datasets` (413 si se supera) |
| `FRONTEND_BASE_URL` | no | `http://localhost:5173` | Frontend al que redirigen (303) las URIs persistentes cuando se pide HTML |
| `JWT_SECRET` | **sí** | — | Secreto HMAC para firmar los JWT. Longitud mínima según el algoritmo: 32 bytes con HS256, 48 con HS384 y 64 con HS512. Sin él la API no arranca. Genera uno con `python -c "import secrets; print(secrets.token_urlsafe(64))"` (vale para los tres) |
| `JWT_ALGORITHM` | no | `HS256` | `HS256`, `HS384` o `HS512` |
| `JWT_EXPIRE_MINUTES` | no | `60` | Validez del token |
| `CORS_ORIGINS` | no | vacío (sin CORS) | Orígenes permitidos separados por comas; en local, `http://localhost:5173` |
| `STORAGE_BACKEND` | no | `disk` | `disk` o `r2`. Declarada; la interfaz de almacenamiento llega en la fase 4 |
| `STORAGE_DISK_PATH` | no | `/data/distributions` | Carpeta de las distribuciones en disco (fase 4) |

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
| `POST /datasets` | editor (y admin, que hereda) | Ingesta de una serie con sus versiones en Turtle (`text/turtle`) o JSON-LD (`application/ld+json`). 201 si la serie es nueva, 200 si se sustituye (`changed=false` si era idéntica), 422 con el informe si no es válida |
| `GET /datasets` | público | Tarjetas del catálogo. Filtros `q`, `domain` (`it`, `ot`, `pqc`, `ia`), `page` y `page_size` (máx. 100) |
| `GET /datasets/{slug}` | público | Ficha: serie, versión actual (o `?version=MAYOR.MENOR.PARCHE`), historial, distribuciones, cadena PROV y metadatos DCAT-AP |
| `GET /datasets/{slug}/rdf` | público | RDF de la versión (actual o `?version=`) en Turtle o JSON-LD, según `?format=turtle\|jsonld` o la cabecera `Accept` |
| `GET /dataset/{slug}` | público | URI persistente de la serie: Turtle o JSON-LD según `Accept`; con `text/html`, 303 a `{FRONTEND_BASE_URL}/datasets/{slug}` |
| `GET /dataset/{slug}/{version}` | público | URI persistente de la versión: igual, con 303 a `{FRONTEND_BASE_URL}/datasets/{slug}?version={version}` |

El contrato completo está en [`openapi.json`](openapi.json). Los campos siguen la convención del resto de la API (`snake_case`: `version_notes`, `previous_version`, `in_series`…).

### Lectura

- **Campos sin valor en el RDF** se devuelven como `null` o lista vacía. Licencia, contacto, fechas (`issued`, `modified`) y proyecto (`is_referenced_by`) son placeholders del prototipo que aún no están en los datos: el frontend muestra el placeholder. No se expone ninguna puntuación FAIR (llega en la fase 4).
- **Versión actual:** `dcat:last` de la serie; si falta, la versión de mayor número.
- **Dominio:** el esquema `{BASE_URI}vocab/{it|ot|pqc|ia}` (`skos:inScheme`) de los temas de la versión actual, con el `skos:prefLabel` del esquema como etiqueta. Si el vocabulario no está cargado, se deduce del patrón de la URI del concepto (`{BASE_URI}vocab/{esquema}/{slug}`) y la etiqueta queda `null`. `domain` es el primero de `domains`. La ficha de una versión antigua muestra el dominio de la serie.
- **Sintético:** `synthetic` es `true` si la serie (o la versión) tiene `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>`.
- **Acceso:** `access_rights` lleva la IRI de `dct:accessRights` y `code`, la entrada de la tabla europea (`PUBLIC`, `RESTRICTED`, `NON_PUBLIC`…). El texto visible lo decide el frontend.
- **Formatos:** el tipo de medio IANA (`text/csv`) de cada distribución de la versión actual o, si no tiene `dcat:mediaType`, su `dct:title` (caso de NPZ).
- **Historial:** de la versión más reciente a la más antigua. Incluye las versiones solo referenciadas por `dcat:previousVersion` (`described=false`), con el número sacado de la URI.
- **Procedencia:** cadena lineal desde el origen hasta la actividad que generó la versión (`prov:wasGeneratedBy` → `prov:used` → `prov:wasGeneratedBy`…), sin la versión misma. Los nodos en blanco tienen `uri=null`. Si una actividad usa varias entidades, se sigue la primera en orden de IRI.
- **Publisher:** se toma del grafo de cada serie (nodo en blanco con `foaf:name`); los agentes no se deduplican por nombre.
- **Búsqueda `q`:** en título y descripción (de la serie y de la versión actual) y en `skos:prefLabel`/`skos:altLabel` de los temas, sin distinguir mayúsculas ni acentos. **No llega a SPARQL**: se filtra en Python.
- **RDF de una versión:** sus triples y los de lo que cuelga de ella en el grafo de la serie (distribuciones, actividades, nodos en blanco y agentes), sin la serie ni las demás versiones. La URI de la serie devuelve el grafo completo de la serie.

### Ingesta (`POST /datasets` y `load-semantic`)

1. **Análisis**, con las IRIs relativas resueltas contra `BASE_URI`. En JSON-LD se rechazan los contextos remotos (`@context` con URL o `@import`) para que el servidor no descargue documentos externos.
2. **Estructura y URIs** (`semantic/uris.md`): exactamente una `dcat:DatasetSeries` con URI `{BASE_URI}dataset/{slug}`; cada `dcat:Dataset` es `{serie}/{version}`, con `dcat:inSeries` hacia la serie y `dcat:version` igual al último segmento; cada distribución cuelga de su versión. Todo sujeto con IRI cuelga de `BASE_URI` y, en concreto, de la serie o de `{BASE_URI}actividad/`: una ingesta no puede reescribir otra serie, el vocabulario ni el catálogo.
3. **SHACL** con pyshacl: todas las formas de `SEMANTIC_DIR/shapes/*.ttl` y, como grafo de soporte, `SEMANTIC_DIR/data/vocab-minimo.ttl`. Sin inferencia y sin la ontología DCAT.
4. **Guardado** en el grafo con nombre `{BASE_URI}dataset/{slug}`.

Si falla un paso, la respuesta es 422 con `kind` (`syntax`, `structure`, `uri` o `shacl`), `detail`, `issues` (nodo, propiedad, valor, severidad, forma y mensaje) y, para SHACL, `report` con el informe de pyshacl en texto. No se escribe nada.

**Estrategia de sustitución:** cada ingesta sustituye **por completo** el grafo con nombre de la serie (`PUT` del Graph Store Protocol, atómico en Fuseki). Por eso se envía siempre la serie entera con todas sus versiones: una versión que no venga en el RDF desaparece. Si el contenido es isomorfo al guardado, no se reescribe (`changed=false`). Las credenciales de escritura se exigen siempre, también cuando no hay cambios.

**Auditoría:** cada ingesta registra `dataset_published` con quién (`actor_*`, o `cli` desde el comando) y `details` con `series`, `slug`, `graph`, `versions`, `triples`, `created`, `changed` y `via` (`api` o `cli`). Se escribe primero en Fuseki y después se confirma la auditoría, para no registrar publicaciones que no han ocurrido.

### Grafos con nombre

| Grafo | Contenido |
|---|---|
| `{BASE_URI}dataset/{slug}` | Una serie con sus versiones, distribuciones y procedencia |
| `{BASE_URI}vocab/` | `data/vocab-minimo.ttl` (esquemas de dominio, temas y tipos de dataset) [PROPUESTA] |
| `{BASE_URI}catalogo` | `data/catalogo.ttl` (el `dcat:Catalog`) |

Las consultas usan siempre `GRAPH ?g`, así que no dependen de `tdb2:unionDefaultGraph`.

### SPARQL seguro

El protocolo SPARQL no tiene parámetros enlazados. `app/sparql.py` serializa los valores como términos escapados (`iri()` valida la IRI y rechaza los caracteres que `IRIREF` no admite; `literal()` escapa comillas, barras y controles, y rechaza `\u`/`\U`), y `render()` solo acepta esos términos: pasarle un `str` es un error. Además, slugs y versiones se validan con su patrón antes de llegar a ninguna consulta (422 si no cumplen), y el texto libre `q` no llega a SPARQL.

### Comando de carga (G2)

```sh
uv run python -m app.cli load-semantic
docker compose exec backend python -m app.cli load-semantic
```

Carga `data/vocab-minimo.ttl`, `data/catalogo.ttl` y todos los `data/sintetico/*.ttl` de `SEMANTIC_DIR`. Valida todo antes de escribir: si un fichero no es válido, muestra sus errores y no carga ninguno (código 1). Es idempotente: lo que no ha cambiado no se reescribe. Necesita `FUSEKI_USER`, `FUSEKI_PASSWORD` y la base de datos (para la auditoría).

### URIs persistentes en el despliegue (fase 5)

Las URIs se construyen con `BASE_URI` (p. ej. `https://<dominio>/itot/`) y el backend las sirve en su raíz (`/dataset/{slug}`). En el despliegue, el proxy inverso del dominio de `BASE_URI` debe:

- Enviar `{BASE_URI}dataset/*` al backend quitando el prefijo de ruta de `BASE_URI` (`/itot/dataset/x` → `/dataset/x`) y conservando la cabecera `Accept`.
- Dejar que el backend responda 303 a `FRONTEND_BASE_URL` cuando se pide HTML. Si frontend y URIs comparten dominio, `FRONTEND_BASE_URL` es ese mismo origen.
- Respetar `Vary: Accept` en cualquier caché (el backend lo envía).

El resto de patrones (`actividad/`, `vocab/`, `onto/`, `sparql`) se resolverán igual cuando tengan ruta en el backend.

## Roles y autorización

- `lector`: anónimo, sin cuenta. Ve lo público.
- `miembro`, `editor` y `admin`: cuentas guardadas en PostgreSQL.

El JWT lleva `sub` (id de la cuenta), `username`, `role`, `iat` y `exp`. El rol del token es informativo para el frontend: en cada petición el backend vuelve a leer la cuenta de la base de datos, así que un cambio de rol o una baja tienen efecto inmediato, sin esperar a que caduque el token.

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
- El login responde igual (401, mismo mensaje) si el usuario no existe, la contraseña es incorrecta, la cuenta está de baja o el nombre de usuario contiene caracteres de control (NUL incluido). En este último caso no se consulta la base de datos y la auditoría registra el motivo `invalid_username` sin guardar el valor enviado.
- Los nombres de usuario y las contraseñas con caracteres de control se rechazan en `POST /users` con 422.
- Las respuestas 422 siguen el formato de FastAPI (`detail` con `type`, `loc` y `msg`), pero nunca devuelven el valor enviado (`input`) ni el contexto (`ctx`), para no reflejar contraseñas.
- La tabla `audit_events` registra `login_success`, `login_failure` (con el motivo), `user_created`, `role_changed` (rol anterior y nuevo), `user_deactivated` y `user_reactivated`, con quién (`actor_*`), sobre quién (`target_*`) y cuándo (`occurred_at`, UTC). Las altas por CLI quedan con `actor_username = "cli"`.

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

**Datos de prueba:** `tests/fixtures/data/` es una copia de `semantic/data/` (datos sintéticos de G2, de `semantico`). Las formas SHACL no se copian: las pruebas montan un `SEMANTIC_DIR` temporal con las formas reales de `semantic/shapes/` y esos datos. Cuando `semantic/data/` llegue a `main`, la copia se puede sustituir por los ficheros originales.

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

`Dockerfile` usa `python:3.15.2-slim`, instala las dependencias de `uv.lock` sin las de desarrollo, se ejecuta con un usuario sin privilegios (uid 10001), valida la configuración, aplica las migraciones y arranca uvicorn en el puerto 8000. Si se le pasa un comando, lo ejecuta en lugar del arranque (útil para la CLI).

```sh
docker build -t itot-backend backend/
```
