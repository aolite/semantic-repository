# 0022. Consistencia con Pellet

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

La ficha de ontología comprueba la consistencia con un razonador. El diseño citaba HermiT, pero el backend usa owlready2 (ADR 0021), que incluye Pellet.

## Decisión

El responsable del proyecto ha decidido comprobar la consistencia con Pellet, a través de owlready2. Esto requiere Java en la imagen del backend. La interfaz muestra el razonador que devuelve la API, no uno fijo.

Las ontologías importadas no se descargan, así que el razonamiento se hace sin ellas.

## Consecuencias

- La imagen del backend incluye Java para el razonador, aunque las métricas no lo necesiten.
- El texto del diseño que cita HermiT deja de ser exacto; la interfaz lo toma de la respuesta de la API.
- El resultado de consistencia no cubre los axiomas de las ontologías importadas.
- Relacionado: [0021](0021-metricas-owl-con-owlready2.md).
