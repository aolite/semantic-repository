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

| `tests/externas-versiones.spec.ts` | Versiones de las ontologías externas (decisión 51): ficha de una externa sin versiones (`d3f`), botón «Sustituir ontología» solo para editor y admin, enlace desde las tarjetas de Vocabularios, el diálogo con teclado y foco (`aria-modal`, Tab atrapado, Escape y vuelta del foco), errores del cliente (`role="alert"`, `aria-invalid`, foco en el primer error), errores del backend (`syntax`, `prefix_in_use`), una sustitución completa con el aviso `role="status"`, métricas, historial (`aria-current`, descarga del RDF de cada versión), `?version=n` y la URI persistente (303) |
| `tests/accesibilidad.spec.ts` | axe-core (decisión 53) en las pantallas principales, la ficha de la externa y los diálogos y formularios de CRUD (ver «Accesibilidad») |

## Accesibilidad (axe-core)

Decisión 53: `@axe-core/playwright` (versión exacta fijada en `package.json` y en `package-lock.json`) es dependencia de las pruebas de navegador. `support/a11y.ts` exporta `expectNoSeriousA11yViolations(page, testInfo, nombre, opciones?)`, que analiza la página tal como está (diálogo abierto, menú desplegado, cursor encima…) con las etiquetas `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` y `best-practice`:

- **Falla** con cualquier violación `serious` o `critical`, y escribe en el mensaje la regla y los selectores.
- Las `moderate` y `minor` no hacen fallar, pero se adjuntan al informe como `axe-<nombre>.json`.
- **No hay exclusiones.** Una regla solo se puede desactivar con `disableRules: [{ rule, reason }]`, y `reason` tiene que citar un hallazgo abierto (`QA-NN-NN`); sin él, la prueba lanza un error. Hoy no se desactiva ninguna.
- Qué cubre: Catálogo (con y sin resultados), lista y ficha de catálogo, Ficha de dataset, Vocabularios, Ficha de ontología propia (también con el cursor sobre «Descargar Turtle»), Ficha de externa (sin versiones, con versiones como anónimo y como editor, versión anterior con `?version=`, diálogo «Sustituir ontología» abierto y con errores), Navegador SKOS, Consola SPARQL (con resultados), Inicio de sesión, el menú «Publicar recurso» y sus formularios, los formularios de catálogo y dataset y los diálogos de baja de catálogo, dataset, esquema y ontología.

```sh
cd tests/browser
npm ci
npx playwright install chromium     # axe corre dentro de Chromium: no necesita nada más
BASE_URL=http://localhost:5173 API_URL=http://localhost:8000 npx playwright test tests/accesibilidad.spec.ts
```

El informe de una prueba que falla (`test-results/` o `playwright-report/`) trae el JSON completo de axe, con el HTML de cada nodo y cómo arreglarlo. En CI, el job `browser` de `.github/workflows/ci.yml` ya hace `npm ci` y `npx playwright install --with-deps chromium`, y ejecuta `npx playwright test` entero, así que axe corre sin cambiar el workflow.

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

La accesibilidad se comprueba con roles, nombres accesibles, `aria-expanded`, foco y teclado, y con axe-core (decisión 53, ver «Accesibilidad»).

Las pruebas de la decisión 51 no se pueden repetir sobre un entorno donde otra prueba haya sustituido `d3f` (es la externa «sin versiones»): `saref` admite cualquier número de sustituciones, `d3f` ninguna. Con un entorno nuevo (`docker compose down -v`) vuelve a estar limpia.
