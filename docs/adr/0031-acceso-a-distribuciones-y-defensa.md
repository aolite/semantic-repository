# 0031. Acceso a distribuciones y `NON_PUBLIC` como defensa

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

`Plan.md` dice que el miembro puede solicitar o descargar distribuciones restringidas, y que los datasets restringidos de defensa solo publican metadatos: sus distribuciones se quedan en infraestructura de Eurecat. Hacía falta fijar cómo se traducen esas reglas al `dct:accessRights` de la tabla europea (`PUBLIC`, `RESTRICTED`, `NON_PUBLIC`).

## Decisión

El responsable del proyecto ha decidido (decisión 40 de `Plan.md`):

| `dct:accessRights` | Significado | Descarga |
|---|---|---|
| `PUBLIC` | Abierto | Cualquiera, sin autenticación |
| `RESTRICTED` | Restringido | Usuarios autenticados (miembro o superior), con auditoría |
| `NON_PUBLIC` | Dataset de defensa | Solo metadatos: nunca se sube ni se sirve fichero |

El contrato de la fase 4 lo concreta así:

- La API de una distribución informa de `download`: `open`, `authenticated`, `metadata_only` o `unavailable`.
- La descarga está en `/dataset/{slug}/{version}/{dist}/fichero`. Para `RESTRICTED` pide `Authorization: Bearer` o un enlace firmado de corta vida, que el navegador obtiene con `download-link` sin poner el JWT en la URL.
- La subida de fichero es del editor. Con `NON_PUBLIC` se rechaza con 409.
- Solo las descargas `RESTRICTED` se auditan (propuesta del orquestador, para no llenar la tabla).
- El RDF publicado no cambia al subir ficheros. Tamaño y suma de comprobación van en PostgreSQL y en la API (propuesta del orquestador).

## Consecuencias

- Un anónimo descarga solo `PUBLIC`. Un miembro descarga también `RESTRICTED`.
- El sistema impide subir un fichero de un dataset de defensa, además de no servirlo.
- Las descargas abiertas no dejan rastro de auditoría.
- La clave de almacenamiento es `{slug}/{version}/{dist}`, igual en disco y en R2 ([0008](0008-almacenamiento-disco-y-r2.md)).
- Relacionado: [0011](0011-roles-de-usuario.md), [0017](0017-admin-hereda-permisos-de-editor.md), [0018](0018-access-url-de-distribuciones.md).
