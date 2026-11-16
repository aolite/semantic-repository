# 0036. Nivel FAIR: el que devuelve F-UJI

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Cada dataset muestra una puntuación FAIR calculada con F-UJI (evaluador interno). La ficha puede mostrar además un nivel de madurez, y habría que decidir si el repositorio define sus propios umbrales o usa los del evaluador.

## Decisión

El responsable del proyecto ha decidido (decisión 45 de `Plan.md`) que el nivel FAIR es el nivel de madurez que devuelve F-UJI, sin umbrales propios. El contrato de la fase 4 lo concreta:

- Las puntuaciones (total y por principio F, A, I, R) y el nivel salen solo de la respuesta de F-UJI. No se inventan, no se redondean de otra forma y no se calcula un nivel propio.
- Se guarda el informe completo, el nombre y la versión del evaluador y la URL evaluada. La ficha muestra la última evaluación terminada.
- Un error de F-UJI deja la evaluación como fallida con un mensaje saneado, sin romper la ficha.

### Cómo se evalúa

F-UJI 4.0.1 recibe como `object_identifier` la URL del RDF de la versión bajo `FAIR_TARGET_BASE_URL`, no la URI persistente:

```
{FAIR_TARGET_BASE_URL}datasets/{slug}/rdf?version={v}&format=turtle
```

Esa URL responde Turtle con cualquier `Accept` y se guarda en `fair_evaluations.evaluated_url`.

**Motivo.** Con la URI persistente, F-UJI pide `Accept: text/html, */*` y sigue el 303 hasta la ficha del frontend, que no es alcanzable desde la red interna `fuji-net`. F-UJI solo lee las cabeceras `Link` de la respuesta final, así que no recoge metadatos y la nota baja a 8.33.

**Signposting.** Aun así se añadió, porque es útil: cabeceras `Link` con `cite-as` y `describedby` (Turtle, JSON-LD y RDF/XML) en el 303 y en el RDF de dataset, versión y distribución.

**Informe público.** Al servirlo, la API sustituye la URL evaluada por la URI persistente de la versión y cualquier otra aparición de `FAIR_TARGET_BASE_URL` por `BASE_URI`, de modo que no expone hosts internos. El informe guardado no cambia.

### Puntuaciones medidas en la fase 4

Medición en local con los datos sintéticos, F-UJI 4.0.1 y métricas 0.5. No son un objetivo:

| Versión | Total | Detalle |
|---|---|---|
| modbus-tcp-testbed 2.1.0 | 52.08 | F 35.71, A 100, I 50, R 50; madurez 2.0 |
| hallazgos 1.3.0 y ejemplos 0.9.0 | 52.08 | madurez 1.75 |
| modbus 2.0.0 | 39.58 | F-UJI no encuentra enlaces a datos en sus metadatos |

## Consecuencias

- El nivel cambia si cambia la versión de F-UJI, por eso se guarda el evaluador con cada resultado.
- No hay umbrales que mantener en el repositorio.
- El informe muestra la URI persistente como objeto evaluado aunque F-UJI haya leído su RDF. Es una consecuencia aceptada.
- Relacionado: [0027](0027-versiones-inmutables.md).
