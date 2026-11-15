# 0020. Contenido sintético en la fase 3

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

La fase 3 incorpora ontologías y vocabularios controlados. Los reales de la unidad, con sus definiciones, mapeos externos e identificadores, no están disponibles todavía. El ADR 0016 resolvió el mismo problema para los datasets de la puerta G2.

## Decisión

El responsable del proyecto ha decidido que las ontologías y los vocabularios de la fase 3 son sintéticos. Salen de las pantallas del prototipo y se marcan como sintéticos. Las definiciones, los mapeos externos y los identificadores que el prototipo no detalla quedan como placeholder. Los contenidos reales llegan en el piloto.

## Consecuencias

- La fase 3 no queda bloqueada a la espera de contenido real.
- Los recursos llevan una marca de sintético en el RDF.
- Los placeholders se mantienen hasta que el responsable aporte el valor real.
- En el piloto hay que sustituir los recursos sintéticos por los reales o retirarlos del repositorio.
- Nota del 2026-11-15, que matiza esta decisión sin sustituirla: el responsable ha decidido retirar de las ontologías sintéticas todo el contenido que no sale del prototipo. Se retiran los `rdfs:comment` de clases y propiedades, las propiedades de objeto inventadas y el alineamiento concreto con D3FEND. Se mantienen las clases que nombra el prototipo, con etiqueta en español, y las traducciones del nombre al inglés y al catalán como propuesta. Como consecuencia, la cobertura de documentación y las métricas de las ontologías sintéticas son bajas, pero no contienen nada sin fuente.
- Relacionado: [0016](0016-datasets-sinteticos-para-g2.md).
