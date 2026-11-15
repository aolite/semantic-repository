# Frontend · Repositorio semántico IT&OT

Cliente web en React + TypeScript + Vite + React Router, con pruebas en Vitest y Testing Library.

Estado (fase 2): navegación lateral, login con JWT y las pantallas **Catálogo** (`/`) y **Ficha de dataset** (`/datasets/:slug`, con `?version=` para versiones antiguas). Vocabularios y la consola SPARQL siguen como páginas provisionales (fases 3 y 4).

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
  api/          llamadas a la API (único sitio que usa fetch) y tipos del OpenAPI
  auth/         contexto de sesión (AuthProvider, useAuth) y nombres de rol
  catalog/      textos de presentación: dominios, formatos, acceso y placeholders
  components/   layout, navegación lateral, etiquetas e iconos
  hooks/        hooks reutilizables (debounce de la búsqueda)
  pages/        Catálogo, Ficha de dataset, login y páginas provisionales
  styles/       variables CSS del diseño y estilos por pantalla
  test/         configuración, utilidades y respuestas ficticias de las pruebas
```

## Pantallas

### Catálogo (`/`)

- Búsqueda con debounce de 300 ms que lanza `GET /datasets?q=`; chips de dominio (`aria-pressed`) que lanzan `domain` (`it`, `ot`, `pqc`, `ia`); se pide `page_size=100` (la interfaz de paginación está pendiente).
- Selector de tipo: «Todo» y «Datasets» piden datasets; «Vocabularios y ontologías» muestra el estado vacío sin llamar a la API hasta la fase 3.
- El contador usa `total`. Hay estados de carga (`role="status"`), vacío y error (`role="alert"` con «Reintentar»).
- No se muestran «Importar SKOS» ni «Publicar recurso» (sin funcionalidad todavía) ni la barra FAIR (fase 4).

### Ficha de dataset (`/datasets/:slug`)

- El backend redirige aquí (303) desde la URI persistente; `?version=X.Y.Z` muestra una versión antigua.
- Secciones del prototipo: descripción, versionado con historial (cada versión enlazada con `?version=`; la mostrada lleva `aria-current`), distribuciones (sin columna «Acción» hasta la fase 4), procedencia PROV-O, RDF (Turtle o JSON-LD desde `GET /datasets/{slug}/rdf`), Evaluación FAIR («Disponible en la fase 4») y metadatos DCAT-AP.
- Las secciones sin datos muestran un texto neutro. 404 o 422 de la API: «Dataset no encontrado».
- No se muestran «Nueva versión» ni «Solicitar acceso» (fase 4).

### Textos que pone el frontend

- Nombres y colores de dominio por slug, como en el prototipo (`src/catalog/labels.ts`).
- Etiquetas cortas de formato: `application/vnd.tcpdump.pcap` → PCAP, `text/csv` → CSV, `application/vnd.apache.parquet` → Parquet, `application/json` → JSON, `text/turtle` → RDF, `application/ld+json` → JSON-LD, `application/rdf+xml` → RDF/XML. Los demás tipos y los títulos (p. ej. NPZ) se muestran tal cual.
- Acceso: `RESTRICTED` → «Restringido», `PUBLIC` → «Público»; otros códigos, tal cual.
- Placeholders cuando el campo llega `null`: `[LICENCIA]`, `[CONTACTO]`, `[FECHA]` y `[PROYECTO]`. Para campos sin placeholder en el prototipo: «Sin indicar».
- Marca «Dataset sintético» cuando `synthetic` es `true` (decisión de G2, no está en el prototipo).

## API

El contrato es `backend/openapi.json`. El cliente usa estos endpoints:

- `POST /auth/token`: formulario OAuth2 password (`application/x-www-form-urlencoded`, campos `username` y `password`). Devuelve el esquema `Token`: `{ access_token, token_type: "bearer", expires_in, role }`. Las credenciales incorrectas devuelven 401.
- `GET /auth/me` con `Authorization: Bearer <token>`. Devuelve el esquema `UserRead`: `{ id, username, role, is_active, created_at, updated_at }`. La navegación muestra `username` y `role` (`miembro`, `editor` o `admin`).
- `GET /health`: esquema `HealthStatus`, `{ status: "ok" }`.
- `GET /datasets?q=&domain=&page=&page_size=`: esquema `DatasetPage` con `DatasetCard`.
- `GET /datasets/{slug}?version=`: esquema `DatasetDetail` (serie, `VersionDetail` e historial `VersionSummary`).
- `GET /datasets/{slug}/rdf?format=turtle|jsonld&version=`: RDF en texto.

Los tipos de `src/api/types.ts` están copiados a mano del OpenAPI, sin generador. Si el contrato cambia, hay que actualizarlos ahí. Las respuestas ficticias de las pruebas (`src/test/utils.tsx`) usan esos tipos, así que el build falla si se desalinean.

## Sesión

El token JWT se guarda **solo en memoria** (estado de React), no en `sessionStorage` ni `localStorage`:

- Un script inyectado (XSS) no puede leerlo del almacenamiento del navegador, y el token no queda en disco ni sobrevive a la pestaña.
- El coste es que recargar la página cierra la sesión. Si eso molesta, la alternativa segura es un refresh token en una cookie `HttpOnly`, `Secure` y `SameSite=Strict` emitida por el backend; es una decisión del backend.

Los lectores son anónimos: todas las rutas actuales son públicas.

## Tipografía

IBM Plex Mono se sirve desde el propio frontend con el paquete `@fontsource/ibm-plex-mono` (pesos 400 y 500, subconjunto latino) en lugar de cargarla desde Google Fonts, para no enviar las IP de los usuarios a un servicio externo.
