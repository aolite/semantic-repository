# Frontend · Repositorio semántico IT&OT

Cliente web en React + TypeScript + Vite + React Router, con pruebas en Vitest y Testing Library.

Estado (fase 3): navegación lateral, login con JWT y las pantallas **Catálogo** (`/`), **Ficha de dataset** (`/datasets/:slug`), **Vocabularios y ontologías** (`/vocabularios`), **Ficha de ontología** (`/ontologias/:slug`) y **Navegador SKOS** (`/vocabularios/:slug` y `/vocabularios/corp/:slug`). La consola SPARQL sigue como página provisional (fase 4).

## Variables de entorno

Vite solo expone al navegador las variables con prefijo `VITE_`. Se leen de `.env` (no versionado) o del entorno del proceso, por ejemplo desde Docker Compose. El `.env.example` de la raíz del repositorio documenta sus valores ficticios.

| Variable | Uso | Ejemplo ficticio |
|---|---|---|
| `VITE_API_BASE_URL` | URL base de la API del backend. La usa el navegador, así que debe ser accesible desde la máquina del usuario (no el nombre de un servicio interno de Docker). | `http://localhost:8000` |
| `VITE_BASE_URI` | Base de las URIs persistentes. Equivale a `BASE_URI` del backend. La URL del endpoint SPARQL que se muestra en la navegación es `VITE_BASE_URI` + `sparql`. Si falta, se muestra el placeholder `[DOMINIO]/itot/sparql`. También sirve para deducir, a partir de una URI persistente (`semantic/uris.md`), la pantalla a la que enlaza: temas y `conformsTo` de la ficha de dataset, `broader` y `related` de un concepto. Si falta o la URI no es de esa base, se muestra el texto sin enlace. | `https://semantic.example.org/itot/` |

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
  components/   layout, navegación lateral, etiquetas, tarjetas, árbol SKOS e iconos
  hooks/        hooks reutilizables (debounce de la búsqueda, carga de la API)
  pages/        Catálogo, fichas, Vocabularios, Navegador SKOS, login y páginas provisionales
  vocab/        textos de los tipos y estados de vocabulario, y rutas a partir de las URIs
  styles/       variables CSS del diseño y estilos por pantalla
  test/         configuración, utilidades y respuestas ficticias de las pruebas
