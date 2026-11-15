# 0035. Corrección de itot 1.2.0

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

La versión 1.2.0 de la ontología `itot` no declaraba que `IED` es subclase de `ActivoIndustrial`. Las versiones son inmutables ([0027](0027-versiones-inmutables.md)), pero 1.2.0 es un dato sintético de ejemplo (ADR 0020).

## Decisión

El responsable del proyecto ha decidido (decisión 44 de `Plan.md`) corregir el fichero `semantic/ontologias/itot/1.2.0.ttl` añadiendo `IED rdfs:subClassOf ActivoIndustrial`, solo en 1.2.0, en lugar de publicar una versión nueva. El contrato de la fase 4 pide revisar que sigue cumpliendo las formas SHACL y es consistente, y que `semantico` informe de las métricas nuevas para actualizar la e2e de G3.

Como contenido ya cargado con otro grafo daría 409, los entornos existentes se recargan desde cero ([operacion.md](../operacion.md)).

## Consecuencias

- Es una excepción acotada a la inmutabilidad, que se acepta porque son datos sintéticos de ejemplo.
- Un entorno cargado con la 1.2.0 anterior no se puede actualizar publicando de nuevo: hay que recrearlo.
- Cambian las métricas de 1.2.0 y `qa` actualiza la e2e de G3.
- Relacionado: [0020](0020-contenido-sintetico-en-fase-3.md), [0021](0021-metricas-owl-con-owlready2.md), [0022](0022-consistencia-con-pellet.md).
