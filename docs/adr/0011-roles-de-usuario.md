# 0011. Roles de usuario

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

La autenticación es JWT dentro del backend, sin SSO en el MVP. Los flujos de aprobación con varios roles quedan fuera del MVP.

## Decisión

| Rol | Alcance |
|---|---|
| Lector | Anónimo; ve lo público |
| Miembro | Usuario de la unidad; puede solicitar o descargar distribuciones restringidas |
| Editor | Publica y versiona recursos |
| Admin | Gestiona usuarios |

## Consecuencias

- La autorización por rol se aplica en el backend y se prueba (ADR 0010).
- Los usuarios se guardan en PostgreSQL (ADR 0007); su alta se describe en el ADR 0015.
