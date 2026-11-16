# 0033. SPARQL público de solo lectura con límites

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

El punto único del repositorio incluye un endpoint SPARQL común. Exponer Fuseki directamente permitiría actualizaciones, consultas sin límite de coste y federación hacia servicios externos.

## Decisión

El responsable del proyecto ha decidido (decisión 42 de `Plan.md`) que el SPARQL es público, de solo lectura y pasa por el backend, con límites. Los valores concretos los propuso el orquestador y el responsable los aceptó:

- **Validación previa** con un parser de SPARQL: solo `SELECT`, `ASK`, `CONSTRUCT` y `DESCRIBE`. Las actualizaciones y `SERVICE` dan 400. `FROM` y `FROM NAMED` hacia IRIs que no sean grafos del dataset se rechazan. Una consulta de más de 20 KB da 413.
- **Ejecución** contra el endpoint de solo lectura de Fuseki, con tiempo máximo (`SPARQL_TIMEOUT_SECONDS`, 10 s por defecto; al superarlo, 504) y número máximo de filas o triples (`SPARQL_MAX_ROWS`, 10000 por defecto, con cabecera `X-Result-Truncated: true` si se trunca). Un SELECT que supera además 32 MiB de respuesta procesada (`MAX_RESPONSE_BYTES` en `backend/app/sparql_public.py`) también se trunca y lleva esa cabecera.
- **Frecuencia:** `SPARQL_RATE_ANON_PER_MIN` por IP (30) y `SPARQL_RATE_AUTH_PER_MIN` por usuario (60), con 429 y `Retry-After`. La IP sale de la conexión, no de `X-Forwarded-For`, salvo proxies de confianza configurados.
- **Formatos:** `application/sparql-results+json` y `text/csv` para SELECT y ASK; Turtle y JSON-LD para CONSTRUCT y DESCRIBE.

## Consecuencias

- Cualquiera puede consultar el catálogo sin credenciales, y no puede escribir ni federar.
- El backend es el único punto de acceso al triplestore para consultas, además de para escrituras.
- Una consulta legítima muy pesada puede truncarse o dar 504.
- Los límites se ajustan por variables de entorno.
- Relacionado: [0006](0006-base-uri-configurable.md), [0034](0034-consultas-guardadas.md).
