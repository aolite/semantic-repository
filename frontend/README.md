# Frontend · Repositorio semántico IT&OT

Cliente web en React + TypeScript + Vite + React Router, con pruebas en Vitest y Testing Library.

Estado (fase 4): navegación lateral, login con JWT y las 6 pantallas del prototipo: **Catálogo** (`/`), **Ficha de dataset** (`/datasets/:slug`), **Vocabularios y ontologías** (`/vocabularios`), **Ficha de ontología** (`/ontologias/:slug`), **Navegador SKOS** (`/vocabularios/:slug` y `/vocabularios/corp/:slug`) y **Consola SPARQL** (`/sparql`). Además (decisión 49), las pantallas de **catálogos** (`/catalogos` y `/catalogos/:slug`), el alta, la edición y la baja de catálogos y datasets, y «Nueva versión» en la Ficha de dataset. Y (decisión 50) los botones «Importar SKOS» y «Publicar recurso» del Catálogo, y la publicación, edición, traslado y baja de esquemas SKOS y ontologías propias. Los formularios no están en el prototipo: las propone el frontend con sus estilos y componentes, y las revisa el responsable.

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
  components/   layout, navegación lateral, etiquetas, tarjetas, árbol SKOS, iconos, paginación, diálogo de confirmación, ficha de baja y avisos
  crud/         formularios de catálogos, datasets y versiones (decisión 49) y de esquemas y ontologías (decisión 50), su validación y los mensajes de error de la API
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
- **Filtro por catálogo** (decisiones 49 y 50): selector «Catálogo» con «Todos los catálogos» y los de `GET /catalogs`, que lanza `GET /datasets?catalog=` y `GET /vocabularies?catalog=` (desde la decisión 50 los esquemas y las ontologías propias también están en un catálogo; las externas, en ninguno) y se guarda en la URL como `?catalogo=` (vuelve a la página 1). Si `GET /catalogs` falla, el selector no aparece y el resto sigue funcionando. Al lado, el enlace «Ver los catálogos» a `/catalogos`.
- **«Importar SKOS» y «Publicar recurso»** (prototipo; decisión 50 d), a la derecha del título, solo para editor y admin, en un grupo «Publicar» (`display: flex; flex-wrap: wrap; gap: 10px`): «Importar SKOS» secundario (borde y texto `#662483`, fondo blanco) y «Publicar recurso» primario (fondo y borde `#662483`, texto blanco), los dos en negrita, `min-height: 44px`, `padding: 0 18px` y `border-radius: 8px`.
  - **[PROPUESTA]** «Publicar recurso» es un botón con menú (patrón «menu button» de WAI-ARIA, `src/components/PublishMenu.tsx`): `aria-haspopup="menu"` y `aria-expanded`; se abre con clic, Intro, Espacio o las flechas; flechas, Inicio y Fin recorren las opciones; Escape cierra y devuelve el foco; Tab o un clic fuera cierran. Opciones, en este orden: «Nuevo catálogo», «Nuevo dataset», «Nuevo vocabulario» y «Nueva ontología».
  - **[PROPUESTA]** Cada opción abre su formulario bajo la cabecera (`src/crud/PublishActions.tsx` y `src/crud/usePublishActions.tsx`, que comparte la ficha de catálogo): «Nuevo catálogo» es el de `/catalogos`; «Nuevo dataset» es el de la ficha de catálogo con un selector «Catálogo» obligatorio; «Nuevo vocabulario» e «Importar SKOS» abren el mismo formulario de publicar un esquema desde fichero (cambia el título); «Nueva ontología» publica una versión de ontología. Al terminar, va a la ficha del recurso con un aviso. Cancelar o Escape devuelven el foco al botón que lo abrió.

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
- **410** (dataset dado de baja, decisión 49): ficha mínima con `GoneResponse` (ver «Recursos dados de baja»), no un error.
- Si el dataset tiene catálogo (`catalog`), las migas lo enlazan: «Catálogo / {catálogo} / {dominio} / Dataset».
- **Acciones del editor y el admin** (decisión 49), a la derecha de la cabecera, en un grupo «Acciones del dataset». El miembro y el anónimo no las ven:
  - «Editar»: título y descripción de la serie (en español), publicador y catálogo (`PATCH /datasets/{slug}`, solo con los campos que cambian; cambiar el catálogo es moverlo, `catalog`). El publicador se precarga con `DatasetDetail.publisher.label` y solo se manda si cambia; vaciarlo conserva el actual (la API no admite borrarlo). Las versiones publicadas no se tocan.
  - «Nueva versión» (botón del prototipo): sube el RDF de la serie completa (Turtle `.ttl` o JSON-LD `.jsonld`/`.json`) a `POST /datasets?catalog={catálogo del dataset}`. Ver «Nueva versión».
  - «Dar de baja»: diálogo de confirmación que avisa de que se eliminan los ficheros de todas sus distribuciones; `DELETE /datasets/{slug}` y vuelta a la ficha de su catálogo (o al Catálogo) con el aviso «Dataset «…» dado de baja.».
  - Tras guardar o publicar, la ficha se vuelve a pedir (se sigue mostrando la anterior mientras tanto) y un aviso (`role="status"`) dice el resultado.
