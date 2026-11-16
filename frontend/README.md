# Frontend · Repositorio semántico IT&OT

Cliente web en React + TypeScript + Vite + React Router, con pruebas en Vitest y Testing Library.

Estado (fase 4): navegación lateral, login con JWT y las 6 pantallas del prototipo: **Catálogo** (`/`), **Ficha de dataset** (`/datasets/:slug`), **Vocabularios y ontologías** (`/vocabularios`), **Ficha de ontología** (`/ontologias/:slug`), **Navegador SKOS** (`/vocabularios/:slug` y `/vocabularios/corp/:slug`) y **Consola SPARQL** (`/sparql`).

## Variables de entorno

Vite solo expone al navegador las variables con prefijo `VITE_`. Se leen de `.env` (no versionado) o del entorno del proceso, por ejemplo desde Docker Compose. El `.env.example` de la raíz del repositorio documenta sus valores ficticios.

| Variable | Uso | Ejemplo ficticio |
|---|---|---|
| `VITE_API_BASE_URL` | URL base de la API del backend. La usa el navegador, así que debe ser accesible desde la máquina del usuario (no el nombre de un servicio interno de Docker). | `http://localhost:8000` |
| `VITE_BASE_URI` | Base de las URIs persistentes. Equivale a `BASE_URI` del backend. La URL del endpoint SPARQL que se muestra en la navegación y en la consola es `VITE_BASE_URI` + `sparql` (la consola ejecuta contra `VITE_API_BASE_URL` + `/sparql`). Las URIs persistentes que devuelve la API para abrir en el navegador (fichero de una distribución, enlace firmado) se piden a la API con la misma ruta (`apiHref` en `src/api/client.ts`). Si falta, se muestra el placeholder `[DOMINIO]/itot/sparql`. También sirve para deducir, a partir de una URI persistente (`semantic/uris.md`), la pantalla a la que enlaza: temas y `conformsTo` de la ficha de dataset, `broader` y `related` de un concepto. Si falta o la URI no es de esa base, se muestra el texto sin enlace. | `https://semantic.example.org/itot/` |

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
  catalog/      textos de presentación (dominios, formatos, acceso, placeholders) y estado del Catálogo en la URL
  components/   layout, navegación lateral, etiquetas, tarjetas, árbol SKOS e iconos
  dataset/      secciones «Distribuciones» y «Evaluación FAIR» de la ficha, con sus textos
  hooks/        hooks reutilizables (debounce de la búsqueda, carga de la API)
  lib/          utilidades del navegador (lanzar una descarga)
  pages/        Catálogo, fichas, Vocabularios, Navegador SKOS, Consola SPARQL y login
  sparql/       presentación de resultados (tabla, JSON, CSV) y mensajes de error de la consola
  vocab/        textos de los tipos y estados de vocabulario, y rutas a partir de las URIs
  styles/       variables CSS del diseño y estilos por pantalla
  test/         configuración, utilidades y respuestas ficticias de las pruebas
