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

Carga `semantic/data/vocab-minimo.ttl` y `semantic/data/sintetico/*.ttl`, validando antes con las formas de `semantic/shapes/`. Este comando lo implementa y confirma `backend`; esta documentación se ajustará si cambia su nombre u opciones.

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
