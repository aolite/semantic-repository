# 0001. Formato del registro de decisiones: ADR

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

`Plan.md` (secciones 5 y 9) dejaba abierto el formato del registro de decisiones (ADR, CHANGELOG u otro). El estado del proyecto debe guardarse en el repositorio para que no dependa de la memoria de una conversación.

## Decisión

El responsable decide usar ADR (Architecture Decision Records): un fichero por decisión en `docs/adr/NNNN-titulo-corto.md`, con las secciones Estado, Fecha, Contexto, Decisión y Consecuencias. Hay un índice en `docs/adr/README.md` y una plantilla en `docs/adr/0000-plantilla.md`.

## Consecuencias

- Cada decisión nueva se registra en su propio fichero, con numeración correlativa.
- Una decisión que cambia no se reescribe: se crea un ADR nuevo y el anterior pasa a "Sustituida por NNNN".
- El índice se actualiza en el mismo cambio que añade el ADR.
- Cierra el punto abierto del formato en `Plan.md`, que debe actualizarse.
