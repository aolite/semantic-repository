# Plan del sistema multi-agente · Repositorio semántico IT&OT

> **Objetivo:** definir los subagentes de Claude Code que construyen el repositorio semántico, qué hace cada uno, cómo se coordinan y cómo se integra su trabajo hasta llegar al MVP.

**Fuentes de este plan**

- **Plan de implementación** (documento interno).
- **Diseño**: prototipo de 6 pantallas (documento interno).
- Los enlaces a los documentos internos no se publican en este repositorio. Están en `CLAUDE.local.md`, un fichero local que no se versiona (ver `CLAUDE.md`).
- Decisiones tomadas por el responsable del proyecto el 2026-11-14:
  - El sistema multi-agente se compone solo de **subagentes de Claude Code**.
  - Los agentes trabajan en ramas y abren **PR**. El responsable revisa, hace el merge y valida las puertas G1 a G4.
  - El **reparto es por capa técnica**.
  - La arquitectura es **frontend en React y backend en FastAPI**.
  - El código se aloja en **GitHub**: <https://github.com/aolite/semantic-repository.git>.
  - El proveedor cloud **no está decidido**.

Todo lo que no sale de estas fuentes va marcado como **[PROPUESTA]**, si es una sugerencia de este plan, o como **[ABIERTO]**, si es una decisión pendiente. Ambos se recogen en la sección 9.

---

## 1. Contexto del producto (resumen de las fuentes)

| Aspecto | Qué dicen las fuentes |
|---|---|
| Propósito | Punto único donde la Unidad IT&OT Security publica, describe y enlaza datasets, ontologías y vocabularios controlados, con endpoint SPARQL común y puntuación FAIR por dataset |
| Alcance MVP | Datasets en DCAT-AP 3; ontologías propias y externas con métricas; SKOS de dominio y corporativos; procedencia PROV-O; versionado; evaluación FAIR automática |
| Fuera del MVP | Edición colaborativa de ontologías en la herramienta; flujos de aprobación con varios roles; federación con catálogos externos |
| Equipo | Una persona (el responsable) con asistentes de IA; dedicación supuesta de un día a la semana, **pendiente de confirmar** |
| Duración | Unas 16 semanas, en 5 fases separadas por 4 puertas |
| Entorno | Desarrollo local con Docker Compose; el proveedor cloud se decide en el piloto, y Cloudflare es una opción que hay que evaluar |
| Código | Repositorio en GitHub: <https://github.com/aolite/semantic-repository.git> |
| Autenticación | JWT dentro del backend, sin SSO en el MVP |

### Arquitectura de referencia

```
Equipo IT/OT (navegador, SPARQL)        Autenticación JWT en la API
                │                                   │
        Frontend web: las 6 pantallas del prototipo (React)
                │
        API backend propia (Python, FastAPI)
        catálogo DCAT-AP · versionado · control de acceso · orquestación FAIR · métricas OWL
        │              │                  │                     │
   Triplestore     Evaluador FAIR     Distribuciones         Ingesta
   Fuseki          F-UJI (servicio)   disco (MVP) / R2,      validación SHACL,
   (GraphDB si     puntuación por     acceso por rol         carga al triplestore
   hace falta)     versión                                   ▲
                                                             │
        Repositorio Git de ontologías y vocabularios (cada etiqueta de versión
        dispara validación, documentación y publicación)
```

Hay dos reglas de arquitectura que todos los agentes deben respetar:

1. **Solo el backend escribe** en el triplestore y en el almacén, de modo que versionado, permisos y FAIR pasan siempre por el mismo punto.
2. Las ontologías y los vocabularios **viven en Git**, y el catálogo solo publica versiones etiquetadas.

Además, la arquitectura incluye una base de datos relacional pequeña para usuarios y auditoría: **PostgreSQL**.

### Decisiones técnicas de la fase 1 (responsable, 2026-11-14)