- No se muestran «Solicitar acceso» ni «Solicitar».
- Los temas (`dcat:theme`) enlazan a su concepto en el navegador SKOS y `dct:conformsTo` a la ficha de ontología (con `?version=` si apunta a un `owl:versionIRI`). Si la URI no sigue el patrón, se muestra sin enlace.
- Desde la fase 3 el dominio es un concepto de `vocab/dominio` y no el esquema de los temas: los temas se colorean con el dominio de la serie si solo tiene uno.

### Vocabularios y ontologías (`/vocabularios`)

- Tarjetas de estadísticas por tipo con los recuentos de `counts` (botones `aria-pressed`; pulsar la activa vuelve a «Todos»), búsqueda con debounce que lanza `q` y chips de tipo que lanzan `kind`.
- Cada tarjeta: tipo RDF, tipo de vocabulario, dominio con su color (solo esquemas de dominio), estado (Publicada, Borrador o Referenciada), «Sintético» si `synthetic`, prefijo y espacio de nombres, descripción, métricas (`N clases · N propiedades`, «Externa · referencia» o `N conceptos`) y versión.
- Destinos: ontología propia → `/ontologias/{slug}`; esquema de dominio → `/vocabularios/{slug}`; corporativo → `/vocabularios/corp/{slug}`. Las ontologías externas no tienen ficha: enlazan a su IRI oficial.
- **Filtro por catálogo** (decisión 50): selector «Catálogo» con los de `GET /catalogs`, que lanza `GET /vocabularies?catalog=` y se guarda en la URL como `?catalog=` (un valor que no es un slug se ignora). Con un catálogo, las ontologías externas no aparecen (no están en ninguno). Si `GET /catalogs` falla, el selector no aparece.
- Las tarjetas de ontologías propias y esquemas muestran «Catálogo: …» enlazado a su ficha (`VocabularyCard.catalog`; también en el Catálogo).
- No se muestran «Catalogar externa» ni «Nuevo vocabulario» de esta pantalla (los esquemas se publican desde el Catálogo). Los chips de la tarjeta del prototipo («OWL 2 DL», «Importa SOSA, SAREF»…) no se muestran: la API no los da.

### Ficha de ontología (`/ontologias/:slug`)

