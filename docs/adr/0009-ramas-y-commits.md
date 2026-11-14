# 0009. Convención de ramas y commits

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Con varios agentes trabajando en paralelo hace falta una convención uniforme para ramas y mensajes de commit.

## Decisión

- Ramas con el formato `<agente>/<descripción-corta>` (por ejemplo, `docs/adr-arquitectura`).
- Mensajes en formato Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`…).

## Consecuencias

- Se ve de un vistazo qué agente es dueño de cada rama.
- El historial es legible y puede automatizarse un CHANGELOG si se decide.
