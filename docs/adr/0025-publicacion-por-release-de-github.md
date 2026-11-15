# 0025. Publicación por Release de GitHub

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Las ontologías y los vocabularios necesitan un modo de publicar versiones con su RDF y su documentación. El CI es GitHub Actions (ADR 0005).

## Decisión

El responsable del proyecto ha decidido publicar por Release de GitHub. Al empujar una etiqueta con uno de estos formatos:

- `onto/{slug}/v{version}`
- `vocab/{slug}/v{version}`
- `vocab/corp/{slug}/v{version}`

el CI valida con SHACL, genera la documentación y adjunta el RDF y la documentación a una Release. La documentación de las ontologías la genera WIDOCO; la de los esquemas SKOS, una página HTML sencilla que genera el pipeline con rdflib.

La carga en un entorno se hace con `load-semantic`. El despliegue automático llega en la fase 5.

## Consecuencias

- Cada versión publicada queda como Release con sus artefactos.
- El CI incorpora WIDOCO para las ontologías, que necesita Java en el runner. Los esquemas SKOS no pasan por WIDOCO.
- La Release no despliega nada: cargar el contenido en un entorno es un paso manual con `load-semantic` hasta la fase 5.
- Relacionado: [0005](0005-github-y-github-actions.md).