- El backend redirige aquí (303) desde `onto/{slug}`; `?version=X.Y.Z` muestra una versión antigua (URI de la versión y descargas con `version`).
- «Descargar Turtle» y las serializaciones (Turtle, RDF/XML, JSON-LD) son enlaces a `GET /ontologies/{slug}/rdf?format=&download=1` (el backend responde con `Content-Disposition: attachment`). «Copiar URI» copia la URI de la ontología (o el `owl:versionIRI` en una versión antigua).
- Métricas del fichero (clases, propiedades de objeto y de datos, individuos, axiomas lógicos, imports), perfil OWL (con los perfiles compatibles aproximados), expresividad DL («Sin calcular»: la API la manda siempre `null`), consistencia con el razonador que devuelve la API (con el motivo si `consistent` es `null`) y cobertura de documentación.
- Imports y alineamientos (relación abreviada, número de axiomas y correspondencias desplegables), versionado (`owl:versionIRI`, `owl:priorVersion`, `owl:backwardCompatibleWith` e historial), uso en el catálogo y metadatos VANN y DCT con los vocabularios SKOS usados.
- No se muestran «Documentación» ni la fila de documentación WIDOCO (sin funcionalidad todavía). 404 o 422 de la API: «Ontología no encontrada».
- «Catálogo: …» bajo la URI, enlazado a la ficha del catálogo (decisión 50). 410 (ontología dada de baja, también al pedir una versión con `?version=`): ficha mínima de la baja, que nombra la versión pedida.
- **[PROPUESTA]** Acciones del editor y el admin (decisión 50), en el grupo «Acciones de la ontología» (`src/crud/OntologyActions.tsx`):
  - «Mover de catálogo»: selector «Catálogo de destino» con el actual marcado; `PATCH /ontologies/{slug}` con `catalog`. Los metadatos de una ontología van en cada versión, que es inmutable: se cambian publicando una versión nueva.
  - «Nueva versión»: sube el RDF de la versión (`POST /ontologies?catalog=` con el catálogo de la ontología) y vuelve a la ficha de la versión actual con el aviso.
  - «Dar de baja»: diálogo de confirmación; `DELETE /ontologies/{slug}` y vuelta a la ficha de su catálogo. Si otra ontología la importa o usa sus términos, el 409 `in_use` lista los usos (`used_by`) en el diálogo.

### Navegador SKOS (`/vocabularios/:slug` y `/vocabularios/corp/:slug`)

- El backend redirige aquí (303) desde `vocab/…`; `?concepto=` elige el concepto. Sin `?concepto=` se muestra el primero del árbol.
- Lista de esquemas («De dominio» y «Corporativos») a partir de `GET /vocabularies`, con el actual marcado con `aria-current` y el color del dominio cuando el esquema lo tiene.
- Árbol con el patrón «tree» de WAI-ARIA (`role="tree"`, `treeitem` con `aria-expanded`, `aria-selected` y `aria-level`, foco itinerante): flechas arriba y abajo, derecha (abrir o bajar al primer hijo), izquierda (cerrar o subir al padre), Inicio, Fin, e Intro o Espacio para seleccionar. El filtro busca por `prefLabel` y `altLabel` sin distinguir mayúsculas ni acentos, abre las ramas y conserva los antepasados. Los conceptos salen en el orden de la API (hoy, alfabético): el contrato no trae un orden y el frontend no lo fuerza.
- Detalle del concepto: `prefLabel` por idioma (es, ca, en y el resto), `altLabel`, `broader` y `related` enlazados, mapeos externos («Sin mapeos externos todavía» si no hay; los que contienen placeholders no se enlazan) y recursos que lo usan.
- Los esquemas auxiliares (`vocab/dominio` y `vocab/tipo-dataset`, `kind: auxiliary`) también se ven: llevan la etiqueta neutra «Esquema auxiliar». El backend redirige aquí la URI del dominio de cada dataset (`/vocabularios/dominio?concepto=ot`).
- «Exportar Turtle» enlaza a `GET /schemes/…/rdf?format=turtle&download=1`. No se muestra «Nuevo concepto». Los corporativos muestran «Responsable: [RESPONSABLE]».
- «Catálogo: …» en la cabecera, enlazado a la ficha del catálogo (decisión 50; los auxiliares no tienen).
- **Conceptos retirados** (`deprecated`, decisión 50): en el árbol, la etiqueta en gris con la marca «Retirado» (el `treeitem` se anuncia «… (retirado)»); en el detalle, un aviso «Retirado · owl:deprecated» con sus sustitutos (`replaced_by`, `dct:isReplacedBy`) enlazados, o «No indica sustitutos.».
- 410 (esquema dado de baja): ficha mínima de la baja; con `?concepto=`, dice que el concepto se dio de baja con su esquema. Si el 410 llega al pedir el concepto, el panel muestra «Concepto dado de baja».
- **[PROPUESTA]** Acciones del editor y el admin (decisión 50), en el grupo «Acciones del esquema» (`src/crud/SchemeActions.tsx`); no salen en los esquemas auxiliares, que no se gestionan desde la aplicación:
  - «Editar»: título y descripción **en español** (los demás idiomas y los conceptos no cambian), publicador y catálogo; `PATCH /schemes/…` solo con lo que cambia. Si el esquema no tenía descripción, no obliga a ponerla.
  - «Republicar»: sube el esquema completo (`POST /schemes?catalog=` con su catálogo). El texto explica que tiene que traer todos los conceptos publicados (un concepto se retira con `owl:deprecated`) y que no se reactivan.
  - «Dar de baja»: diálogo de confirmación; `DELETE /schemes/…` y vuelta a la ficha de su catálogo. Si sus conceptos se usan, el 409 `in_use` lista los usos en el diálogo.

