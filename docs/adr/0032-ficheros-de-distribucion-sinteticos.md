# 0032. Ficheros de distribución sintéticos

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Para probar la descarga de distribuciones hacen falta ficheros, y los datasets reales son internos o de proyectos restringidos. Los datos sintéticos de la fase 2 (ADR 0016) describen distribuciones, pero no tienen fichero.

## Decisión

El responsable del proyecto ha decidido (decisión 41 de `Plan.md`) crear ficheros de distribución sintéticos, mínimos y marcados como tales, para los tres datasets de ejemplo. El contrato de la fase 4 lo concreta:

- Un fichero por cada distribución `PUBLIC` o `RESTRICTED`, y ninguno para `NON_PUBLIC`.
- Tamaño máximo de 64 KB, deterministas y regenerables con un script sin red.
- Marcados como sintéticos donde el formato lo permita.
- El tipo de fichero coincide con el `dcat:mediaType` de su distribución.
- No tienen que cuadrar con los tamaños, recuentos o fechas del prototipo, que siguen como placeholder.
- `load-semantic` los sube con la misma lógica que la API.

## Consecuencias

- La descarga y las pruebas de acceso pueden ejecutarse de extremo a extremo sin datos reales.
- Ningún dato real entra en el repositorio, que es público.
- Si ningún dataset sintético tiene una versión `NON_PUBLIC`, no se inventa: `qa` la cubre con datos de prueba.
- Relacionado: [0016](0016-datasets-sinteticos-para-g2.md), [0020](0020-contenido-sintetico-en-fase-3.md), [0031](0031-acceso-a-distribuciones-y-defensa.md).
