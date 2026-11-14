# 0014. Alcance del Docker Compose de la fase 1

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

`Plan.md` (3.4) menciona un Compose con frontend, API, Fuseki y F-UJI. La puerta G1 solo exige un entorno local listo, y F-UJI pertenece a la fase 4.

## Decisión

El Docker Compose de la fase 1 contiene postgres, Fuseki, backend y frontend (un esqueleto mínimo de Vite con login). F-UJI se integra en la fase 4.

## Consecuencias

- El entorno de G1 es más pequeño y rápido de levantar.
- En la fase 4 hay que añadir F-UJI al Compose y las variables necesarias.
- Cualquier variable de entorno nueva se documenta en `.env.example` con valores ficticios.
