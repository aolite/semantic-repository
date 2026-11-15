# 0003. Modelo de Claude para cada agente

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Cada subagente puede usar un modelo distinto, con compromiso entre coste y calidad.

## Decisión

| Agente | Modelo |
|---|---|
| Orquestador (sesión principal) | Claude Opus 5.5, elegido al abrir la sesión |
| `semantico`, `backend`, `frontend` | Claude Opus 5.5 (`opus`) |
| `infra`, `docs` | Claude Sonnet 5.5, el último Sonnet (`sonnet`) |
| `qa` | Claude Sonnet 5.5 (`sonnet`); hasta el 2026-11-15, Claude Fable 5.2 (`fable`) |

## Consecuencias

- Las capas con más carga de diseño (modelo de datos, API, interfaz) usan el modelo más capaz.
- El modelo se declara en el campo `model:` de cada `.claude/agents/<nombre>.md`.
- Si cambian los modelos disponibles, se registra un ADR nuevo.

**Nota (2026-11-15):** el responsable cambia el modelo de `qa` de Claude Fable 5.2 a Claude Sonnet 5.5 para consumir menos tokens. El resto de la decisión sigue vigente.
