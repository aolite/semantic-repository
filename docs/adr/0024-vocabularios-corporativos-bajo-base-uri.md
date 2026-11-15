# 0024. Vocabularios corporativos bajo `BASE_URI`

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

El prototipo sugería publicar los vocabularios corporativos en un dominio `/eurecat/` aparte. El ADR 0006 establece que todas las URIs se construyen a partir de `BASE_URI`.

## Decisión

El responsable del proyecto ha decidido publicar los vocabularios corporativos en `{BASE_URI}vocab/corp/{slug}/`, y no en un dominio aparte. Así se mantiene una sola variable y una sola regla de URIs.

Si Eurecat los publica en su propio dominio, se enlazan con `skos:exactMatch`.

## Consecuencias

- No hay una segunda variable de entorno ni una segunda regla de URIs.
- Los vocabularios corporativos siguen el mismo patrón de URIs persistentes que el resto.
- Un eventual dominio propio de Eurecat se resuelve con enlaces, no con cambios en las URIs.
- Relacionado: [0006](0006-base-uri-configurable.md).
