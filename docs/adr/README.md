# Registro de decisiones (ADR)

Cada decisión se guarda en un fichero `NNNN-titulo-corto.md` con las secciones Estado, Fecha, Contexto, Decisión y Consecuencias. Usa `0000-plantilla.md` para crear uno nuevo y añádelo a esta tabla en el mismo cambio. Una decisión que cambia no se edita: se crea un ADR nuevo y el anterior pasa a "Sustituida por NNNN".

[PROPUESTA] Un ADR nuevo matiza a otro, sin sustituirlo, cuando cambia solo una parte acotada de lo decidido y el resto sigue vigente: el ADR matizado conserva el estado "Aceptada" y ambos se enlazan en Consecuencias (caso 0017 → 0011). Si deja de ser cierto lo esencial de la decisión, se sustituye.

| ADR | Título | Estado | Fecha |
|---|---|---|---|
| [0001](0001-formato-registro-decisiones.md) | Formato del registro de decisiones: ADR | Aceptada | 2026-11-14 |
| [0002](0002-subagentes-pr-y-reparto-por-capa.md) | Subagentes, PR con revisión del responsable y reparto por capa técnica | Aceptada | 2026-11-14 |
| [0003](0003-modelos-por-agente.md) | Modelo de Claude para cada agente | Aceptada | 2026-11-14 |
| [0004](0004-stack-react-fastapi.md) | Frontend React y backend FastAPI | Aceptada | 2026-11-14 |
| [0005](0005-github-y-github-actions.md) | Código en GitHub y CI con GitHub Actions | Aceptada | 2026-11-14 |
| [0006](0006-base-uri-configurable.md) | URIs persistentes a partir de `BASE_URI` | Aceptada | 2026-11-14 |
| [0007](0007-postgresql-usuarios-auditoria.md) | PostgreSQL para usuarios y auditoría | Aceptada | 2026-11-14 |
| [0008](0008-almacenamiento-disco-y-r2.md) | Distribuciones: disco en el MVP y Cloudflare R2 en el despliegue | Aceptada | 2026-11-14 |
| [0009](0009-ramas-y-commits.md) | Convención de ramas y commits | Aceptada | 2026-11-14 |
| [0010](0010-alcance-pruebas-seguridad.md) | Alcance de las pruebas de seguridad | Aceptada | 2026-11-14 |
| [0011](0011-roles-de-usuario.md) | Roles de usuario | Aceptada | 2026-11-14 |
| [0012](0012-python-ultima-version-con-uv.md) | Python del backend: última versión estable con uv | Aceptada | 2026-11-14 |
| [0013](0013-herramientas-seguridad-fase-1.md) | Herramientas de seguridad de la fase 1 | Aceptada | 2026-11-14 |
| [0014](0014-alcance-docker-compose-fase-1.md) | Alcance del Docker Compose de la fase 1 | Aceptada | 2026-11-14 |
| [0015](0015-alta-de-usuarios.md) | Alta de usuarios | Aceptada | 2026-11-14 |
| [0016](0016-datasets-sinteticos-para-g2.md) | Datasets sintéticos para la puerta G2 | Aceptada | 2026-11-14 |
| [0017](0017-admin-hereda-permisos-de-editor.md) | El admin hereda los permisos de editor | Aceptada | 2026-11-14 |
| [0018](0018-access-url-de-distribuciones.md) | `dcat:accessURL` de las distribuciones | Aceptada | 2026-11-14 |
| [0019](0019-alcance-ficha-de-dataset-g2.md) | Alcance de la ficha de dataset en G2 | Aceptada | 2026-11-14 |
| [0020](0020-contenido-sintetico-en-fase-3.md) | Contenido sintético en la fase 3 | Aceptada | 2026-11-15 |
| [0021](0021-metricas-owl-con-owlready2.md) | Métricas OWL con owlready2 | Aceptada | 2026-11-15 |
| [0022](0022-consistencia-con-pellet.md) | Consistencia con Pellet | Aceptada | 2026-11-15 |
| [0023](0023-responsable-de-esquema-corporativo-placeholder.md) | Responsable de esquema corporativo como placeholder | Aceptada | 2026-11-15 |
| [0024](0024-vocabularios-corporativos-bajo-base-uri.md) | Vocabularios corporativos bajo `BASE_URI` | Aceptada | 2026-11-15 |
| [0025](0025-publicacion-por-release-de-github.md) | Publicación por Release de GitHub | Aceptada | 2026-11-15 |