| Tema | Decisión |
|---|---|
| CI | GitHub Actions |
| URIs persistentes | Base genérica y configurable mediante una única variable de entorno (`BASE_URI`, valor por defecto `https://semantic.example.org/itot/`). Ningún agente escribe el dominio a mano: todas las URIs se construyen a partir de esa variable. El placeholder `[DOMINIO]` del prototipo equivale a `BASE_URI` |
| Frontend | React + TypeScript + Vite + React Router + Vitest |
| Base de datos de usuarios y auditoría | PostgreSQL |
| Almacenamiento de distribuciones | **MVP:** disco de la máquina (un volumen de Docker). **Despliegue:** Cloudflare R2, compatible con S3, cuando se configure. El backend accede a través de una interfaz de almacenamiento con dos implementaciones, disco y R2, y se elige una u otra por configuración, sin cambiar el código |
| Ramas y commits | Ramas `<agente>/<descripción-corta>`; mensajes en formato Conventional Commits |
| Pruebas de seguridad (`qa`) | JWT, autorización por rol, acceso a distribuciones restringidas, inyección en consultas SPARQL y análisis de dependencias |
| Roles de usuario | **Lector:** anónimo, ve lo público. **Miembro:** usuario de la unidad, puede solicitar o descargar distribuciones restringidas. **Editor:** publica y versiona recursos. **Admin:** gestiona usuarios |
| Python del backend | La última versión estable, gestionada con uv (hoy 3.15), fijada en `backend/.python-version` y en la imagen Docker |

### Pantallas del prototipo (contrato de la interfaz)

| Pantalla | Fichero del diseño | Contenido clave |
|---|---|---|
| Catálogo | `Main.dc.html` | Búsqueda; filtros por dominio (Seguridad IT, OT/ICS, PQC e identidad, IA adversaria) y por tipo (Datasets / Vocabularios y ontologías); tarjetas con tipo RDF, acceso, formatos y FAIR |
| Ficha de dataset | `Dataset.dc.html` | Descripción; versionado (`dcat:version`, `adms:versionNotes`, historial); distribuciones; procedencia PROV-O; RDF en Turtle o JSON-LD; FAIR global con desglose F/A/I/R; metadatos DCAT-AP |
| Vocabularios y ontologías | `Vocabularios.dc.html` | Ontologías propias, ontologías externas, SKOS corporativos y SKOS de dominio, con estado (Publicada / Borrador / Referenciada) |
| Ficha de ontología | `Ontologia.dc.html` | Métricas (clases, propiedades, individuos, axiomas, imports); perfil OWL; consistencia con HermiT; imports y alineamientos; versionado (`owl:versionIRI`); uso en el catálogo; metadatos VANN |
| Navegador SKOS | `Skos.dc.html` | Árbol de esquemas y conceptos; prefLabel y altLabel por idioma; broader y related; mapeos externos; recursos que usan el concepto |
| Consola SPARQL | `Sparql.dc.html` | Consultas guardadas, editor, ejecución, resultados en tabla, JSON o CSV |

---

## 2. Principios del sistema multi-agente

1. **El responsable del proyecto es quien decide.** Ningún agente hace merge, despliega en cloud ni cierra una puerta.
2. **Una sesión principal de Claude Code orquesta** y los subagentes especializados ejecutan. Claude Code sí permite que un subagente lance otros, pero aquí se desactiva: ningún subagente tiene la herramienta `Agent` en su lista `tools`, así que solo la sesión principal delega.
3. **Cada capa tiene un dueño.** Cada agente modifica solo su zona de ficheros. Lo que cruza capas, como el contrato de la API o las formas SHACL, se acuerda mediante un artefacto compartido versionado.
4. **Todo cambio entra por PR,** con descripción, pruebas y referencia a la fase.
5. **La documentación se escribe junto al código** (es una mitigación del riesgo "dependencia de una sola persona"), para que nada dependa de la memoria de una conversación.
6. **No se inventan datos.** Los placeholders del prototipo (`[LICENCIA]`, `[CONTACTO]`, `[FECHA]`, `[PROYECTO]`, `[VERSIÓN]`, `[QID]`…) se mantienen como tales hasta que el responsable aporte el valor real.

---

## 3. Agentes

Son siete roles: la sesión principal (orquestador) y seis subagentes por capa técnica.

### 3.0 Orquestador (sesión principal de Claude Code)

- **Responsabilidad:** traducir la fase en curso a tareas, delegar cada tarea al subagente de su capa, integrar resultados, preparar las PR y el informe de cada puerta.
- **No hace:** implementar dentro de una capa cuando hay un subagente responsable de ella.
- **Entradas:** este Plan.md, el plan de implementación, el diseño y el estado del repositorio.
- **Salidas:** tareas delegadas, PR abiertas y el checklist de la puerta.

### 3.1 `frontend` · Frontend React

