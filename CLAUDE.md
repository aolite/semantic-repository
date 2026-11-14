# Repositorio semántico IT&OT

Punto único donde la Unidad IT&OT Security publica, describe y enlaza datasets, ontologías y vocabularios controlados, con un endpoint SPARQL común y una puntuación FAIR por dataset.

**`Plan.md` es la referencia del proyecto**: agentes, contratos entre capas, fases, puertas y decisiones abiertas. Léelo antes de planificar o delegar trabajo.

## Documentos internos

El plan se basa en dos documentos internos que no se publican en este repositorio, que es público:

- **Plan de implementación:** alcance, arquitectura, modelo de datos, fases y riesgos.
- **Diseño:** prototipo de las 6 pantallas, que es el contrato de la interfaz.

Sus enlaces y cómo leerlos están en **`CLAUDE.local.md`**, un fichero local que está en `.gitignore`. Si no existe en tu máquina, pídeselo al responsable.

- **Solo la sesión principal (el orquestador) los lee.** Los subagentes no tienen las herramientas para abrirlos: el orquestador extrae lo que necesita cada tarea (textos, campos, estructura de una pantalla) y se lo pasa en el encargo.
- **No copies esos enlaces** a ningún fichero versionado, commit, PR ni issue.

## Stack

- **Frontend:** React + TypeScript + Vite + React Router + Vitest. Implementa las 6 pantallas del prototipo: Catálogo, Ficha de dataset, Vocabularios y ontologías, Ficha de ontología, Navegador SKOS y Consola SPARQL.
- **Backend:** Python + FastAPI. Es el único componente que escribe en el triplestore y en el almacenamiento.
- **Triplestore:** Apache Jena Fuseki (GraphDB Free como alternativa).
- **Evaluador FAIR:** F-UJI, como servicio interno.
- **Usuarios y auditoría:** PostgreSQL.
- **Distribuciones:** disco de la máquina en el MVP; Cloudflare R2 en el despliegue, a través de una interfaz de almacenamiento elegida por configuración.
- **Autenticación:** JWT dentro del backend, sin SSO en el MVP.
- **Entorno:** Docker Compose en local. El proveedor cloud se decide en el piloto (Cloudflare es una opción).
- **CI:** GitHub Actions.

## Estándares

DCAT-AP 3 (con series y versiones de DCAT 3), SKOS, OWL 2 con VANN, PROV-O y SHACL. Toda ingesta se valida con las formas SHACL.

## URIs

Todas las URIs se construyen a partir de la variable de entorno `BASE_URI` (por defecto `https://semantic.example.org/itot/`). Nunca escribas un dominio a mano en el código.

## Agentes

La sesión principal orquesta y delega en los subagentes de `.claude/agents/`, cada uno responsable de su carpeta:

| Agente | Carpeta | Modelo |
|---|---|---|
| `semantico` | `semantic/` | opus |
| `backend` | `backend/` | opus |
| `frontend` | `frontend/` | opus |
| `infra` | `infra/`, `docker-compose.yml`, `.github/workflows/` | sonnet |
| `qa` | `tests/` y pruebas de cada capa | fable |
| `docs` | `docs/` | sonnet |

Cuando una tarea cruza capas, primero se cambia el contrato (OpenAPI, SHACL, patrón de URIs, Docker Compose o datos de ejemplo), en una PR propia, y después las capas que dependen de él.

## Flujo de trabajo

- Ramas con el formato `<agente>/<descripción-corta>`. Commits en formato Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`…).
- Todo cambio entra por PR, que revisa y fusiona el responsable del proyecto. Antes, `qa` revisa y ejecuta las pruebas.
- La documentación se actualiza en el mismo cambio que el código.

## Reglas

- No hagas merge, ni push a `main`, ni despliegues, ni operaciones con coste sin la aprobación explícita del responsable.
- No escribas en ningún fichero del repositorio información privada: contraseñas, tokens, claves, emails o datos personales. Los secretos van en `.env`, que está en `.gitignore`. Para documentar las variables necesarias se usa `.env.example`, con valores ficticios.
- No inventes datos. Los placeholders del prototipo (`[LICENCIA]`, `[CONTACTO]`, `[FECHA]`, `[PROYECTO]`, `[VERSIÓN]`, `[QID]`…) se quedan así hasta que el responsable aporte el valor real.
- Los datasets restringidos de proyectos de defensa solo publican metadatos. Sus distribuciones se quedan en infraestructura de Eurecat.
- Residencia de datos en la UE como criterio excluyente para cualquier servicio externo.
- Si algo no está decidido en `Plan.md`, pregunta al responsable en lugar de suponer.
