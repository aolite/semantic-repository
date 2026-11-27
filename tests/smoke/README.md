# Prueba de humo del despliegue

Comprueba en pocos segundos (la suite entera, unos 5 s) que un despliegue funciona. Solo usa la biblioteca estándar y pytest, y **no escribe nada** salvo con `SMOKE_ALLOW_WRITE=1`.

```sh
uv run --frozen --project backend pytest tests/smoke -v
```

## Variables

| Variable | Por defecto | Uso |
|---|---|---|
| `SMOKE_FRONTEND_URL` | `http://localhost:5173` | URL del frontend (sin barra final). El 303 de las URIs persistentes debe apuntar aquí |
| `SMOKE_API_URL` | `http://localhost:18000` | URL de la API |
| `SMOKE_BASE_URI` | `https://semantic.example.org/itot/` | `BASE_URI` del despliegue. Las URIs que devuelve el catálogo deben colgar de él; se piden a la API con su ruta relativa (`dataset/x`) |
| `SMOKE_INSECURE_TLS` | desactivado | `1`: no valida el certificado (p. ej. `tls internal` de Caddy en la prueba local) |
| `SMOKE_HTTP_PORT` | `80` | Puerto HTTP donde se espera la redirección a HTTPS |
| `SMOKE_CHECK_PORTS` | desactivado | `1`: comprueba que 3030, 13030, 5432 y 15432 del host no responden. En local fallará: están publicados en `127.0.0.1` |
| `SMOKE_EDITOR_USER`, `SMOKE_EDITOR_PASSWORD` | sin definir | Login y rol de un editor (o admin). Solo por entorno, nunca en el repositorio |
| `SMOKE_MEMBER_USER`, `SMOKE_MEMBER_PASSWORD` | sin definir | Opcional: un miembro, para comprobar que no puede escribir |
| `SMOKE_ALLOW_WRITE` | desactivado | `1` (con editor): crea y borra un catálogo `smoke-<hex>` titulado «[PRUEBA DE HUMO]». Lo borra siempre; si no pudiera, el fallo dice qué catálogo queda. Los eventos de auditoría de la prueba permanecen |
| `SMOKE_TIMEOUT` | `10` | Segundos por petición |

## Qué comprueba

- **API:** `/health`, `/health/ready` (Fuseki y PostgreSQL), versión (`info.version` de `/openapi.json`) y `/docs` público (decisión 24).
- **Frontend:** el HTML contiene la app (`#root`), sirve sus assets (no HTML disfrazado de asset) y una ruta interna del SPA.
- **Datos:** catálogos, datasets, ontologías y vocabularios SKOS no vacíos; catálogo raíz en Turtle.
- **URIs persistentes** (tomadas del catálogo cargado, nunca a mano): dataset, ontología y concepto SKOS dan 303 al frontend sin `Accept` y Turtle con `Accept: text/turtle`.
- **SPARQL:** un `SELECT` responde; los `INSERT` (por `query`, `update`, `sparql-update` y GET) dan 4xx y un `ASK` posterior confirma que no se escribió.
- **Escritura sin token:** toda operación POST, PUT, PATCH y DELETE del OpenAPI desplegado (salvo login y SPARQL) da 401 o 403 sin token y con un token inválido. Se envía con cuerpo vacío y recursos inexistentes, de modo que aunque el control fallase no se crearía nada. `/users` y `/auth/me` exigen token.
- **HTTPS** (si alguna URL lo es): certificado válido y no caducado (aviso a menos de 14 días), HTTP redirige a HTTPS.
- **Puertos internos** (con `SMOKE_CHECK_PORTS=1`): Fuseki y PostgreSQL no son accesibles desde fuera.
- **Con credenciales:** el login funciona y el rol es editor o admin; un editor no administra usuarios; un miembro recibe 403 al escribir.
- **Avisos** (no hacen fallar; se listan al final): falta HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`/CSP; la API no informa de su versión desplegada; ningún dataset con evaluación FAIR visible (F-UJI).

## Ejemplos

Pila local `itot` (valores por defecto: frontend en 5173 y API en 18000):

```sh
uv run --frozen --project backend pytest tests/smoke -v
```

Pila local con HTTPS de certificado no público (`tls internal`), dominios y puertos ficticios:

```sh
SMOKE_FRONTEND_URL=https://localhost:8443 SMOKE_API_URL=https://localhost:9443 \
SMOKE_INSECURE_TLS=1 SMOKE_HTTP_PORT=8080 \
  uv run --frozen --project backend pytest tests/smoke -v
```

Piloto (hosts ficticios), con credenciales de un editor tomadas del entorno de quien lanza la prueba:

```sh
export SMOKE_EDITOR_USER=... SMOKE_EDITOR_PASSWORD=...   # no las escribas en ficheros
SMOKE_FRONTEND_URL=https://repositorio.example.org \
SMOKE_API_URL=https://api.example.org \
SMOKE_BASE_URI=https://api.example.org/semanticrepository/ \
SMOKE_CHECK_PORTS=1 \
  uv run --frozen --project backend pytest tests/smoke -v
```

Añade `SMOKE_ALLOW_WRITE=1` para la escritura opcional. Solo se lanza contra el entorno propio del proyecto.

## Límites

- Las URIs persistentes se piden a `SMOKE_API_URL` con la ruta relativa al `BASE_URI`. Si en el piloto el proxy sirve la API bajo `/semanticrepository/`, ajusta `SMOKE_API_URL` para que incluya ese prefijo.
- La comprobación de puertos mira los dos hosts (API y frontend) desde donde se ejecuta; no sustituye a revisar el cortafuegos del VPS desde otra red.