```

## Pantallas

### Catálogo (`/`)

- Búsqueda con debounce de 300 ms que lanza `GET /datasets?q=`; chips de dominio (`aria-pressed`) que lanzan `domain` (`it`, `ot`, `pqc`, `ia`).
- Estado en la URL (decisión 33), para compartir enlaces y usar «atrás»: `?q=`, `?dominio=` (`it`, `ot`, `pqc`, `ia`), `?tipo=` (`datasets` o `vocabularios`; sin él, «Todo») y `?pagina=` (desde 2). Los valores desconocidos se ignoran. Los chips y la paginación crean una entrada del historial; la búsqueda sustituye la actual (si no, habría una por búsqueda). Cambiar un filtro vuelve a la página 1. Si la URL cambia desde fuera (atrás, un enlace), el campo de búsqueda la sigue (`src/catalog/urlState.ts`).
- Paginación de los datasets con `page` y `page_size=20` (el prototipo no fija el tamaño): «Anterior», «Página N de M» y «Siguiente», enlaces dentro de `<nav aria-label="Paginación">`, solo si hay más de una página. `GET /vocabularies` no se pagina: en «Todo», los vocabularios van tras la última página de datasets.
- Selector de tipo: «Datasets» pide `GET /datasets`; «Vocabularios y ontologías» pide `GET /vocabularies?q=` y muestra sus tarjetas con el mismo estilo; «Todo» pide las dos y muestra primero los datasets y después los vocabularios.
- Con un dominio elegido, los vocabularios se piden con `GET /vocabularies?domain=`: solo quedan los esquemas de dominio de ese dominio.
- El placeholder del buscador es «Título, concepto o URI»: desde la decisión 30, `q` también busca en la URI del recurso.
- El contador suma los `total` de las dos respuestas. Hay estados de carga (`role="status"`), vacío y error (`role="alert"` con «Reintentar»).
- Las tarjetas de dataset con `fair_total` muestran «FAIR {n}» y su barra (decorativa, `aria-hidden`), como el prototipo. Sin `fair_total`, no.
- No se muestran «Importar SKOS» ni «Publicar recurso» (decisión 35).

### Ficha de dataset (`/datasets/:slug`)

- El backend redirige aquí (303) desde la URI persistente; `?version=X.Y.Z` muestra una versión antigua.
- Secciones del prototipo: descripción, versionado con historial (cada versión enlazada con `?version=`; la mostrada lleva `aria-current`), distribuciones, procedencia PROV-O, RDF (Turtle o JSON-LD desde `GET /datasets/{slug}/rdf`), Evaluación FAIR y metadatos DCAT-AP.
- **Distribuciones** (`id="distribuciones"`, destino de la redirección `…#distribuciones` del backend), con la columna «Acción» (encabezado oculto visualmente, como el prototipo) según `download`:
  - `open`: enlace «Descargar» al fichero (`download_url`, pedido a la API).
  - `authenticated` sin sesión: enlace «Iniciar sesión para descargar», que lleva al login y vuelve a la ficha (con la misma `?version=`).
  - `authenticated` con sesión: botón «Descargar», que pide `POST …/download-link` con el JWT y abre el enlace firmado (el JWT no va en la URL). Si falla (401, 403 u otro), lo dice junto al botón.
  - `metadata_only`: «Solo metadatos: la distribución se conserva en infraestructura de Eurecat.»
  - `unavailable`: «No disponible».
  - Los enlaces y botones llevan `aria-label` con el nombre de la distribución («Descargar Distribución A»).
- **Evaluación FAIR** con `version.fair`: el total sobre 100, el nivel de madurez tal cual lo da F-UJI (`maturity`, sin umbrales propios), el texto del prototipo bajo el nivel y las barras F, A, I y R con los colores del prototipo (decorativas; la puntuación va en texto). No se muestran las pistas de ejemplo por principio. Pie: «Última evaluación: {evaluated_at (AAAA-MM-DD)} · Evaluador: {evaluator}», con `[FECHA]` y `[MOTOR FAIR]` si llegan `null`, y «Ver informe completo de pruebas» a `report_url` (pedido a la API). Los estados `pending`, `running`, `failed` y `not_evaluated` (o `fair: null`) muestran un texto propio; si además hay puntuaciones (de la última evaluación terminada), se siguen mostrando. La ficha no se refresca sola mientras la evaluación está en curso.
- Las secciones sin datos muestran un texto neutro. 404 o 422 de la API: «Dataset no encontrado».
- No se muestran «Nueva versión» (decisión 35), «Solicitar acceso» ni «Solicitar».
- Los temas (`dcat:theme`) enlazan a su concepto en el navegador SKOS y `dct:conformsTo` a la ficha de ontología (con `?version=` si apunta a un `owl:versionIRI`). Si la URI no sigue el patrón, se muestra sin enlace.
- Desde la fase 3 el dominio es un concepto de `vocab/dominio` y no el esquema de los temas: los temas se colorean con el dominio de la serie si solo tiene uno.

### Vocabularios y ontologías (`/vocabularios`)

