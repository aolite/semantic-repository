# Pruebas de pantallas (Playwright)

Pruebas con Chromium sobre el Compose real (decisión 34). Comprueban lo que las e2e de `tests/e2e/` no pueden: lo que pinta el navegador.

| Fichero | Qué comprueba |
|---|---|
| `tests/pantallas.spec.ts` | Las 6 pantallas (Catálogo, Ficha de dataset, Vocabularios, Ficha de ontología, Navegador SKOS y Consola SPARQL) cargan con datos reales, sin errores de consola ni textos rotos |
| `tests/dataset-fair.spec.ts` | La sección FAIR repite la evaluación real de F-UJI y enlaza el informe; «Descargar» / «Iniciar sesión para descargar» / solo metadatos según `download`; descarga con enlace firmado tras iniciar sesión |
| `tests/sparql.spec.ts` | Consulta de referencia sin sesión (Tabla, JSON, CSV), errores de validación, guardar una consulta personal con sesión y que otro miembro no la vea |
| `tests/catalogo.spec.ts` | Paginación (20 por página) y filtros de dominio, tipo y búsqueda en la URL |

## Ejecución

Con el Compose levantado y los datos cargados (`docker compose exec backend python -m app.cli load-semantic`):

```sh
cd tests/browser
npm ci
npx playwright install chromium
BASE_URL=http://localhost:5173 API_URL=http://localhost:8000 npx playwright test
```

| Variable | Efecto |
|---|---|
| `BASE_URL` | El frontend (por defecto `http://localhost:5173`) |
| `API_URL` | El backend (por defecto `http://localhost:8000`) |
| `CI` | Con valor, un reintento e informe HTML en `playwright-report/` |
| `BROWSER_COMPOSE_ARGS` | Opciones de `docker compose` para crear el admin con la CLI del backend, p. ej. `-p miproyecto` si el entorno no se llama `itot` |
| `BROWSER_ADMIN_USER`, `BROWSER_ADMIN_PASSWORD` | Un admin que ya exista, en lugar de crearlo con la CLI |

`support/global-setup.ts` crea sus propias cuentas (un admin con la CLI y un editor y dos miembros por la API, con contraseñas aleatorias que solo viven en memoria), crea el catálogo `browser-pruebas` (decisión 49: cada serie pertenece a uno), publica en él 21 series pequeñas para la paginación y espera a que F-UJI termine la evaluación de los datasets sintéticos. No hay credenciales ni datos fijos.

Solo habla con `BASE_URL` y `API_URL`: úsalo contra el entorno local o de pruebas del proyecto.

## Defectos conocidos

`QA-G4-04` (frontend) está corregido: su prueba es una prueba normal y protege contra la regresión.
