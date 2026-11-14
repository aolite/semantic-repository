# 0012. Python del backend: última versión estable con uv

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

El backend necesita una versión de Python reproducible entre local, CI e imagen Docker.

## Decisión

Se usa la última versión estable de Python, gestionada con uv (hoy 3.15). Se fija en `backend/.python-version` y en la imagen Docker.

## Consecuencias

- Local, CI y Docker usan la misma versión.
- Subir de versión exige actualizar `backend/.python-version` y la imagen Docker en el mismo cambio.
