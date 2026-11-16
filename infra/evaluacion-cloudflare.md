# Evaluación de Cloudflare como proveedor (decisión 12, fase 5)

Estado: **borrador**. Los apartados 3 a 6 esperan datos verificados con fuentes.

## 1. Objetivo y alcance

- Evaluar si Cloudflare puede alojar el despliegue del repositorio semántico y qué componentes sí y cuáles no (`Plan.md`, decisión abierta 12, línea 287).
- Evaluación **sin coste y solo con datos sintéticos**. No se crean cuentas, no se despliega nada y no se ejecuta ninguna operación con coste.
- Quedan **fuera** los datos reales y los de proyectos de defensa. Estos últimos solo publican metadatos y sus distribuciones se quedan siempre en infraestructura de Eurecat (`CLAUDE.md`, sección Reglas).
- La residencia de datos en la UE es un criterio **excluyente** para cualquier servicio externo (`CLAUDE.md`, sección Reglas).
- Las URIs se construyen siempre desde `BASE_URI`; este documento no fija ningún dominio.

## 2. Inventario de requisitos por componente

Las referencias son `fichero:línea` del repositorio en la rama `main`. Donde el repositorio no da una cifra se indica «sin cifra en el repositorio».

### 2.1 Frontend

| Aspecto | Dato | Fuente |
|---|---|---|
| Imagen y runtime | `node:26.13.0-alpine`; ejecuta el servidor de desarrollo de Vite (`npm run dev --host 0.0.0.0 --port 5173`) | `frontend/Dockerfile:3`, `:19` |
| Producción | **No hay imagen ni build de producción** en el repositorio: la imagen es de desarrollo con recarga en caliente | `frontend/Dockerfile:1`, `infra/README.md:37` |
| Larga duración / segundo plano | Proceso de larga duración (servidor de Vite); sin tareas propias | `frontend/Dockerfile:19` |
| Persistencia | Ninguna | `docker-compose.yml:130-149` (sin `volumes`) |
| Memoria | Sin cifra en el repositorio | `docker-compose.yml:130-149` |
| Puertos y red | 5173 (publicado solo en 127.0.0.1); red por defecto; depende de que el backend esté sano | `docker-compose.yml:137-141` |
| Internet | No lo necesita en ejecución. Es el navegador del usuario quien llama al backend con `VITE_API_BASE_URL` | `.env.example:80-83`, `infra/README.md:52` |
| Variables | `VITE_API_BASE_URL` (URL que usa el navegador), `VITE_BASE_URI` (mismo valor que `BASE_URI`); el frontend no recibe secretos | `docker-compose.yml:133-136`, `.env.example:80-83` |

### 2.2 Backend (API FastAPI) y trabajador FAIR