### Consola SPARQL (`/sparql`)

- Cabecera con «Endpoint · {`VITE_BASE_URI` + `sparql`}».
- «Consultas guardadas» de `GET /sparql/queries`: primero las de referencia y después, con sesión, las personales (pedidas con el JWT). Botones con `aria-pressed`, título y pista. Al entrar se elige la primera. Lo editado en cada consulta se conserva al cambiar de una a otra.
- Editor con su `label` («Consulta»). «Ejecutar» (o Ctrl+Intro / Cmd+Intro en el editor) manda `POST /sparql` con `application/sparql-query`, con el JWT si hay sesión (límite de usuario autenticado).
- Resultados SELECT en Tabla (cabeceras `?var`), JSON (la respuesta tal cual) o CSV (formato CSV del W3C, generado en el navegador a partir del JSON para no repetir la consulta, que cuenta para el límite de frecuencia). Recuento «N resultados» y «Sin resultados.» si no hay filas. ASK muestra `true` o `false`; CONSTRUCT y DESCRIBE, el Turtle, sin pestañas de formato. Si la API manda `X-Result-Truncated: true`, se avisa.
- Errores legibles (`role="alert"`): 400 (con el `detail` del backend), 413, 429 (con `Retry-After` si lo hay), 504, sin conexión y otros.
- «Guardar» **solo con sesión** (sin sesión no se muestra: ir al login perdería la consulta del editor, porque la sesión vive en memoria). Abre un formulario con «Título» y «Pista (opcional)» que hace `POST /sparql/queries`; al guardar, recarga la lista y elige la nueva. Escape o «Cancelar» lo cierran y devuelven el foco a «Guardar». Errores 401, 409 (máximo de consultas), 413 y 422 con su mensaje.
- No hay edición ni borrado de consultas personales: el prototipo no tiene esos controles.

### Catálogos (`/catalogos`, decisión 49)

- `GET /catalogs` (sin el catálogo raíz ni las bajas): tarjetas con `dcat:Catalog`, título enlazado a la ficha, descripción, publicador y «N datasets» (y, desde la decisión 50, «N vocabularios» y «N ontologías» si los tiene). Recuento «N catálogos», y estados de carga, vacío («Todavía no hay catálogos.») y error con «Reintentar».
- Editor y admin: «Nuevo catálogo» (`aria-expanded`) abre el formulario con slug, título y descripción (en español) y publicador, todos obligatorios. Bajo el slug se ve la URI que formará (`VITE_BASE_URI` + `catalogo/{slug}`). `POST /catalogs` y, al crear, a la ficha del catálogo con el aviso «Catálogo creado.».

### Ficha de catálogo (`/catalogos/:slug`, decisión 49)

