# 0010. Alcance de las pruebas de seguridad

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

`qa` incluye pruebas de seguridad. Hay que acotar qué cubren.

## Decisión

Las pruebas de seguridad cubren: JWT, autorización por rol, acceso a distribuciones restringidas, inyección en consultas SPARQL y análisis de dependencias. Las herramientas concretas se decidieron después (ADR 0013).

## Consecuencias

- Cada uno de estos puntos debe tener pruebas automatizadas.
- Lo que quede fuera de este alcance no se considera cubierto.
