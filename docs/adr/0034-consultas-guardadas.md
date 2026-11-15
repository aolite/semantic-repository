# 0034. Consultas guardadas

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

La consola SPARQL del prototipo ofrece consultas guardadas. Hay dos usos distintos: consultas de ejemplo que sirven a todos y consultas que cada miembro quiere conservar para sí.

## Decisión

El responsable del proyecto ha decidido (decisión 43 de `Plan.md`):

- **De referencia:** viven en `semantic/` (`semantic/consultas/{id}.rq`), son visibles para todos y no se modifican por la API. Llevan el marcador `{BASE_URI}`, que el backend sustituye al servirlas.
- **Personales:** se guardan en PostgreSQL y solo las ve su dueño. Se guarda el texto, no se ejecuta.

El contrato de la fase 4 fija que crear consultas personales es cosa del miembro, que consultar la de otro usuario devuelve 404 para no revelar que existe, y que hay un máximo por usuario (`SAVED_QUERIES_MAX_PER_USER`, propuesta del orquestador). La auditoría registra creación y borrado, nunca el texto de la consulta.

## Consecuencias

- Las consultas de referencia se versionan con el resto del contenido semántico y se prueban contra los datos de `semantic/`.
- Las personales añaden una tabla a PostgreSQL.
- Una consulta personal no se comparte entre usuarios.
- Relacionado: [0033](0033-sparql-publico-con-limites.md), [0007](0007-postgresql-usuarios-auditoria.md).