| Aspecto | Dato | Fuente |
|---|---|---|
| Imagen y runtime | Multietapa: `python:3.15.2-slim` + uv `0.13.6`; dependencias desde `uv.lock`; usuario sin privilegios (uid 10001) | `backend/Dockerfile:4-6`, `:16`, `:32-35` |
| Java | Incluye `openjdk-25-jre-headless` para el razonador Pellet; la imagen pasa de unos 278 MB a 559 MB | `backend/Dockerfile:20-31`, `infra/README.md:72` |
| Arranque | Valida la configuración, aplica `alembic upgrade head` y lanza `uvicorn app.main:app --host 0.0.0.0 --port 8000` (un solo proceso, sin `--workers`) | `backend/docker-entrypoint.sh:12-16` |
| Larga duración | Sí. Es un proceso de larga duración | `backend/docker-entrypoint.sh:16` |
| Segundo plano: trabajador FAIR | Hilo demonio `fair-worker` que arranca en el `lifespan` de la API y consulta las evaluaciones pendientes cada `FAIR_WORKER_POLL_SECONDS` (10 s por defecto; 0 lo desactiva) | `backend/app/main.py:78-89`, `backend/app/fair.py:479`, `:494`, `backend/app/config.py:95-96` |
| Segundo plano: purga de login | **No es una tarea periódica**: `purge_expired` se ejecuta en la petición, al registrar cada fallo de login (un `DELETE`) | `backend/app/login_guard.py:50-56` |
| Segundo plano: procesos auxiliares | La validación SHACL corre en procesos de un *forkserver* de `multiprocessing`, con tiempo (`SHACL_TIMEOUT_SECONDS`, 60) y memoria (`SHACL_MEMORY_MB`, 2048, `RLIMIT_AS`, solo Linux); Pellet corre en una JVM aparte (`REASONER_TIMEOUT_SECONDS` 120, `REASONER_JAVA_MEMORY_MB` 1024) | `backend/app/config.py:59-67`, `backend/README.md:49-51`, `:249` |
| Persistencia | Volumen `distributions` en `/data/distributions` (distribuciones) y `./semantic` montado en `/semantic` solo lectura (formas SHACL y datos de ejemplo). El propio backend no guarda más estado | `docker-compose.yml:107-109` |
| Memoria | Sin límite de contenedor en el repositorio. Cifras de procesos internos: SHACL hasta 2048 MB y Pellet 1024 MB (`-Xmx`) por ejecución | `docker-compose.yml:93-128`, `backend/app/config.py:63`, `:67` |
| Puertos y red | 8000 (127.0.0.1 en el host); redes `default` y `fuji-net`. Habla con PostgreSQL, Fuseki y F-UJI, y recibe las llamadas de F-UJI | `docker-compose.yml:105-122` |
| Internet | No lo necesita en ejecución. Solo habla con servicios internos; con R2 necesitaría salida hacia R2 | `backend/app/config.py:46`, `:89` |
| Depende de | PostgreSQL sano y Fuseki sano; F-UJI es opcional (`required: false`) | `docker-compose.yml:110-119` |
| Detrás de un proxy | La IP del cliente es la de la conexión; `X-Forwarded-For` se ignora. Con un proxy inverso hay que configurar `FORWARDED_ALLOW_IPS` de uvicorn (por defecto `127.0.0.1`). Afecta al límite de frecuencia de SPARQL y al bloqueo de login. No está en `.env.example` ni en Compose | `backend/README.md:343` |
| Variables relevantes para un despliegue | `BASE_URI`, `DATABASE_URL`, `FUSEKI_URL`, `FUSEKI_DATASET`, `FUSEKI_USER`/`FUSEKI_PASSWORD`, `FUJI_URL`, `FUJI_USERNAME`/`FUJI_PASSWORD`, `FUJI_TIMEOUT_SECONDS`, `FAIR_TARGET_BASE_URL`, `FAIR_WORKER_POLL_SECONDS`, `JWT_SECRET` (obligatoria, mínimo 32 bytes con HS256), `CORS_ORIGINS`, `FRONTEND_BASE_URL` (destino de la redirección 303 de las URIs persistentes), `STORAGE_BACKEND`, `STORAGE_DISK_PATH`, `MAX_UPLOAD_MB` (512), `DOWNLOAD_LINK_TTL_SECONDS` (60) | `.env.example:5-83`, `backend/app/config.py:37-108` |

### 2.3 Fuseki (triplestore)

