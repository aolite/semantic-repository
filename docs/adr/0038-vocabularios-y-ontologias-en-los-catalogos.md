# 0038. Vocabularios y ontologías en los catálogos, con CRUD completo

## Estado

Aceptada

## Fecha

2026-11-22

## Contexto

La decisión 50 de `Plan.md` extiende a los esquemas SKOS y a las ontologías propias el modelo de catálogos de la decisión 49 ([0037](0037-crud-de-catalogos-y-datasets.md)), antes del despliegue del piloto. El contrato se validó en varias rondas entre el 2026-11-22 y el 2026-11-26.

## Decisión

El responsable del proyecto ha decidido (decisión 50 de `Plan.md`, 2026-11-22):

- Cada esquema SKOS y cada ontología propia pertenece a **un solo** catálogo, como los datasets, y aparece en su ficha.
- CRUD completo desde la aplicación: publicar (esquema o versión de ontología en Turtle o JSON-LD, con SHACL y métricas como hasta ahora), editar metadatos y **dar de baja** con lápida y 410, igual que los datasets. Las versiones de ontología publicadas siguen inmutables ([0027](0027-versiones-inmutables.md)).
- Permisos de editor y admin.
- Accesos: se implementan los botones del prototipo «Publicar recurso» (menú: nuevo catálogo, nuevo dataset, nuevo vocabulario, nueva ontología) e «Importar SKOS» en la pantalla Catálogo.
- Primero se cambia el contrato (SHACL, URIs y datos de ejemplo).

Validado a propuesta de `semantico` (2026-11-22):

- Los esquemas y ontologías sintéticos van a un catálogo nuevo, `{BASE_URI}catalogo/vocabularios-sinteticos` («Vocabularios y ontologías sintéticos de demostración»).
- Los vocabularios corporativos se tratan como los de dominio.
- Las ontologías externas y los esquemas auxiliares (`vocab/dominio`, `vocab/tipo-dataset`) quedan fuera de los catálogos y no se gestionan desde la aplicación.
- La aplicación manda en catálogo, traslados y bajas. La etiqueta de Git (decisión 37) solo versiona y archiva (Release y WIDOCO), sin cargar nada.
- Dar de baja un esquema u ontología que usan recursos vivos da **409**.
- Republicar un esquema sin conceptos que ya estaban da **409**. Un concepto se retira marcándolo `owl:deprecated`, sin perder su URI.

Contrato validado por el responsable (2026-11-25), a propuesta de `semantico` (PR #45):

- El catálogo enlaza sus esquemas y ontologías con `dcat:resource` (pendiente de confirmar contra DCAT-AP 3, decisión 22).
- La pertenencia vive solo en el grafo del catálogo, no en los ficheros de `vocabularios/` ni `ontologias/`.
- Solo el esquema y la ontología llevan lápida. Sus conceptos y versiones responden 410 por arrastre.
- Cuenta como «uso» para el 409 de baja: un concepto que es `dcat:theme` de una versión de dataset vivo, `dct:subject` de una ontología viva o destino de `skos:related` o `*Match` desde otro esquema vivo; y una ontología importada (`owl:imports`) o cuyos términos usa otra ontología viva.
- Publicar un esquema u ontología que ya está en otro catálogo da 409.
- Dar de baja un catálogo con datasets, esquemas u ontologías da 409.
- En `load-semantic`, lo que tiene lápida se omite, los traslados no se deshacen y un recurso nuevo va al catálogo de `data/catalogos/`.
- La descripción del catálogo `vocabularios-sinteticos` es la propuesta.

Decidido también (2026-11-25):

- **Manda la aplicación** también en el contenido de los esquemas: `load-semantic` no quita conceptos añadidos desde la aplicación.
- Un `dcat:theme` nuevo que apunte a un concepto retirado se rechaza, avisando al editor.
- Un concepto retirado indica los que lo sustituyen con `dct:isReplacedBy`.
- Reactivar un concepto retirado es un caso raro y queda fuera del piloto.
- El prefijo VANN de un recurso dado de baja no se reutiliza, como el slug.
- El código de error al intentar gestionar una ontología externa o un esquema auxiliar lo propone `backend` en el OpenAPI.

Validado (2026-11-26), a propuesta de `backend` (PR #46) y `qa` (PR #47):

- Gestionar una ontología externa o un esquema auxiliar desde la API da **403 `not_managed`**. Las ontologías externas solo se pueden sustituir ([0039](0039-sustitucion-de-ontologias-externas-por-versiones.md)).
- Una versión de dataset con un tema retirado da **422 `deprecated_theme`**, con los sustitutos.
- Reactivar un concepto retirado da **409 `concept_reactivated`**.
- Editar un esquema cambia solo los literales en español.
- También bloquean la baja (409 `in_use`): un `dct:subject` hacia el esquema mismo, un `dct:isReplacedBy` desde otro esquema vivo (QA-50-02) y un `dct:conformsTo` de una versión de dataset viva hacia una ontología.
- Un `dcat:theme` hacia un concepto de un esquema dado de baja, o hacia un concepto que no existe, da **422** (QA-50-03).
- Publicar un prefijo VANN que ya usa otro recurso vivo da **409** (QA-50-01).

Decidido también (2026-11-26, tras revisar la aplicación):

- Los prefijos VANN de las ontologías externas **también cuentan**: un esquema u ontología propia no puede usar el prefijo de una externa.
- Se siguen permitiendo los temas externos (conceptos fuera de `BASE_URI`).
- Un `dct:isReplacedBy` dentro del mismo esquema no bloquea su baja, y un recurso no choca con su propio prefijo.
- Se permite `dct:subject` hacia un esquema entero.
- El prefijo que una versión posterior de una ontología deja de usar queda reservado para esa ontología, porque sus versiones antiguas lo siguen declarando (QA-50-06, con lo que QA-50-07 deja de ser un problema).
- Las tarjetas de dataset **no** muestran «Catálogo: X»: al catálogo se llega por la miga de pan.
- La ficha de un catálogo lleva los mismos botones que «Publicar recurso» e «Importar SKOS», con el catálogo ya fijado.
- **Las ontologías externas se sustituyen enteras y cada sustitución genera una versión nueva.** Siguen fuera de los catálogos, sin baja y sin edición campo a campo; el resto de escrituras sigue dando 403 `not_managed`. El modelo de esas versiones lo propuso `semantico` y el responsable lo validó el 2026-11-26 ([0039](0039-sustitucion-de-ontologias-externas-por-versiones.md)).

## Consecuencias

- Detalle del contrato en `semantic/uris.md`.
- Las pantallas de publicación y baja de esquemas y ontologías son propuestas de `frontend`: el prototipo solo dibuja los botones «Publicar recurso» e «Importar SKOS».
- Relacionado: [0037](0037-crud-de-catalogos-y-datasets.md), [0027](0027-versiones-inmutables.md), [0024](0024-vocabularios-corporativos-bajo-base-uri.md), [0025](0025-publicacion-por-release-de-github.md).
