# 0029. Playwright para las pruebas de pantallas

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Vitest cubre componentes, pero no recorre las pantallas en un navegador real contra la API real. La fase 4 añade flujos que lo piden: descarga con sesión, consola SPARQL con consultas guardadas y catálogo con paginación en la URL.

## Decisión

El responsable del proyecto ha decidido (decisión 34 de `Plan.md`) usar Playwright para las pruebas de pantallas. Van en `tests/browser/`, se ejecutan en la e2e y en el CI, sobre el Docker Compose, con Chromium. El contrato de la fase 4 añade que el job de CI sube el informe y las trazas como artefacto solo si falla, con acciones fijadas por commit y permisos mínimos.

## Consecuencias

- Las 6 pantallas y los flujos de G4 se prueban en un navegador real.
- El CI incorpora un job que levanta el Compose, con más tiempo de ejecución.
- Vitest sigue para las pruebas de componentes: Playwright no lo sustituye.
- Relacionado: [0005](0005-github-y-github-actions.md), [0010](0010-alcance-pruebas-seguridad.md).
