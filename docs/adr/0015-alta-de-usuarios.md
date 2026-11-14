# 0015. Alta de usuarios

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Hacen falta usuarios con roles (ADR 0011) sin versionar credenciales en un repositorio público.

## Decisión

- El primer admin se crea con un comando CLI del backend. La contraseña la introduce el responsable en local.
- Después, el admin da de alta al resto de usuarios desde la API.
- No se versiona ningún usuario.

## Consecuencias

- No hay usuarios ni contraseñas por defecto en el repositorio, en el Compose ni en los datos de ejemplo.
- La API necesita un endpoint de gestión de usuarios restringido al rol admin.
- La documentación de operación debe describir el comando CLI cuando exista.
