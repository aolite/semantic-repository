# 0007. PostgreSQL para usuarios y auditoría

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

La arquitectura necesita una base de datos relacional pequeña para usuarios y auditoría. El catálogo vive en el triplestore.

## Decisión

El motor es PostgreSQL.

## Consecuencias

- Es un servicio del Docker Compose desde la fase 1 (ver ADR 0014).
- Afecta a `backend` y a `infra`.
- En el despliegue, el alojamiento de PostgreSQL forma parte de la decisión pendiente del proveedor cloud.