- Tarjetas de estadísticas por tipo con los recuentos de `counts` (botones `aria-pressed`; pulsar la activa vuelve a «Todos»), búsqueda con debounce que lanza `q` y chips de tipo que lanzan `kind`.
- Cada tarjeta: tipo RDF, tipo de vocabulario, dominio con su color (solo esquemas de dominio), estado (Publicada, Borrador o Referenciada), «Sintético» si `synthetic`, prefijo y espacio de nombres, descripción, métricas (`N clases · N propiedades`, «Externa · referencia» o `N conceptos`) y versión.
- Destinos: ontología propia → `/ontologias/{slug}`; esquema de dominio → `/vocabularios/{slug}`; corporativo → `/vocabularios/corp/{slug}`. Las ontologías externas no tienen ficha: enlazan a su IRI oficial.
- No se muestran «Catalogar externa» ni «Nuevo vocabulario» (sin funcionalidad todavía). Los chips de la tarjeta del prototipo («OWL 2 DL», «Importa SOSA, SAREF»…) no se muestran: la API no los da.

### Ficha de ontología (`/ontologias/:slug`)

- El backend redirige aquí (303) desde `onto/{slug}`; `?version=X.Y.Z` muestra una versión antigua (URI de la versión y descargas con `version`).
- «Descargar Turtle» y las serializaciones (Turtle, RDF/XML, JSON-LD) son enlaces a `GET /ontologies/{slug}/rdf?format=&download=1` (el backend responde con `Content-Disposition: attachment`). «Copiar URI» copia la URI de la ontología (o el `owl:versionIRI` en una versión antigua).
- Métricas del fichero (clases, propiedades de objeto y de datos, individuos, axiomas lógicos, imports), perfil OWL (con los perfiles compatibles aproximados), expresividad DL («Sin calcular»: la API la manda siempre `null`), consistencia con el razonador que devuelve la API (con el motivo si `consistent` es `null`) y cobertura de documentación.
- Imports y alineamientos (relación abreviada, número de axiomas y correspondencias desplegables), versionado (`owl:versionIRI`, `owl:priorVersion`, `owl:backwardCompatibleWith` e historial), uso en el catálogo y metadatos VANN y DCT con los vocabularios SKOS usados.
- No se muestran «Documentación» ni la fila de documentación WIDOCO (sin funcionalidad todavía). 404 o 422 de la API: «Ontología no encontrada».

### Navegador SKOS (`/vocabularios/:slug` y `/vocabularios/corp/:slug`)

- El backend redirige aquí (303) desde `vocab/…`; `?concepto=` elige el concepto. Sin `?concepto=` se muestra el primero del árbol.
- Lista de esquemas («De dominio» y «Corporativos») a partir de `GET /vocabularies`, con el actual marcado con `aria-current` y el color del dominio cuando el esquema lo tiene.
- Árbol con el patrón «tree» de WAI-ARIA (`role="tree"`, `treeitem` con `aria-expanded`, `aria-selected` y `aria-level`, foco itinerante): flechas arriba y abajo, derecha (abrir o bajar al primer hijo), izquierda (cerrar o subir al padre), Inicio, Fin, e Intro o Espacio para seleccionar. El filtro busca por `prefLabel` y `altLabel` sin distinguir mayúsculas ni acentos, abre las ramas y conserva los antepasados. Los conceptos salen en el orden de la API (hoy, alfabético): el contrato no trae un orden y el frontend no lo fuerza.
- Detalle del concepto: `prefLabel` por idioma (es, ca, en y el resto), `altLabel`, `broader` y `related` enlazados, mapeos externos («Sin mapeos externos todavía» si no hay; los que contienen placeholders no se enlazan) y recursos que lo usan.
- Los esquemas auxiliares (`vocab/dominio` y `vocab/tipo-dataset`, `kind: auxiliary`) también se ven: llevan la etiqueta neutra «Esquema auxiliar». El backend redirige aquí la URI del dominio de cada dataset (`/vocabularios/dominio?concepto=ot`).
- «Exportar Turtle» enlaza a `GET /schemes/…/rdf?format=turtle&download=1`. No se muestra «Nuevo concepto». Los corporativos muestran «Responsable: [RESPONSABLE]».

### Consola SPARQL (`/sparql`)

