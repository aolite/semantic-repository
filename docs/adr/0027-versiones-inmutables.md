# 0027. Versiones inmutables

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Un dataset o una ontología publicados se citan y se enlazan por la URI de su versión. Si el contenido de una versión puede cambiar después de publicada, esa cita deja de ser fiable, y las evaluaciones FAIR y la procedencia quedan referidas a algo que ya no existe.

## Decisión

El responsable del proyecto ha decidido (decisión 28 de `Plan.md`) que las versiones, de datasets y de ontologías, son inmutables:

- Republicar una versión ya publicada con otro contenido da 409. Con el mismo contenido es idempotente y no escribe nada.
- La comparación es por isomorfismo de grafos: el subgrafo de la versión (sus triples, los de sus distribuciones y su procedencia propia) frente al publicado.
- En datasets, `POST /datasets` sigue recibiendo la serie completa. Cada versión ya publicada debe venir con el mismo contenido: si falta, 409 `version_removed`; si cambia, 409 `version_immutable`. Los metadatos de la serie sí pueden cambiar y las versiones nuevas se añaden.
- En ontologías, si la `owl:versionIRI` ya existe con otro contenido, 409 `version_immutable`.
- Los esquemas SKOS quedan fuera: su versión no forma parte de la URI.
- `load-semantic` aplica las mismas reglas.

## Consecuencias

- Corregir una versión publicada exige publicar una versión nueva.
- Una corrección en los datos de ejemplo de una versión ya cargada choca con esta regla en un entorno existente. Es el caso de itot 1.2.0, que se resuelve recargando el entorno local desde cero ([0035](0035-correccion-de-itot-1-2-0.md)).
- La publicación comprueba el contenido antes de escribir, con el coste de comparar grafos.
- Relacionado: [0016](0016-datasets-sinteticos-para-g2.md), [0025](0025-publicacion-por-release-de-github.md).
