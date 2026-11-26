# Pruebas de pantallas (Playwright)

Pruebas con Chromium sobre el Compose real (decisión 34). Comprueban lo que las e2e de `tests/e2e/` no pueden: lo que pinta el navegador.

| Fichero | Qué comprueba |
|---|---|
| `tests/pantallas.spec.ts` | Las 6 pantallas (Catálogo, Ficha de dataset, Vocabularios, Ficha de ontología, Navegador SKOS y Consola SPARQL) cargan con datos reales, sin errores de consola ni textos rotos |
| `tests/dataset-fair.spec.ts` | La sección FAIR repite la evaluación real de F-UJI y enlaza el informe; «Descargar» / «Iniciar sesión para descargar» / solo metadatos según `download`; descarga con enlace firmado tras iniciar sesión |
| `tests/sparql.spec.ts` | Consulta de referencia sin sesión (Tabla, JSON, CSV), errores de validación, guardar una consulta personal con sesión y que otro miembro no la vea |
| `tests/catalogo.spec.ts` | Paginación (20 por página) y filtros de dominio, tipo y búsqueda en la URL |
| `tests/crud-catalogos.spec.ts` | CRUD de catálogos y datasets (decisión 49): botones por rol (anónimo, miembro, editor y admin), crear, editar y mover, «Nueva versión» (200, 201 y los 409 `version_immutable`, `catalog_conflict` y `withdrawn`), 409 al dar de baja un catálogo con datasets, 410 en la API y en la ficha, 409 por slug dado de baja, 303 de `/catalogo/{slug}`, filtro `/?catalogo=` y el diálogo de baja con teclado (Tab atrapado, Escape y vuelta del foco). La sesión vive en memoria: se navega con los enlaces de la app |
| `tests/crud-vocabularios.spec.ts` | Esquemas SKOS y ontologías en los catálogos (decisión 50): botones por rol (anónimo, miembro, editor y admin; los esquemas auxiliares no se gestionan), el menú «Publicar recurso» con teclado (Intro, Espacio, flechas, Inicio, Fin, Escape, Tab y clic fuera, con `aria-expanded`), los cuatro formularios y «Importar SKOS», errores de la ingesta en el formulario (`prefix_in_use`, `catalog_conflict`, `withdrawn`, `prefix_withdrawn`, `concepts_removed`, `concept_reactivated`, `replacement`, `deprecated_theme`, `unknown_theme`), editar y mover esquemas y ontologías, 409 `in_use` con la lista de usos y 409 `catalog_not_empty`, 410 (API y ficha, también por concepto y versión), el diálogo de baja con teclado, el filtro `?catalog=` y 403 `not_managed` contra la API. Ficha de catálogo (tercera ronda): grupo «Publicar» solo para editor y admin y sin él en un catálogo dado de baja, menú de tres opciones (sin «Nuevo catálogo») con teclado, formularios «… en este catálogo» sin selector y con `?catalog={slug}` en el POST (vocabulario, ontología, «Importar SKOS» con un 409 `prefix_in_use` y dataset desde el menú), y tarjetas de dataset sin «Catálogo: X» |

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

La accesibilidad se comprueba con roles, nombres accesibles, `aria-expanded`, foco y teclado; el repositorio no tiene axe-core entre sus dependencias y añadirlo requiere decisión del responsable.
