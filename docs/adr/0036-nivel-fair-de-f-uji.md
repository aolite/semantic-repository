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

## Consecuencias

- El nivel cambia si cambia la versión de F-UJI, por eso se guarda el evaluador con cada resultado.
- No hay umbrales que mantener en el repositorio.
- Relacionado: [0027](0027-versiones-inmutables.md).