- Cabecera con «Endpoint · {`VITE_BASE_URI` + `sparql`}».
- «Consultas guardadas» de `GET /sparql/queries`: primero las de referencia y después, con sesión, las personales (pedidas con el JWT). Botones con `aria-pressed`, título y pista. Al entrar se elige la primera. Lo editado en cada consulta se conserva al cambiar de una a otra.
- Editor con su `label` («Consulta»). «Ejecutar» (o Ctrl+Intro / Cmd+Intro en el editor) manda `POST /sparql` con `application/sparql-query`, con el JWT si hay sesión (límite de usuario autenticado).
- Resultados SELECT en Tabla (cabeceras `?var`), JSON (la respuesta tal cual) o CSV (formato CSV del W3C, generado en el navegador a partir del JSON para no repetir la consulta, que cuenta para el límite de frecuencia). Recuento «N resultados» y «Sin resultados.» si no hay filas. ASK muestra `true` o `false`; CONSTRUCT y DESCRIBE, el Turtle, sin pestañas de formato. Si la API manda `X-Result-Truncated: true`, se avisa.
- Errores legibles (`role="alert"`): 400 (con el `detail` del backend), 413, 429 (con `Retry-After` si lo hay), 504, sin conexión y otros.
- «Guardar» **solo con sesión** (sin sesión no se muestra: ir al login perdería la consulta del editor, porque la sesión vive en memoria). Abre un formulario con «Título» y «Pista (opcional)» que hace `POST /sparql/queries`; al guardar, recarga la lista y elige la nueva. Escape o «Cancelar» lo cierran y devuelven el foco a «Guardar». Errores 401, 409 (máximo de consultas), 413 y 422 con su mensaje.
- No hay edición ni borrado de consultas personales: el prototipo no tiene esos controles.

### Navegación lateral

- En Catálogo y en el resto de pantallas, «Esquemas de conceptos» enlaza cada dominio a su esquema de dominio con el mismo slug (`/vocabularios/it`, `ot`, `pqc`, `ia`).
- En las pantallas de vocabularios muestra «Tipos de vocabulario», como el prototipo, y marca «Vocabularios».

### Textos que pone el frontend

- Nombres y colores de dominio por slug, como en el prototipo (`src/catalog/labels.ts`).
- Etiquetas cortas de formato: `application/vnd.tcpdump.pcap` → PCAP, `text/csv` → CSV, `application/vnd.apache.parquet` → Parquet, `application/json` → JSON, `text/turtle` → RDF, `application/ld+json` → JSON-LD, `application/rdf+xml` → RDF/XML. Los demás tipos y los títulos (p. ej. NPZ) se muestran tal cual.
- Acceso: `RESTRICTED` → «Restringido», `PUBLIC` → «Público»; otros códigos, tal cual.
- Placeholders cuando el campo llega `null`: `[LICENCIA]`, `[CONTACTO]`, `[FECHA]` y `[PROYECTO]`. Para campos sin placeholder en el prototipo: «Sin indicar».
- Marca «Dataset sintético» cuando `synthetic` es `true` (decisión de G2, no está en el prototipo). En ontologías y esquemas, «Sintético».
- Tipos y estados de vocabulario con los nombres y colores del prototipo (`src/vocab/labels.ts`). Si la API manda un dominio, tipo o estado desconocido, se muestra tal cual con colores neutros, sin romper la pantalla.
- Un error de renderizado en una pantalla muestra «No se ha podido mostrar esta pantalla.» (`role="alert"`) en lugar de una página en blanco (`src/components/ErrorBoundary.tsx`).
- Textos de la fase 4 que no salen del prototipo: los estados FAIR sin puntuación (`src/dataset/fair.ts`), las acciones de distribución sin descarga y sus errores (`src/dataset/download.ts`), la paginación, y los mensajes, el estado inicial y el formulario de guardar de la consola SPARQL (`src/sparql/results.ts` y `src/pages/SparqlPage.tsx`).
- Placeholders de vocabularios cuando el campo llega `null`: `[VERSIÓN]`, `[AUTORES]`, `[REPOSITORIO GIT]` (la API no lo da), `[RESPONSABLE]` y `[N] conceptos` (esquemas sin conceptos).

