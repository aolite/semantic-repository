# Backend · API FastAPI

API del repositorio semántico IT&OT. Es el único componente que escribe en el triplestore y en el almacenamiento de distribuciones (ver `Plan.md`, sección 3.2).

**Estado (fase 1):** health checks, autenticación JWT, cuentas de usuario y auditoría en PostgreSQL. El catálogo DCAT-AP, la ingesta, F-UJI, las métricas OWL y la interfaz de almacenamiento llegan en fases posteriores.

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
| `FUSEKI_URL` | no | `http://fuseki:3030` | Fuseki. En la fase 1 solo lo usa `/health/ready` |
| `FUSEKI_DATASET` | no | `itot` | Dataset de Fuseki que comprueba `/health/ready` |
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

El contrato completo está en [`openapi.json`](openapi.json).

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
def publicar(user: Annotated[User, Depends(require_role(Role.EDITOR, Role.ADMIN))]): ...


@router.get("/datasets")
def listar(user: OptionalUser): ...  # None = lector anónimo
```

`require_role` no aplica jerarquía: hay que listar todos los roles admitidos.

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

Las pruebas usan **SQLite en memoria** por defecto: no necesitan servicios, son rápidas e iguales en local y en CI. Los modelos solo usan tipos portables (`Uuid`, `JSON`, `Enum` no nativo con restricción CHECK), y `tests/test_migrations.py` comprueba que las migraciones de Alembic aplican, revierten y producen exactamente el esquema de los modelos. Fuseki se simula.

Para pasar la misma batería contra un PostgreSQL de pruebas (vacío y desechable, porque las pruebas borran y crean las tablas):

```sh
TEST_DATABASE_URL=postgresql+psycopg://<usuario>@localhost:5432/<bd_de_pruebas> uv run pytest
```

## Imagen Docker

`Dockerfile` usa `python:3.15.2-slim`, instala las dependencias de `uv.lock` sin las de desarrollo, se ejecuta con un usuario sin privilegios (uid 10001), valida la configuración, aplica las migraciones y arranca uvicorn en el puerto 8000. Si se le pasa un comando, lo ejecuta en lugar del arranque (útil para la CLI).

```sh
docker build -t itot-backend backend/
```
