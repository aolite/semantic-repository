# 0039. Sustitución de las ontologías externas por versiones

## Estado

Aceptada

## Fecha

2026-11-26

## Contexto

Las ontologías externas quedan fuera de los catálogos y no se gestionan desde la aplicación ([0038](0038-vocabularios-y-ontologias-en-los-catalogos.md)). La decisión 50 de `Plan.md` (punto 8) añade que se pueden sustituir enteras. La decisión 51 fija cómo se guardan esas sustituciones.

## Decisión

El responsable del proyecto ha decidido (decisión 51 de `Plan.md`):

- Las ontologías externas se sustituyen enteras y cada sustitución genera una versión nueva.
- El contrato lo propuso `semantico` en la PR #45 (`semantic/uris.md`, «Versiones de las ontologías externas»): versiones `{BASE_URI}onto/externas/{slug}/{n}`, un grafo por versión con el fichero completo, la última como actual y las anteriores inmutables. El responsable validó sus 9 puntos el 2026-11-26.
- La implementación en `backend`, `frontend` y `qa` va en una tanda aparte, después de fusionar la cadena de la decisión 50. Quedó implementada en las PR #51 (backend), #52 (frontend) y #53 (qa, con axe-core, [0041](0041-accesibilidad-automatica-con-axe-core.md)).

Validado el 2026-11-26, a propuesta de `backend` (PR #51):

- El prefijo VANN que usó cada versión de una externa se guarda en PostgreSQL (tabla `external_version_prefixes`, migración `0005`), como los prefijos dados de baja, para que el que una versión deja de usar siga reservado.
- El grafo de la versión se escribe antes que la referencia y, si la referencia falla, se borra. Si tampoco se puede borrar, queda un grafo huérfano que nadie lista, visible en SPARQL, que la siguiente sustitución sobrescribe.
- Las métricas y la consistencia se calculan sobre el fichero oficial, sin el registro de versión.

## Consecuencias

- Detalle en `semantic/uris.md` y `backend/README.md`.
- Un grafo huérfano es una consecuencia aceptada: es visible en SPARQL, pero no aparece en ningún listado.
- Relacionado: [0027](0027-versiones-inmutables.md), [0038](0038-vocabularios-y-ontologias-en-los-catalogos.md).