- El backend redirige aquí (303) desde la URI persistente `catalogo/{slug}`.
- Cabecera con `dcat:Catalog`, título, descripción, URI con «Copiar URI» y `dct:publisher`. Debajo, sus datasets con las tarjetas del Catálogo (`GET /datasets?catalog={slug}`, paginados con `?pagina=` como el Catálogo) o «Este catálogo todavía no tiene datasets.».
- 404: «Catálogo no encontrado». 410: ficha mínima de la baja.
- Editor y admin, en el grupo «Publicar» (decisión 50, 2026-11-26): los mismos botones «Importar SKOS» y «Publicar recurso», con el mismo estilo, que la pantalla Catálogo (`src/crud/usePublishActions.tsx`, con la opción `catalog`), con este catálogo fijado. El menú no tiene «Nuevo catálogo» (los catálogos no agrupan otros: solo el raíz lleva `dcat:catalog`). Los formularios no dejan elegir catálogo: muestran «Catálogo: …» y su título termina en «en este catálogo».
  - «Nuevo dataset en este catálogo»: slug, título, descripción y publicador opcional (`POST /catalogs/{slug}/datasets`). Al crear, va a la ficha del dataset (serie sin versiones) con el aviso «Dataset creado. Publica su primera versión con «Nueva versión».».
  - «Nuevo vocabulario en este catálogo» e «Importar SKOS en este catálogo» (`POST /schemes?catalog={slug}`) y «Nueva ontología en este catálogo» (`POST /ontologies?catalog={slug}`).
  - Abrir uno de estos formularios cierra «Editar catálogo», y al revés. En un catálogo dado de baja (410) no hay botones.
- Editor y admin, en el grupo «Acciones del catálogo»:
  - «Editar catálogo»: título, descripción y publicador, con los valores actuales (`PATCH /catalogs/{slug}`, solo los campos que cambian). El slug no se edita.
  - «Dar de baja»: diálogo de confirmación; `DELETE /catalogs/{slug}` y vuelta a `/catalogos` con el aviso. Si el catálogo no está vacío, el 409 (`ConflictResponse` con `kind: catalog_not_empty`) se muestra en el diálogo con la lista de los datasets (`datasets`) y de los esquemas y ontologías (`resources`, decisión 50) que hay que mover o dar de baja antes, enlazados a su ficha.
- Secciones «Vocabularios SKOS» y «Ontologías» (decisión 50) con los de la ficha (`CatalogDetail.schemes` y `ontologies`), enlazados al Navegador SKOS y a la Ficha de ontología, con su recuento.

### Formularios de catálogos y datasets

- Paneles bajo la cabecera, con los campos (`label`, `aria-invalid`, `aria-describedby` con la ayuda y el error de cada campo), botones y colores de las pantallas existentes. El foco va al primer campo; Escape o «Cancelar» los cierran y devuelven el foco al botón que los abrió.
- Validación en el cliente con los límites del OpenAPI (`src/crud/validation.ts`): obligatorios, slug con el patrón de `semantic/uris.md` (`^[a-z0-9]+(-[a-z0-9]+)*$`, hasta 200) y longitudes máximas. El backend vuelve a validar todo con SHACL.
- Errores de la API (`src/crud/errors.ts`), en un `role="alert"` del formulario y marcando el campo:
  - 409 `ConflictResponse` al crear, en el slug: `slug_in_use` («Ya existe un recurso con ese slug. Elige otro.») y `withdrawn` («Ese slug es de un recurso dado de baja y no se reutiliza. Elige otro.»). Un 409 sin `kind` muestra un texto que cubre los dos casos.
  - `IngestErrorResponse` por `kind`: `withdrawn`, `catalog_conflict`, `version_removed`, `version_immutable` (409) y `catalog`, `shacl`, `syntax`, `structure`, `uri`, `limit` (422), con un texto propio para cada uno y la lista de incidencias (`issues`, con el último segmento de `path` o `focus_node`, hasta 10). Decisión 50: `prefix_withdrawn`, `prefix_in_use` (con el recurso que ya usa el prefijo, `issues[].value`), `concepts_removed`, `concept_reactivated` (409) y `replacement`, `deprecated_theme` (cada tema retirado con sus sustitutos, `issues[].replaced_by`) y `unknown_theme` (temas que no son conceptos de un esquema vivo) (422). Los esquemas y las ontologías tienen su propio texto para `catalog_conflict` y `withdrawn`. Un `kind` que el frontend aún no conoce, si trae `issues`, muestra el `detail` del backend y las incidencias.
  - 409 `ConflictResponse` `in_use` (baja de un esquema o una ontología en uso, decisión 50): el mensaje y la lista `used_by` (quién lo usa, enlazado a su ficha, la propiedad abreviada y lo que usa).
  - 403 con `kind: not_managed` (ontología externa o esquema auxiliar, decisión 50): «Este recurso no se gestiona desde la aplicación…», distinto del 403 por rol, que no lleva `kind`.
  - 422 de validación de FastAPI: marca los campos por su `loc` (sin mostrar valores).
  - 503 con `Retry-After` (otra escritura tiene el bloqueo del catálogo, QA-49-03): «El servidor está ocupado; inténtalo de nuevo en unos segundos.», con el formulario abierto para reintentar. Sin `Retry-After`, «El repositorio no está disponible ahora mismo…».
  - 401, 403, 404, 410, 413, 415 y sin conexión, con su mensaje.

