# Infraestructura local

Entorno de desarrollo con Docker Compose (fase 1). Requiere Docker con Compose v2.

## Arranque

```bash
cp .env.example .env          # edita los valores; .env no se versiona
docker compose up -d --build
docker compose ps             # espera a que todos estén healthy
```

Crear el primer administrador (cuando el backend esté healthy):

```bash
docker compose exec backend uv run python -m app.cli create-admin
```

El comando `create-admin` lo implementa el backend; el comando exacto y sus opciones los confirma el agente `backend`.

Parar el entorno: `docker compose down`. Para borrar además los datos (PostgreSQL, Fuseki y distribuciones): `docker compose down -v`.

## Servicios

| Servicio | Imagen | Puerto en el host | Notas |
|---|---|---|---|
| `frontend` | build de `./frontend` | 5173 | Servidor de desarrollo de Vite |
| `backend` | build de `./backend` | 8000 | FastAPI; `GET /health` y `GET /health/ready`; aplica las migraciones al arrancar |
| `fuseki` | `secoresearch/fuseki:6.2.0` | 127.0.0.1:3030 | Dataset TDB2 persistente `itot`, creado desde `infra/fuseki/assembler.ttl` |
| `postgres` | `postgres:17.6-alpine` | 127.0.0.1:5432 | Usuarios y auditoría |

Fuseki y PostgreSQL solo escuchan en localhost. Si un puerto está ocupado en tu máquina, define `FUSEKI_HOST_PORT` o `POSTGRES_HOST_PORT` en `.env` (opcionales; no los usan las demás capas).

F-UJI (evaluador FAIR) se añadirá en la fase 4.

## Volúmenes

- `postgres-data`: base de datos.
- `fuseki-data`: triplestore (`/fuseki-base/databases`).
- `distributions`: distribuciones de datasets, montado en el backend en `/data/distributions`.

## Fuseki

Endpoints del dataset: `http://localhost:3030/itot/sparql` (consulta), `/itot/update`, `/itot/data` y `/itot/shacl`. La contraseña del usuario `admin` es `FUSEKI_ADMIN_PASSWORD`. Se evitan `/`, `&` y `\` en ella porque la imagen la aplica con `sed`.

## CI

`.github/workflows/ci.yml` se ejecuta en cada PR y en cada push a `main`. Los jobs `backend`, `frontend` y `semantic` se saltan si la carpeta de su capa aún no existe. El job `compose` valida `docker compose config` con un `.env` copiado de `.env.example`. Las acciones están fijadas por SHA de commit.
