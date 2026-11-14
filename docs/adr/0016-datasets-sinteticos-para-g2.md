# 0016. Datasets sintéticos para la puerta G2

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

La puerta G2 exige demostrar el núcleo del catálogo (publicación, versionado y distribuciones). Los datos reales de la unidad, con su licencia, punto de contacto y proyecto, no están disponibles todavía.

## Decisión

El responsable del proyecto ha decidido que la puerta G2 se demuestra con datasets sintéticos. Son los tres del catálogo del prototipo:

- Modbus/TCP del banco de pruebas OT.
- Hallazgos de auditorías y pruebas de intrusión.
- Corpus de ejemplos adversarios en visión.

Los datasets se marcan como sintéticos. Los datos reales, con su licencia, contacto y proyecto reales, llegan en el piloto (fase 5).

## Consecuencias

- El núcleo del catálogo no queda bloqueado a la espera de datos reales.
- Los placeholders como `[LICENCIA]` y `[CONTACTO]` se mantienen hasta el piloto.
- Los datasets llevan una marca de sintético en el RDF.
- En el piloto hay que sustituir los datasets sintéticos por los reales o retirarlos del catálogo.
