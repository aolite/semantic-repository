# 0037. CRUD de catálogos y datasets en la aplicación

## Estado

Aceptada

## Fecha

2026-11-21

## Contexto

Hasta la fase 4, los catálogos y los datasets se cargan desde `semantic/` con `load-semantic`. La decisión 49 de `Plan.md` los hace gestionables desde la aplicación y la fija como requisito previo al despliegue del piloto.

## Decisión

El responsable del proyecto ha decidido (decisión 49 de `Plan.md`):

- **Varios catálogos.** Cada dataset pertenece a **un solo** catálogo. Los catálogos y los datasets se crean, editan y borran desde la aplicación.
- **Modificar** es editar los metadatos del catálogo, del dataset y de la serie, y publicar versiones nuevas. Las versiones publicadas siguen siendo inmutables ([0027](0027-versiones-inmutables.md)).
- **Borrado lógico.** El recurso deja de aparecer en los listados y en SPARQL, su URI responde 410 Gone con una ficha mínima y sus ficheros se eliminan.
- Crean, editan y borran el **editor** y el admin.
- Las pantallas las propone `frontend` (decisión 35 de `Plan.md`).
- Primero se cambia el contrato (patrón de URIs, SHACL de catálogos y del borrado, OpenAPI) en una PR propia.

El responsable validó el contrato (2026-11-21), a propuesta de `semantico`:

- `{BASE_URI}catalogo` pasa a ser el **catálogo raíz**, fijo: no se crea, edita ni borra desde la aplicación. Agrupa los demás con `dcat:catalog`.
- Cada catálogo es `{BASE_URI}catalogo/{slug}`.
- Las URIs de los datasets no llevan el catálogo. Mover un dataset es editar los metadatos de la serie.
- Los tres datasets sintéticos van a `{BASE_URI}catalogo/sintetico`, con el título «Datasets sintéticos de demostración».
- Borrar un catálogo con datasets da **409**.
- Las bajas son lápidas PROV (`prov:invalidatedAtTime`, `adms:status` Withdrawn y el título) en el grafo no publicado `{BASE_URI}bajas`.
- Solo el catálogo y la serie tienen lápida. Sus versiones, distribuciones y ficheros responden también 410.
- Un slug dado de baja no se reutiliza.

El responsable validó también, a propuesta de `backend` (2026-11-21):

- Publicar una versión de un dataset que ya está en otro catálogo da 409: mover es explícito, editando los metadatos.
- Los formularios guardan título y descripción solo en español en el piloto.
- En `load-semantic`, la aplicación manda en bajas y traslados, y los ficheros en los metadatos.

## Consecuencias

- Detalle del contrato en `semantic/uris.md` y `backend/README.md`.
- Las decisiones de esquemas y ontologías siguen el mismo modelo: [0038](0038-vocabularios-y-ontologias-en-los-catalogos.md).
- Relacionado: [0027](0027-versiones-inmutables.md), [0011](0011-roles-de-usuario.md), [0017](0017-admin-hereda-permisos-de-editor.md).