- **Zona [PROPUESTA]:** `frontend/`
- **Responsabilidad:** implementar las 6 pantallas del prototipo en React, fieles al diseño (paleta, tipografía, navegación lateral, accesibilidad: botones reales, `aria-*`, objetivos táctiles de 44 px o más, adaptación a móvil). Consume la API mediante el contrato OpenAPI y gestiona el login JWT desde el cliente.
- **Depende de:** el contrato de API publicado por `backend`.
- **Stack:** TypeScript, Vite, React Router y Vitest. La librería de estado sigue [ABIERTO].

### 3.2 `backend` · API FastAPI

- **Zona [PROPUESTA]:** `backend/`
- **Responsabilidad:** la API del diagrama: catálogo DCAT-AP, versionado (series y versiones DCAT 3, PROV-O), control de acceso con JWT, distribuciones con acceso por rol (en disco durante el MVP o en Cloudflare R2 en el despliegue, a través de la interfaz de almacenamiento), orquestación de F-UJI en cada publicación de versión, cálculo de métricas OWL en la ingesta (ROBOT u owlready2, consistencia con Pellet), proxy o exposición del endpoint SPARQL y negociación de contenido HTML/Turtle/JSON-LD sobre las URIs persistentes.
- **Garantiza:** es el único componente que escribe en el triplestore y en el almacén.
- **Publica:** el contrato OpenAPI que consume `frontend`.

### 3.3 `semantico` · Modelo de datos y estándares

- **Zona [PROPUESTA]:** `semantic/`, con formas SHACL, ontologías propias, esquemas SKOS y consultas SPARQL de referencia.
- **Responsabilidad:**
  - Formas SHACL que codifican DCAT-AP 3 y las reglas propias de la unidad.
  - Ontologías propias como `owl:Ontology` con `owl:versionIRI`, `owl:priorVersion` y VANN; las externas, solo por referencia.
  - Esquemas SKOS de dominio y corporativos con etiquetas en es, ca y en y mapeos `skos:exactMatch` / `skos:closeMatch` (ATT&CK, CWE, Wikidata, NACE…).
  - Patrón de URIs persistentes (cuando se conozca el dominio).
  - Consultas SPARQL guardadas de la consola.
- **No hace:** inventar conceptos, mapeos o identificadores externos. Los que el prototipo deja como placeholder siguen así hasta que haya fuente.

### 3.4 `infra` · Infraestructura y despliegue

- **Zona [PROPUESTA]:** `infra/`, `docker-compose.yml` y la configuración de CI.
- **Responsabilidad:** el Docker Compose local con frontend, API, Fuseki, F-UJI. El pipeline Git que, ante una etiqueta de versión, valida, documenta y publica; copias de seguridad; en la fase 5, el despliegue en el proveedor elegido y una tarea programada con actividad real (reevaluación FAIR o backup diario) para evitar perdida de datos.
- **No hace:** crear recursos cloud ni gastar dinero sin la aprobación explícita del responsable.

### 3.5 `qa` · Pruebas y verificación

- **Zona [PROPUESTA]:** `tests/` y las pruebas dentro de cada capa.
- **Responsabilidad:** pruebas de la API, validación SHACL de los datos de ejemplo, pruebas de las pantallas frente al prototipo, pruebas de extremo a extremo de cada puerta, **pruebas de seguridad** y revisión de cada PR antes de pasarla al responsable.
- **Es de solo lectura sobre el código de producción:** si encuentra un defecto, lo reporta y no lo corrige.

### 3.6 `docs` · Documentación

- **Zona [PROPUESTA]:** `docs/`
- **Responsabilidad:** documentación de arquitectura, decisiones, operación (entregable de la fase 5), guía de publicación de datasets para el equipo y plantillas de metadatos precargadas (mitigación de los riesgos de adopción y de FAIR bajo).

### Definición en Claude Code

Cada subagente se define en `.claude/agents/<nombre>.md` con frontmatter `name`, `description`, `tools` y, opcionalmente, `model`. El cuerpo del fichero es su system prompt: rol, zona de ficheros, reglas de esta sección y referencia a este plan.

Modelos decididos por el responsable el 2026-11-14:

| Agente | Herramientas [PROPUESTA] | Modelo |
|---|---|---|
| Orquestador (sesión principal) | Todas | Claude Opus 5.5 (se elige al abrir la sesión, no en `.claude/agents/`) |
| `semantico` | Read, Edit, Write, Bash, Grep, Glob | Claude Opus 5.5 (`opus`) |
| `backend` | Read, Edit, Write, Bash, Grep, Glob | Claude Opus 5.5 (`opus`) |
| `frontend` | Read, Edit, Write, Bash, Grep, Glob | Claude Opus 5.5 (`opus`) |
| `infra` | Read, Edit, Write, Bash, Grep, Glob | Claude Sonnet 5.5, el último Sonnet (`sonnet`) |
| `qa` | Read, Edit, Write, Bash, Grep, Glob. Necesita escribir para crear las pruebas; la restricción de no tocar código de producción va en su system prompt, porque `tools` no se puede limitar por ruta | Claude Fable 5.2 (`fable`), para las pruebas y las pruebas de seguridad |
| `docs` | Read, Edit, Write, Grep, Glob | Claude Sonnet 5.5, el último Sonnet (`sonnet`) |

La documentación de Claude Code confirma que el campo `model:` acepta los alias `opus`, `sonnet`, `haiku` y `fable`.

---

## 4. Contratos entre capas

Son los artefactos compartidos que evitan que dos agentes pisen la misma zona.

| Contrato | Dueño | Consumidores |
|---|---|---|
| Especificación OpenAPI de la API | `backend` | `frontend`, `qa`, `docs` |
| Formas SHACL (DCAT-AP 3 y reglas propias) | `semantico` | `backend` (ingesta), `qa` |
| Patrón de URIs persistentes | `semantico` | `backend`, `frontend` |
| Docker Compose y variables de entorno | `infra` | todos |
| Datos de ejemplo del prototipo (dataset Modbus/TCP, ontología itot, esquema SKOS OT…) | `semantico` | `backend`, `frontend`, `qa` |

Cambiar un contrato exige una PR propia, revisada antes que las PR que dependen de ella.

---

## 5. Flujo de trabajo

```
Responsable ──(fase / objetivo)──► Orquestador
                                      │ divide en tareas por capa
             ┌──────────┬─────────────┼───────────┬──────────┐
          frontend   backend      semantico     infra      docs
             └──────────┴─────────────┼───────────┴──────────┘
                                      ▼
                                     qa  (revisa y prueba)
                                      ▼
                         PR en rama ──► Responsable revisa y hace merge
                                      ▼
                           Al final de la fase: demo y puerta
```

1. El responsable fija el objetivo de la sesión (una fase o una parte de ella).
2. El orquestador divide el objetivo en tareas por capa, resuelve primero los cambios de contrato y lanza en paralelo las tareas independientes.
3. Cada subagente trabaja en su rama `<agente>/<descripción-corta>`, con commits en formato Conventional Commits, y deja el código, las pruebas y la documentación de su cambio.
4. `qa` revisa y ejecuta las pruebas, y sus hallazgos vuelven al agente dueño.
5. El orquestador abre la PR con resumen, fase, pruebas ejecutadas y pendientes.
6. El responsable revisa y hace el merge.

Para que el trabajo no dependa de la memoria de una conversación, el estado se guarda en el repositorio: este Plan.md, el registro de decisiones en `docs/` y la descripción de las PR. El formato concreto (ADR, CHANGELOG…) es [ABIERTO].

---

## 6. Fases, puertas y agentes implicados

Las fases y las puertas son las del plan de implementación. Las semanas son orientativas.

| Fase | Semanas | Trabajo (según el plan) | Agentes principales | Puerta |
|---|---|---|---|---|
| 1 · Preparación | 2 | Dominio de las URIs, entorno local con Docker Compose, autenticación JWT con los usuarios de la unidad, repositorio Git, formas SHACL mínimas | `infra`, `backend` (JWT), `semantico` (SHACL, URIs) | **G1** entorno local listo |
| 2 · Núcleo del catálogo | 4 | Triplestore, API, ingesta DCAT-AP; pantallas Catálogo y Ficha de dataset con un primer dataset real | `backend`, `frontend`, `semantico`, `infra` (Fuseki) | **G2** primer dataset publicado |
| 3 · Vocabularios | 4 | Esquemas SKOS de dominio y corporativos; ontologías propias con métricas; flujo de Git a publicación (CI) | `semantico`, `backend` (métricas OWL), `frontend` (Vocabularios, Ficha de ontología, Navegador SKOS), `infra` (CI) | **G3** vocabularios cargados |
| 4 · FAIR y versiones | 3 | F-UJI; series y versiones de dataset; acceso restringido a distribuciones; consola SPARQL con consultas guardadas | `backend`, `infra` (F-UJI, almacenamiento), `frontend` (FAIR, versionado, SPARQL), `semantico` (consultas) | **G4** FAIR y versiones integrados |
| 5 · Piloto y MVP | 3 | Decisión de proveedor y despliegue del mismo Docker Compose; carga de datos reales; uso del equipo durante dos semanas; documentación de operación | `infra`, `docs`, `qa` | Cierre del MVP |

