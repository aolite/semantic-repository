# Frontend · Repositorio semántico IT&OT

Cliente web en React + TypeScript + Vite + React Router, con pruebas en Vitest y Testing Library.

Estado (fase 1): esqueleto con la navegación lateral del prototipo, páginas provisionales y login con JWT. Las pantallas reales llegan en las fases 2 a 4.

## Variables de entorno

Vite solo expone al navegador las variables con prefijo `VITE_`. Se leen de `.env` (no versionado) o del entorno del proceso, por ejemplo desde Docker Compose. El `.env.example` de la raíz del repositorio documenta sus valores ficticios.

| Variable | Uso | Ejemplo ficticio |
|---|---|---|
| `VITE_API_BASE_URL` | URL base de la API del backend. La usa el navegador, así que debe ser accesible desde la máquina del usuario (no el nombre de un servicio interno de Docker). | `http://localhost:8000` |
| `VITE_BASE_URI` | Base de las URIs persistentes. Equivale a `BASE_URI` del backend. La URL del endpoint SPARQL que se muestra en la navegación es `VITE_BASE_URI` + `sparql`. Si falta, se muestra el placeholder `[DOMINIO]/itot/sparql`. | `https://semantic.example.org/itot/` |

Ningún dominio está escrito en el código: todo sale de estas variables (ver `src/config.ts`).

## Scripts

```bash
npm ci              # instala las dependencias fijadas en package-lock.json
npm run dev         # servidor de desarrollo en http://localhost:5173
npm run lint        # ESLint
npm test -- --run   # Vitest una sola vez (sin --run queda en modo watch)
npm run build       # comprobación de tipos y build de producción en dist/
```

## Docker (desarrollo)

`Dockerfile` arranca el servidor de Vite en el puerto 5173 con `--host 0.0.0.0`, sobre una imagen de Node fijada. Las variables `VITE_*` se pasan como entorno del contenedor.

```bash
docker build -t itot-frontend-dev .
docker run --rm -p 5173:5173 \
  -e VITE_API_BASE_URL=http://localhost:8000 \
  -e VITE_BASE_URI=https://semantic.example.org/itot/ \
  itot-frontend-dev
```

## Estructura

```
src/
  api/          llamadas a la API (único sitio que usa fetch) y tipos provisionales
  auth/         contexto de sesión (AuthProvider, useAuth) y nombres de rol
  components/   layout, navegación lateral e iconos
  pages/        páginas provisionales y login
  styles/       variables CSS del diseño y estilos globales
  test/         configuración y utilidades de las pruebas
```

## API

El cliente usa estos endpoints (contrato de la fase 1, pendiente de `backend/openapi.json`):

- `POST /auth/token`: formulario OAuth2 password (`application/x-www-form-urlencoded`, campos `username` y `password`). Devuelve `{ access_token, token_type: "bearer" }`.
- `GET /auth/me` con `Authorization: Bearer <token>`. Devuelve el usuario; el cliente usa `username` y `role` (`miembro`, `editor` o `admin`).
- `GET /health`.

Los tipos de `src/api/types.ts` están escritos a mano. Cuando el backend publique el OpenAPI se sustituirán por tipos generados.

## Sesión

El token JWT se guarda **solo en memoria** (estado de React), no en `sessionStorage` ni `localStorage`:

- Un script inyectado (XSS) no puede leerlo del almacenamiento del navegador, y el token no queda en disco ni sobrevive a la pestaña.
- El coste es que recargar la página cierra la sesión. Si eso molesta, la alternativa segura es un refresh token en una cookie `HttpOnly`, `Secure` y `SameSite=Strict` emitida por el backend; es una decisión del backend.

Los lectores son anónimos: todas las rutas actuales son públicas.

## Tipografía

IBM Plex Mono se sirve desde el propio frontend con el paquete `@fontsource/ibm-plex-mono` (pesos 400 y 500, subconjunto latino) en lugar de cargarla desde Google Fonts, para no enviar las IP de los usuarios a un servicio externo.