### Nueva versión

Una versión DCAT-AP lleva distribuciones, procedencia PROV-O y temas, y el backend comprueba la inmutabilidad de las versiones sobre el RDF: no cabe en un formulario plano (`backend/README.md`, «Catálogos y bajas»). Por eso el formulario sube un fichero RDF de la serie, que el backend valida con SHACL antes de publicar:

- Campo «Fichero RDF (Turtle o JSON-LD)»; el `Content-Type` sale de la extensión (`.ttl` → `text/turtle`; `.jsonld` o `.json` → `application/ld+json`).
- El texto explica que el fichero lleva la serie completa: sus metadatos, todas las versiones ya publicadas sin cambios y la nueva (si falta o cambia una, 409).
- `?catalog=` es el catálogo del dataset (se muestra «Catálogo: …»). Si la serie no tiene catálogo, un selector opcional permite elegir uno; sin él, lo declara el RDF.
- Al publicar, el aviso dice las versiones de la serie (`IngestResult.versions`), o que no ha cambiado nada (`changed: false`). Si el RDF era de otra serie, va a su ficha.
- Los ficheros de las distribuciones no se suben aquí (`PUT …/file`): queda pendiente.

### Publicar un esquema o una versión de ontología (decisión 50)

`src/crud/PublishRdfForm.tsx` **[PROPUESTA]**: mismo campo de fichero que «Nueva versión» (Turtle o JSON-LD por la extensión) y un selector «Catálogo» obligatorio (`?catalog=`), o «Catálogo: …» fijo al republicar un esquema o publicar una versión de una ontología que ya está en uno. El backend valida con SHACL (y, en las ontologías, calcula métricas y consistencia) antes de escribir. Avisos: «Esquema publicado con N conceptos.», «Esquema republicado…», «Versión X de la ontología publicada.» o «El RDF era idéntico al publicado…».

### Recursos dados de baja

Un 410 de `GET /datasets/{slug}`, `GET /catalogs/{slug}`, `GET /schemes/…` u `GET /ontologies/{slug}` con `GoneResponse` muestra una ficha mínima (`src/components/GoneView.tsx`): migas, `dcat:Dataset`, `dcat:Catalog`, `skos:ConceptScheme` u `owl:Ontology`, la marca «Dado de baja» (colores del estado «Borrador»), el título (o el último segmento de la URI), la URI, `prov:invalidatedAtTime` (AAAA-MM-DD en un `<time>`, o `[FECHA]` si llega `null`), `adms:status` Withdrawn, un texto sobre lo que implica y un enlace de vuelta.

### Permisos

Los controles de crear, editar, dar de baja y publicar versiones solo se muestran a editor y admin (`canEdit` en `src/auth/roles.ts`, con sesión). El miembro y el anónimo no los ven; el backend responde igualmente 403 y 401, y el formulario lo explica si ocurre.

