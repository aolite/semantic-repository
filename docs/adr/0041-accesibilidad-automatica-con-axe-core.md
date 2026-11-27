# 0041. Accesibilidad automática con axe-core en Playwright

## Estado

Aceptada

## Fecha

2026-11-26

## Contexto

Las pruebas de pantallas usan Playwright ([0029](0029-playwright-para-pruebas-de-pantallas.md)). La decisión 53 de `Plan.md` añade una comprobación automática de accesibilidad.

## Decisión

El responsable del proyecto ha decidido (decisión 53 de `Plan.md`):

- Se añade `@axe-core/playwright`, con la versión fijada, como dependencia de las pruebas de navegador.
- Se incorpora en la tanda de la decisión 51 ([0039](0039-sustitucion-de-ontologias-externas-por-versiones.md)).

## Consecuencias

- Nueva dependencia de desarrollo de las pruebas de navegador, de la que se encarga `qa`.
- Relacionado: [0029](0029-playwright-para-pruebas-de-pantallas.md).