```

## Pantallas

### Catálogo (`/`)

- Búsqueda con debounce de 300 ms que lanza `GET /datasets?q=`; chips de dominio (`aria-pressed`) que lanzan `domain` (`it`, `ot`, `pqc`, `ia`); se pide `page_size=100` (la interfaz de paginación está pendiente).
- Selector de tipo: «Datasets» pide `GET /datasets`; «Vocabularios y ontologías» pide `GET /vocabularies?q=` y muestra sus tarjetas con el mismo estilo; «Todo» pide las dos y muestra primero los datasets y después los vocabularios.
- Las tarjetas de `/vocabularies` no traen dominio: con un dominio elegido los vocabularios no se piden ni se muestran, y una nota lo indica.
- El placeholder del buscador sigue siendo «Título, concepto o URI», aunque la API no busca por URI (decisión abierta 30).
- El contador suma los `total` de las dos respuestas. Hay estados de carga (`role="status"`), vacío y error (`role="alert"` con «Reintentar»).
- No se muestran «Importar SKOS» ni «Publicar recurso» (sin funcionalidad todavía) ni la barra FAIR (fase 4).

### Ficha de dataset (`/datasets/:slug`)

- El backend redirige aquí (303) desde la URI persistente; `?version=X.Y.Z` muestra una versión antigua.
- Secciones del prototipo: descripción, versionado con historial (cada versión enlazada con `?version=`; la mostrada lleva `aria-current`), distribuciones (sin columna «Acción» hasta la fase 4), procedencia PROV-O, RDF (Turtle o JSON-LD desde `GET /datasets/{slug}/rdf`), Evaluación FAIR («Disponible en la fase 4») y metadatos DCAT-AP.
- Las secciones sin datos muestran un texto neutro. 404 o 422 de la API: «Dataset no encontrado».
- No se muestran «Nueva versión» ni «Solicitar acceso» (fase 4).
- Los temas (`dcat:theme`) enlazan a su concepto en el navegador SKOS y `dct:conformsTo` a la ficha de ontología (con `?version=` si apunta a un `owl:versionIRI`). Si la URI no sigue el patrón, se muestra sin enlace.
- Desde la fase 3 el dominio es un concepto de `vocab/dominio` y no el esquema de los temas: los temas se colorean con el dominio de la serie si solo tiene uno.

### Vocabularios y ontologías (`/vocabularios`)

- Tarjetas de estadísticas por tipo con los recuentos de `counts` (botones `aria-pressed`; pulsar la activa vuelve a «Todos»), búsqueda con debounce que lanza `q` y chips de tipo que lanzan `kind`.
- Cada tarjeta: tipo RDF, tipo de vocabulario, estado (Publicada, Borrador o Referenciada), «Sintético» si `synthetic`, prefijo y espacio de nombres, descripción, métricas (`N clases · N propiedades`, «Externa · referencia» o `N conceptos`) y versión.
- Destinos: ontología propia → `/ontologias/{slug}`; esquema de dominio → `/vocabularios/{slug}`; corporativo → `/vocabularios/corp/{slug}`. Las ontologías externas no tienen ficha: enlazan a su IRI oficial.
- No se muestran «Catalogar externa» ni «Nuevo vocabulario» (sin funcionalidad todavía). Los chips de la tarjeta del prototipo («OWL 2 DL», «Importa SOSA, SAREF»…) no se muestran: la API no los da.

### Ficha de ontología (`/ontologias/:slug`)

- El backend redirige aquí (303) desde `onto/{slug}`; `?version=X.Y.Z` muestra una versión antigua (URI de la versión y descargas con `version`).
- «Descargar Turtle» y las serializaciones (Turtle, RDF/XML, JSON-LD) son enlaces a `GET /ontologies/{slug}/rdf?format=`. «Copiar URI» copia la URI de la ontología (o el `owl:versionIRI` en una versión antigua).
- Métricas del fichero (clases, propiedades de objeto y de datos, individuos, axiomas lógicos, imports), perfil OWL (con los perfiles compatibles aproximados), expresividad DL («Sin calcular»: la API la manda siempre `null`), consistencia con el razonador que devuelve la API (con el motivo si `consistent` es `null`) y cobertura de documentación.
- Imports y alineamientos (relación abreviada, número de axiomas y correspondencias desplegables), versionado (`owl:versionIRI`, `owl:priorVersion`, `owl:backwardCompatibleWith` e historial), uso en el catálogo y metadatos VANN y DCT con los vocabularios SKOS usados.
- No se muestran «Documentación» ni la fila de documentación WIDOCO (sin funcionalidad todavía). 404 o 422 de la API: «Ontología no encontrada».

### Navegador SKOS (`/vocabularios/:slug` y `/vocabularios/corp/:slug`)

- El backend redirige aquí (303) desde `vocab/…`; `?concepto=` elige el concepto. Sin `?concepto=` se muestra el primero del árbol.
- Lista de esquemas («De dominio» y «Corporativos») a partir de `GET /vocabularies`, con el actual marcado con `aria-current`.
- Árbol con el patrón «tree» de WAI-ARIA (`role="tree"`, `treeitem` con `aria-expanded`, `aria-selected` y `aria-level`, foco itinerante): flechas arriba y abajo, derecha (abrir o bajar al primer hijo), izquierda (cerrar o subir al padre), Inicio, Fin, e Intro o Espacio para seleccionar. El filtro no distingue mayúsculas ni acentos, abre las ramas y conserva los antepasados. Solo filtra por `prefLabel`: el árbol de la API no trae `altLabel`.
- Detalle del concepto: `prefLabel` por idioma (es, ca, en y el resto), `altLabel`, `broader` y `related` enlazados, mapeos externos («Sin mapeos externos todavía» si no hay; los que contienen placeholders no se enlazan) y recursos que lo usan.
- «Exportar Turtle» enlaza a `GET /schemes/…/rdf?format=turtle`. No se muestra «Nuevo concepto». Los corporativos muestran «Responsable: [RESPONSABLE]».

### Navegación lateral

- En Catálogo y en el resto de pantallas, «Esquemas de conceptos» enlaza cada dominio a su esquema de dominio con el mismo slug (`/vocabularios/it`, `ot`, `pqc`, `ia`).
- En las pantallas de vocabularios muestra «Tipos de vocabulario», como el prototipo, y marca «Vocabularios».

### Textos que pone el frontend

- Nombres y colores de dominio por slug, como en el prototipo (`src/catalog/labels.ts`).
- Etiquetas cortas de formato: `application/vnd.tcpdump.pcap` → PCAP, `text/csv` → CSV, `application/vnd.apache.parquet` → Parquet, `application/json` → JSON, `text/turtle` → RDF, `application/ld+json` → JSON-LD, `application/rdf+xml` → RDF/XML. Los demás tipos y los títulos (p. ej. NPZ) se muestran tal cual.
- Acceso: `RESTRICTED` → «Restringido», `PUBLIC` → «Público»; otros códigos, tal cual.
- Placeholders cuando el campo llega `null`: `[LICENCIA]`, `[CONTACTO]`, `[FECHA]` y `[PROYECTO]`. Para campos sin placeholder en el prototipo: «Sin indicar».
- Marca «Dataset sintético» cuando `synthetic` es `true` (decisión de G2, no está en el prototipo). En ontologías y esquemas, «Sintético».
- Tipos y estados de vocabulario con los nombres y colores del prototipo (`src/vocab/labels.ts`).
- Placeholders de vocabularios cuando el campo llega `null`: `[VERSIÓN]`, `[AUTORES]`, `[REPOSITORIO GIT]` (la API no lo da), `[RESPONSABLE]` y `[N] conceptos` (esquemas sin conceptos).

## API

El contrato es `backend/openapi.json`. El cliente usa estos endpoints:

- `POST /auth/token`: formulario OAuth2 password (`application/x-www-form-urlencoded`, campos `username` y `password`). Devuelve el esquema `Token`: `{ access_token, token_type: "bearer", expires_in, role }`. Las credenciales incorrectas devuelven 401.
- `GET /auth/me` con `Authorization: Bearer <token>`. Devuelve el esquema `UserRead`: `{ id, username, role, is_active, created_at, updated_at }`. La navegación muestra `username` y `role` (`miembro`, `editor` o `admin`).
- `GET /health`: esquema `HealthStatus`, `{ status: "ok" }`.
- `GET /datasets?q=&domain=&page=&page_size=`: esquema `DatasetPage` con `DatasetCard`.
- `GET /datasets/{slug}?version=`: esquema `DatasetDetail` (serie, `VersionDetail` e historial `VersionSummary`).
- `GET /datasets/{slug}/rdf?format=turtle|jsonld&version=`: RDF en texto.
- `GET /vocabularies?q=&kind=`: esquema `VocabularyPage` con `VocabularyCard` y `counts`.
- `GET /ontologies/{slug}?version=`: esquema `OntologyDetail`. `GET /ontologies/{slug}/rdf?format=turtle|rdfxml|jsonld&version=`: enlace de descarga.
- `GET /schemes/{slug}` y `/schemes/corp/{slug}`: esquema `SchemeDetail` con el árbol `ConceptNode`. `…/concepts/{concept}`: esquema `ConceptDetail`. `…/rdf?format=`: enlace de descarga.

Los tipos de `src/api/types.ts` están copiados a mano del OpenAPI, sin generador. Si el contrato cambia, hay que actualizarlos ahí. Las respuestas ficticias de las pruebas (`src/test/utils.tsx`, `src/test/fixtures.ts` y `src/test/vocabFixtures.ts`) usan esos tipos, así que el build falla si se desalinean.

## Sesión

El token JWT se guarda **solo en memoria** (estado de React), no en `sessionStorage` ni `localStorage`:

- Un script inyectado (XSS) no puede leerlo del almacenamiento del navegador, y el token no queda en disco ni sobrevive a la pestaña.
- El coste es que recargar la página cierra la sesión. Si eso molesta, la alternativa segura es un refresh token en una cookie `HttpOnly`, `Secure` y `SameSite=Strict` emitida por el backend; es una decisión del backend.

Los lectores son anónimos: todas las rutas actuales son públicas.

## Tipografía

IBM Plex Mono se sirve desde el propio frontend con el paquete `@fontsource/ibm-plex-mono` (pesos 400 y 500, subconjunto latino) en lugar de cargarla desde Google Fonts, para no enviar las IP de los usuarios a un servicio externo.