## API

El contrato es `backend/openapi.json`. El cliente usa estos endpoints:

- `POST /auth/token`: formulario OAuth2 password (`application/x-www-form-urlencoded`, campos `username` y `password`). Devuelve el esquema `Token`: `{ access_token, token_type: "bearer", expires_in, role }`. Las credenciales incorrectas devuelven 401.
- `GET /auth/me` con `Authorization: Bearer <token>`. Devuelve el esquema `UserRead`: `{ id, username, role, is_active, created_at, updated_at }`. La navegación muestra `username` y `role` (`miembro`, `editor` o `admin`).
- `GET /health`: esquema `HealthStatus`, `{ status: "ok" }`.
- `GET /datasets?q=&domain=&page=&page_size=`: esquema `DatasetPage` con `DatasetCard`.
- `GET /datasets/{slug}?version=`: esquema `DatasetDetail` (serie, `VersionDetail` e historial `VersionSummary`).
- `GET /datasets/{slug}/rdf?format=turtle|jsonld&version=`: RDF en texto.
- `POST /datasets/{slug}/versions/{version}/distributions/{dist}/download-link` (miembro): `{ url, expires_at }`. `dist` es el último segmento de la URI de la distribución.
- `GET /dataset/{slug}/{version}/{dist}/fichero`: descarga (enlace del navegador, a partir de `download_url` o del enlace firmado).
- `GET /datasets/{slug}/versions/{version}/fair/report`: informe FAIR completo (enlace del navegador, a partir de `report_url`).
- `POST /sparql` (`application/sparql-query`; `Accept: application/sparql-results+json, text/turtle;q=0.9`).
- `GET /sparql/queries` (lista de `SavedQuery`) y `POST /sparql/queries` (`{ title, hint, query }`).
- `GET /vocabularies?q=&kind=&domain=`: esquema `VocabularyPage` con `VocabularyCard` y `counts`.
- `GET /ontologies/{slug}?version=`: esquema `OntologyDetail`. `GET /ontologies/{slug}/rdf?format=turtle|rdfxml|jsonld&version=`: enlace de descarga.
- `GET /schemes/{slug}` y `/schemes/corp/{slug}`: esquema `SchemeDetail` con el árbol `ConceptNode`. `…/concepts/{concept}`: esquema `ConceptDetail`. `…/rdf?format=`: enlace de descarga.

Los errores de la API llegan como `ApiError` con `status`, `detail` (si el `ErrorResponse` lo trae como texto) y `retryAfter` (cabecera `Retry-After` en segundos).

Los tipos de `src/api/types.ts` están copiados a mano del OpenAPI, sin generador. Los de la fase 4 (`FairSummary`, `DistributionRead.download`, `DownloadLink`, `SavedQuery`, `DatasetCard.fair_total`…) salen del contrato de la fase y se contrastan con el `openapi.json` real en la integración (prueba de contrato de `qa`). Si el contrato cambia, hay que actualizarlos ahí. Las respuestas ficticias de las pruebas (`src/test/utils.tsx`, `src/test/fixtures.ts` y `src/test/vocabFixtures.ts`) usan esos tipos, así que el build falla si se desalinean.

## Sesión

El token JWT se guarda **solo en memoria** (estado de React), no en `sessionStorage` ni `localStorage`:

- Un script inyectado (XSS) no puede leerlo del almacenamiento del navegador, y el token no queda en disco ni sobrevive a la pestaña.
- El coste es que recargar la página cierra la sesión. Si eso molesta, la alternativa segura es un refresh token en una cookie `HttpOnly`, `Secure` y `SameSite=Strict` emitida por el backend; es una decisión del backend.

Los lectores son anónimos: todas las rutas son públicas. La sesión solo añade la descarga de distribuciones restringidas, las consultas personales y «Guardar» en la consola SPARQL.

## Tipografía

IBM Plex Mono se sirve desde el propio frontend con el paquete `@fontsource/ibm-plex-mono` (pesos 400 y 500, subconjunto latino) en lugar de cargarla desde Google Fonts, para no enviar las IP de los usuarios a un servicio externo.