### Confirmaciones

Las bajas se confirman en un diálogo propio (`src/components/ConfirmDialog.tsx`), nunca con `window.confirm` ni `alert`: `role="dialog"` con `aria-modal`, título y descripción enlazados, foco inicial en «Cancelar», foco atrapado con Tab, Escape para cancelar y vuelta del foco al botón. Mientras la petición está en curso, los botones quedan con `aria-disabled` (sin perder el foco) y Escape no cierra.

### Navegación lateral

- «Catálogo» queda marcado (`aria-current="true"`) en las fichas de dataset y en las pantallas de catálogos (`/catalogos…`). No hay un enlace propio a `/catalogos`: se llega desde el filtro del Catálogo, las migas y la redirección de `catalogo/{slug}`.
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
- Textos de las decisiones 49 y 50 que no salen del prototipo: pantallas de catálogos, menú de «Publicar recurso», formularios, avisos, diálogos de baja, ficha mínima de la baja, marca de concepto retirado y mensajes de error (`src/crud/errors.ts`, `src/crud/publish.ts`, `src/crud/validation.ts`, `src/components/GoneView.tsx`).
- Textos de la fase 4 que no salen del prototipo: los estados FAIR sin puntuación (`src/dataset/fair.ts`), las acciones de distribución sin descarga y sus errores (`src/dataset/download.ts`), la paginación, y los mensajes, el estado inicial y el formulario de guardar de la consola SPARQL (`src/sparql/results.ts` y `src/pages/SparqlPage.tsx`).
- Placeholders de vocabularios cuando el campo llega `null`: `[VERSIÓN]`, `[AUTORES]`, `[REPOSITORIO GIT]` (la API no lo da), `[RESPONSABLE]` y `[N] conceptos` (esquemas sin conceptos).

## API

El contrato es `backend/openapi.json`. El cliente usa estos endpoints:

- `POST /auth/token`: formulario OAuth2 password (`application/x-www-form-urlencoded`, campos `username` y `password`). Devuelve el esquema `Token`: `{ access_token, token_type: "bearer", expires_in, role }`. Las credenciales incorrectas devuelven 401.
- `GET /auth/me` con `Authorization: Bearer <token>`. Devuelve el esquema `UserRead`: `{ id, username, role, is_active, created_at, updated_at }`. La navegación muestra `username` y `role` (`miembro`, `editor` o `admin`).
- `GET /health`: esquema `HealthStatus`, `{ status: "ok" }`.
- `GET /datasets?q=&domain=&catalog=&page=&page_size=`: esquema `DatasetPage` con `DatasetCard` (con `catalog` desde la decisión 49).
- `GET /datasets/{slug}?version=`: esquema `DatasetDetail` (serie, `catalog`, `publisher`, `VersionDetail` e historial `VersionSummary`); 410 con `GoneResponse`.
- Decisión 49 (con el JWT de editor o admin salvo las lecturas): `GET /catalogs` (`CatalogPage` con `CatalogSummary`), `GET /catalogs/{slug}` (`CatalogDetail`; 410 `GoneResponse`), `POST /catalogs` (`CatalogCreate`), `PATCH /catalogs/{slug}` (`CatalogUpdate`), `DELETE /catalogs/{slug}` (204; 409 `ConflictResponse`), con `ConflictResponse` también en el 409 de los dos `POST` de alta, `POST /catalogs/{slug}/datasets` (`DatasetCreate`), `PATCH /datasets/{slug}` (`DatasetUpdate`), `DELETE /datasets/{slug}` (204) y `POST /datasets?catalog=` (RDF en `text/turtle` o `application/ld+json`; `IngestResult`, o `IngestErrorResponse` en 409 y 422).
- `GET /datasets/{slug}/rdf?format=turtle|jsonld&version=`: RDF en texto.
- `POST /datasets/{slug}/versions/{version}/distributions/{dist}/download-link` (miembro): `{ url, expires_at }`. `dist` es el último segmento de la URI de la distribución.
- `GET /dataset/{slug}/{version}/{dist}/fichero`: descarga (enlace del navegador, a partir de `download_url` o del enlace firmado).
- `GET /datasets/{slug}/versions/{version}/fair/report`: informe FAIR completo (enlace del navegador, a partir de `report_url`).
- `POST /sparql` (`application/sparql-query`; `Accept: application/sparql-results+json, text/turtle;q=0.9`).
- `GET /sparql/queries` (lista de `SavedQuery`) y `POST /sparql/queries` (`{ title, hint, query }`).
- `GET /vocabularies?q=&kind=&domain=`: esquema `VocabularyPage` con `VocabularyCard` y `counts`.
- `GET /ontologies/{slug}?version=`: esquema `OntologyDetail`. `GET /ontologies/{slug}/rdf?format=turtle|rdfxml|jsonld&version=`: enlace de descarga.
- `GET /schemes/{slug}` y `/schemes/corp/{slug}`: esquema `SchemeDetail` con el árbol `ConceptNode`. `…/concepts/{concept}`: esquema `ConceptDetail`. `…/rdf?format=`: enlace de descarga.
- Decisión 50 (con el JWT de editor o admin salvo las lecturas): `GET /vocabularies?catalog=`, `POST /schemes?catalog=` y `POST /ontologies?catalog=` (RDF; `SchemeIngestResult` u `OntologyIngestResult`, o `IngestErrorResponse` en 409 y 422, `ForbiddenResponse` en 403), `PATCH /schemes/{slug}` y `/schemes/corp/{slug}` (`SchemeUpdate`), `PATCH /ontologies/{slug}` (`OntologyUpdate`), `DELETE` de los tres (204; 409 `ConflictResponse` con `used_by`), y los campos nuevos `catalog` (tarjetas y fichas), `scheme_count`, `ontology_count`, `schemes` y `ontologies` (catálogos), `deprecated` y `replaced_by` (conceptos).

