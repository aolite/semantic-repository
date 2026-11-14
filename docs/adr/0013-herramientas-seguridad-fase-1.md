# 0013. Herramientas de seguridad de la fase 1

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

El ADR 0010 fijó el alcance de las pruebas de seguridad pero no las herramientas. Residencia de datos en la UE es criterio excluyente para servicios externos.

## Decisión

- Análisis de dependencias: `pip-audit` en el backend y `npm audit` en el frontend, en local y en CI.
- Pruebas propias con pytest para JWT, roles e inyección SPARQL.
- Sin servicios externos de análisis.

## Consecuencias

- No se envía código ni dependencias a terceros.
- La CI incluye ambos análisis de dependencias.
- Si se necesita más cobertura, se registra un ADR nuevo.