`qa` y `docs` intervienen en todas las fases.

**Checklist de cada puerta**, preparado por el orquestador:

- [ ] Criterio de la puerta demostrado sobre el entorno de trabajo (local hasta el piloto, cloud desde entonces).
- [ ] Pruebas de `qa` en verde.
- [ ] Documentación de la fase actualizada.
- [ ] Ajustes de alcance para la fase siguiente propuestos al responsable.

---

## 7. Reglas que todos los agentes siguen

- No modificar ficheros fuera de su zona salvo indicación del orquestador.
- No hacer merge, push a la rama principal, despliegues cloud ni operaciones con coste.
- No introducir credenciales ni datos restringidos en el repositorio. Los datasets de defensa solo publican metadatos y sus distribuciones se quedan en infraestructura de Eurecat.
- Residencia de datos en la UE como criterio excluyente para cualquier servicio externo.
- Mantener los placeholders del prototipo sin rellenarlos con valores inventados.

---

## 8. Puesta en marcha del sistema

1. ~~Inicializar el repositorio git y enlazarlo con el remoto `https://github.com/aolite/semantic-repository.git`~~. Hecho: rama `main`, remoto `origin`.
2. ~~Crear `CLAUDE.md` con el resumen del proyecto y un enlace a este plan~~. Hecho.
3. ~~Crear las seis definiciones en `.claude/agents/`~~. Hecho.
4. Arrancar la fase 1 con el orquestador.

---

## 9. Decisiones abiertas

Hay que resolverlas antes de la fase o el paso indicado.

| # | Decisión | Afecta a | Cuándo |
|---|---|---|---|
| 1 | ~~Herramienta de CI~~. Decidido: GitHub Actions | `infra` | Cerrada |
| 2 | Dedicación real del responsable (el plan supone un día a la semana) | Calendario | Antes de la fase 1 |
| 3 | ~~Dominio de las URIs~~. Decidido: base genérica configurable con `BASE_URI`. El dominio real se fija al desplegar | `semantico`, `backend` | Cerrada (el valor real, en la fase 5) |
| 4 | ~~Detalles del frontend~~. Decidido: TypeScript, Vite, React Router y Vitest (la librería de estado sigue abierta) | `frontend` | Cerrada |
| 5 | ~~Motor de base de datos~~. Decidido: PostgreSQL | `backend`, `infra` | Cerrada |
| 6 | ~~Almacenamiento de distribuciones~~. Decidido: disco de la máquina en el MVP y Cloudflare R2 en el despliegue, cuando se configure | `infra`, `backend` | Cerrada |
| 7 | ROBOT u owlready2 para las métricas OWL | `backend`, `semantico` | Fase 3 |
| 8 | ~~Modelo de Claude para cada subagente~~. Decidido: ver la tabla de la sección 3 | Coste y calidad | Cerrada |
| 14 | ~~Alcance de las pruebas de seguridad~~. Decidido: JWT, autorización por rol, acceso a distribuciones restringidas, inyección en SPARQL y análisis de dependencias. Las herramientas concretas siguen abiertas | `qa` | Cerrada (herramientas en la fase 1) |
| 9 | ~~Convención de ramas y commits~~. Decidido: `<agente>/<descripción-corta>` y Conventional Commits. El formato del registro de decisiones sigue abierto | Todos | Fase 1 |
| 10 | Primer dataset real para G2 y valores reales de licencia, contacto y proyectos | `semantico`, `backend` | Fase 2 |
| 11 | Responsable nombrado por cada esquema corporativo (mitigación de gobernanza) | `semantico` | Fase 3 |
| 12 | Proveedor cloud. Cloudflare es una opción: las distribuciones ya irán a R2; falta evaluar qué otros componentes pueden alojarse ahí (p. ej. el frontend estático) y cuáles necesitan otro sitio (FastAPI, Fuseki, F-UJI, PostgreSQL) | `infra` | Fase 5 |
| 13 | Papel de ChatGPT Pro y Gemini: el plan de implementación los cita como asistentes, pero este sistema multi-agente se limita a Claude Code | Proceso | Cuando el responsable lo decida |