| Aspecto | Dato | Fuente |
|---|---|---|
| Imagen y runtime | `secoresearch/fuseki:6.2.0` (Jena 6.x, multiarquitectura); JVM lanzada con `java -cp "*:/javalibs/*" org.apache.jena.fuseki.main.cmds.FusekiServerCmd` | `docker-compose.yml:32`, `:39`, `:5-8` |
| Larga duración | Sí. Sin tareas en segundo plano definidas en el repositorio | `docker-compose.yml:31-57` |
| Arranque | `infra/fuseki/entrypoint.sh` genera `/fuseki-base/shiro.ini` desde la plantilla con las contraseñas de `FUSEKI_ADMIN_PASSWORD` y `FUSEKI_BACKEND_PASSWORD` y lanza el entrypoint de la imagen | `infra/fuseki/entrypoint.sh:24-34` |
| Persistencia | Volumen `fuseki-data` en `/fuseki-base/databases` (dataset TDB2 `itot`); configuración montada en solo lectura (`assembler.ttl`, plantilla `shiro.ini`, `entrypoint.sh`) | `docker-compose.yml:47-51`, `infra/fuseki/assembler.ttl:21-24` |
| Memoria (JVM) | **Sin cifra en el repositorio**: Compose no define `-Xmx`, `JAVA_OPTIONS` ni `mem_limit` para Fuseki | `docker-compose.yml:31-57` |
| Puertos y red | 3030 (127.0.0.1 en el host); solo red `default`; lo usa el backend | `docker-compose.yml:45-46` |
| Seguridad | Consultas (`/itot/sparql`, `/itot/query`) anónimas; `update`, `data` y `shacl` exigen `backend` o `admin` | `infra/fuseki/assembler.ttl:14-18` |
| Internet | No lo necesita | `docker-compose.yml:31-57` (sin red externa ni variables de URL) |
| Variables | `FUSEKI_ADMIN_PASSWORD` y `FUSEKI_BACKEND_PASSWORD` (sin `,` `=` `\` `#` `;`); del lado del backend, `FUSEKI_URL`, `FUSEKI_DATASET` y `FUSEKI_TIMEOUT_SECONDS` (10 s) | `infra/fuseki/entrypoint.sh:13-20`, `backend/app/config.py:46-50` |

### 2.4 PostgreSQL

| Aspecto | Dato | Fuente |
|---|---|---|
| Imagen y runtime | `postgres:17.6-alpine` | `docker-compose.yml:14` |
| Larga duración | Sí. Sin tareas programadas en el repositorio | `docker-compose.yml:13-29` |
| Persistencia | Volumen `postgres-data` en `/var/lib/postgresql/data`; guarda usuarios, auditoría, bloqueos de login (`login_attempts`), evaluaciones FAIR y consultas guardadas | `docker-compose.yml:22-23`, `backend/app/login_guard.py:3-5` |
| Memoria | Sin cifra en el repositorio | `docker-compose.yml:13-29` |
| Puertos y red | 5432 (127.0.0.1 en el host); solo red `default`; lo usa el backend. El backend aplica las migraciones de Alembic al arrancar | `docker-compose.yml:20-21`, `backend/docker-entrypoint.sh:13` |
| Internet | No lo necesita | `docker-compose.yml:13-29` |
| Variables | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`; el backend usa `DATABASE_URL` con el esquema `postgresql+psycopg` | `.env.example:7-12` |

### 2.5 F-UJI (evaluador FAIR)

| Aspecto | Dato | Fuente |
|---|---|---|
| Imagen y runtime | `ghcr.io/pangaea-data-publisher/fuji` tag 4.0.1 fijada por digest, más Chromium headless (Playwright) instalado en el build. La imagen oficial no arranca sin él | `infra/fuji/Dockerfile:9-15`, `infra/README.md:108` |
| Arquitectura | Solo `linux/amd64` (en arm64 corre emulada) | `docker-compose.yml:70`, `infra/README.md:108` |
| Larga duración | Sí. En el arranque ejecuta `touch` sobre `repodois.yaml` para evitar refrescar la lista de DataCite; arranca Chromium con Playwright | `docker-compose.yml:72-76`, `infra/fuji/Dockerfile:4-7` |
| Persistencia | Ninguna; solo monta `infra/fuji/users.py` en solo lectura | `docker-compose.yml:80-82` |
| Memoria | Sin cifra en el repositorio. El `start_period` del healthcheck es de 60 s | `docker-compose.yml:66-91` |
| Puertos y red | 1071 (API, base `/fuji/api/v1`); **sin puerto en el host**; solo en `fuji-net` (`internal: true`, sin salida a internet) junto al backend. Alcanza al backend en `http://backend:8000/` | `docker-compose.yml:83-84`, `:151-155`, `infra/README.md:112-114` |
| Internet | **No lo tiene ni lo necesita** en la configuración actual. Si se abriera, F-UJI haría consultas externas (Mendeley Data/Elsevier, DataCite, Google, `publicsuffix.org`, GitHub) y algunas no se pueden desactivar por configuración; no se ha verificado la región de esos servidores | `infra/README.md:117-136` |
| Variables | `FUJI_USERNAME`, `FUJI_PASSWORD` (Basic; sin ellas no arranca); del lado del backend `FUJI_URL`, `FUJI_TIMEOUT_SECONDS` (300), `FAIR_TARGET_BASE_URL` (en local `http://backend:8000/`; vacío = `BASE_URI`) | `docker-compose.yml:77-79`, `.env.example:26-38`, `backend/app/config.py:89-96` |
| Detalle a decidir en despliegue | F-UJI necesita llegar a la URL que evalúa. En local es el backend por red interna; en el despliegue habrá que decidir si mantiene `FAIR_TARGET_BASE_URL` interna o evalúa `BASE_URI` pública (lo segundo implica salida a internet) | `.env.example:36-38`, `infra/README.md:136` |

### 2.6 Almacenamiento de distribuciones

| Aspecto | Dato | Fuente |
|---|---|---|
| Interfaz | `Storage` (protocolo) con `save`, `exists`, `size` y `open_stream`; se elige con `STORAGE_BACKEND` (`disk` o `r2`) | `backend/app/storage.py:70-81`, `backend/app/config.py:82` |
| Disco (MVP) | `DiskStorage` sobre `STORAGE_DISK_PATH` (`/data/distributions`), escritura atómica con `fsync` y `os.replace`, lectura en streaming. Claves `{slug}/{version}/{dist}` | `backend/app/storage.py:84-137`, `:12` |
| R2 | **Existe la clase `R2Storage` pero sin implementar**: cada operación lanza `StorageConfigError` (503). Faltan decidir el cliente (p. ej. `boto3`, dependencia nueva) y los nombres de las variables de credenciales. **No hay ninguna variable de R2 en `config.py` ni en `.env.example`** | `backend/app/storage.py:8-10`, `:140-149`, `backend/README.md:322` |
| Descargas | Enlaces firmados con validez `DOWNLOAD_LINK_TTL_SECONDS` (60 s); subida máxima `MAX_UPLOAD_MB` (512) | `.env.example:52-54`, `backend/app/config.py:84-85` |
| Persistencia en Compose | Volumen `distributions` montado en el backend | `docker-compose.yml:108`, `:160` |
| Copias de seguridad | **No hay script ni servicio de copia de seguridad en el repositorio**; `Plan.md` los lista como responsabilidad de `infra` y propone una tarea programada con actividad real en la fase 5 | `Plan.md:142`; contenido de `infra/` |

### 2.7 Resumen de redes, puertos y dependencias

| Origen | Destino | Puerto | Red |
|---|---|---|---|
| Navegador | frontend | 5173 | host |
| Navegador | backend | 8000 | host |
| backend | PostgreSQL | 5432 | `default` |
| backend | Fuseki | 3030 | `default` |
| backend | F-UJI | 1071 | `fuji-net` (interna) |
| F-UJI | backend | 8000 | `fuji-net` (interna) |

Fuentes: `docker-compose.yml:20`, `:45`, `:105`, `:120-122`, `:137`, `:151-155`; `.env.example:16`, `:29`, `:38`. Ningún servicio necesita internet en ejecución con la configuración actual; solo el build (imágenes base, uv, `apt`, Playwright) lo necesita.

### 2.8 Otros datos relevantes

- El backend es el único componente que escribe en el triplestore y en el almacenamiento (`CLAUDE.md`, sección Stack); cualquier despliegue debe mantenerlo así.
- Plan de la fase 5: desplegar el mismo Docker Compose en el proveedor elegido (`Plan.md:229`) y una tarea programada con actividad real para que el proveedor no pause una máquina inactiva (`Plan.md:142`).
- Los límites de memoria de Compose (`mem_limit`, `deploy.resources`) no existen para ningún servicio.

## 3. Encaje en Cloudflare por componente

| Componente | Encaje | Notas |
|---|---|---|
| Frontend | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |
| Backend FastAPI + trabajador FAIR | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |
| Fuseki | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |
| PostgreSQL | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |
| F-UJI | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |
| Almacenamiento de distribuciones (R2) | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |
| Residencia de datos en la UE | [PENDIENTE: datos de Cloudflare] | [PENDIENTE: datos de Cloudflare] |

## 4. Opciones de arquitectura

[PENDIENTE]

## 5. Coste estimado

[PENDIENTE]

## 6. Riesgos y preguntas para el responsable

[PENDIENTE]
