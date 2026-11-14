# 0005. Código en GitHub e integración continua con GitHub Actions

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Hace falta un lugar de alojamiento del código y una herramienta de CI para el pipeline de validación y publicación.

## Decisión

- El código se aloja en GitHub (repositorio `aolite/semantic-repository`). El repositorio es público.
- La CI es GitHub Actions.

## Consecuencias

- Los flujos de CI viven en `.github/workflows/`, responsabilidad de `infra`.
- Al ser público, el repositorio no puede contener secretos, enlaces a documentos internos ni datos restringidos.
- El proveedor cloud del despliegue sigue sin decidir (fase 5) y es independiente de esta decisión.
