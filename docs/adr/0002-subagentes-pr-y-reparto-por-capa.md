# 0002. Subagentes de Claude Code, PR con revisión del responsable y reparto por capa técnica

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

El proyecto lo lleva una persona (el responsable) con asistentes de IA. Hace falta un sistema de trabajo que mantenga el control humano y evite que dos agentes modifiquen la misma zona.

## Decisión

- El sistema multi-agente se compone solo de subagentes de Claude Code. Una sesión principal (orquestador) delega; ningún subagente tiene la herramienta `Agent`.
- Los agentes trabajan en ramas y abren PR. El responsable revisa, hace el merge y valida las puertas G1 a G4. Antes, `qa` revisa y ejecuta las pruebas.
- El reparto es por capa técnica: `frontend`, `backend`, `semantico`, `infra`, `qa` y `docs`, cada uno con su carpeta.
- Los cambios de contrato entre capas (OpenAPI, SHACL, patrón de URIs, Docker Compose, datos de ejemplo) van en una PR propia, antes de las PR que dependen de ellos.

## Consecuencias

- Ningún agente hace merge, push a `main`, despliegues ni operaciones con coste.
- Cada agente modifica solo su zona; lo que cruza capas se acuerda mediante un artefacto compartido versionado.
- El cuello de botella es la revisión del responsable.
- Las definiciones están en `.claude/agents/`.
