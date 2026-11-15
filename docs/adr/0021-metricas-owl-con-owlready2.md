# 0021. Métricas OWL con owlready2

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

La ficha de ontología muestra métricas del modelo OWL. Hay que decidir con qué herramienta se calculan y dónde.

## Decisión

El responsable del proyecto ha decidido calcular las métricas con owlready2, en el backend y durante la ingesta, sin Java para las métricas. El perfil OWL resultante es aproximado y la expresividad DL no se calcula.

Alternativa descartada: ROBOT, que necesita Java y calcula perfiles exactos.

## Consecuencias

- Las métricas no añaden una dependencia de Java ni un proceso aparte.
- El perfil OWL que se muestra es una aproximación, no un resultado exacto.
- La expresividad DL no aparece entre las métricas.
- Si en el futuro hacen falta perfiles exactos, habrá que revisar esta decisión con un ADR nuevo.
- Relacionado: [0022](0022-consistencia-con-pellet.md), que sí requiere Java en la imagen del backend.
