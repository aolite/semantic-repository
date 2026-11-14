# 0004. Arquitectura con frontend React y backend FastAPI

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Hay que fijar el stack de las dos capas principales. `Plan.md` mantiene abierta la librería de estado del frontend.

## Decisión

- Frontend en React con TypeScript, Vite, React Router y Vitest.
- Backend en Python con FastAPI, que publica el contrato OpenAPI que consume el frontend.
- Regla de arquitectura: solo el backend escribe en el triplestore y en el almacenamiento.

## Consecuencias

- El frontend se genera y comprueba frente al contrato OpenAPI del backend.
- La librería de estado del frontend sigue abierta; no se asume ninguna.
- Versionado, permisos y evaluación FAIR pasan siempre por el backend.