Los errores de la API llegan como `ApiError` con `status`, `detail` (si el `ErrorResponse` lo trae como texto), `retryAfter` (cabecera `Retry-After` en segundos) y `body` (el cuerpo JSON tal cual, para leer `GoneResponse`, `ConflictResponse` o `IngestErrorResponse`).

Los tipos de `src/api/types.ts` están copiados a mano del OpenAPI, sin generador. Los de la fase 4 (`FairSummary`, `DistributionRead.download`, `DownloadLink`, `SavedQuery`, `DatasetCard.fair_total`…) salen del contrato de la fase y se contrastan con el `openapi.json` real en la integración (prueba de contrato de `qa`). Si el contrato cambia, hay que actualizarlos ahí. Las respuestas ficticias de las pruebas (`src/test/utils.tsx`, `src/test/fixtures.ts` y `src/test/vocabFixtures.ts`) usan esos tipos, así que el build falla si se desalinean.

## Sesión

El token JWT se guarda **solo en memoria** (estado de React), no en `sessionStorage` ni `localStorage`:

- Un script inyectado (XSS) no puede leerlo del almacenamiento del navegador, y el token no queda en disco ni sobrevive a la pestaña.
- El coste es que recargar la página cierra la sesión. Si eso molesta, la alternativa segura es un refresh token en una cookie `HttpOnly`, `Secure` y `SameSite=Strict` emitida por el backend; es una decisión del backend.

Los lectores son anónimos: todas las rutas son públicas. La sesión añade la descarga de distribuciones restringidas, las consultas personales y «Guardar» en la consola SPARQL y, para editor y admin, la gestión de catálogos y datasets. Como la sesión vive en memoria, hay que iniciarla desde la aplicación y navegar sin recargar.

## Tipografía

IBM Plex Mono se sirve desde el propio frontend con el paquete `@fontsource/ibm-plex-mono` (pesos 400 y 500, subconjunto latino) en lugar de cargarla desde Google Fonts, para no enviar las IP de los usuarios a un servicio externo.
