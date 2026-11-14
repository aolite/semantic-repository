# 0006. URIs persistentes a partir de la variable BASE_URI

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

El dominio real de las URIs persistentes no se conoce hasta el despliegue, pero las URIs deben ser estables y coherentes en todas las capas.

## Decisión

Base genérica y configurable mediante una única variable de entorno, `BASE_URI`, con valor por defecto `https://semantic.example.org/itot/`. Ningún agente escribe el dominio a mano: todas las URIs se construyen a partir de esa variable. El placeholder `[DOMINIO]` del prototipo equivale a `BASE_URI`.

## Consecuencias

- El dominio real se fija al desplegar (fase 5).
- El patrón de URIs es un contrato propiedad de `semantico`, consumido por `backend` y `frontend`.
- Los datos de ejemplo y las pruebas deben funcionar con cualquier valor de `BASE_URI`.
