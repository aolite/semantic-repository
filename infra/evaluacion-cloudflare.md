# Evaluación de Cloudflare como proveedor (decisión 12, fase 5)

Estado: **borrador completo**, pendiente de revisión del responsable. Las cifras de Cloudflare (apartados 3 a 5) deben contrastarse con la página original antes de decidir.

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

**Nota sobre las fuentes.** Los datos de este apartado y de los siguientes proceden de las páginas oficiales de Cloudflare citadas, consultadas el 2026-11-16 con una herramienta que resume el contenido. **Las cifras y las afirmaciones hay que contrastarlas con la página original antes de decidir.** Lo que figura como «no documentado» significa que no se ha encontrado en esas páginas; no se completa con suposiciones. Los precios están en USD.

### 3.1 Datos de Cloudflare utilizados

| Producto | Dato | Fuente |
|---|---|---|
| R2 (Standard) | 0,015 USD/GB-mes; operaciones clase A 4,50 USD/millón; clase B 0,36 USD/millón; egress gratis (página actualizada el 2026-10-30) | https://developers.cloudflare.com/r2/pricing/ |
| R2 (capa gratuita) | 10 GB-mes, 1 millón de operaciones clase A y 10 millones de clase B al mes | https://developers.cloudflare.com/r2/pricing/ |
| R2 (jurisdicción) | La jurisdicción `eu` garantiza que los objetos de un bucket se almacenan dentro de esa jurisdicción («guarantee objects in a bucket are stored within a specific jurisdiction»); se fija al crear el bucket y no se puede cambiar; endpoint `https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com`, compatible con S3; Logpush no funciona con buckets con jurisdicción; los *location hints* (`weur`, `eeur`…) son «best effort and not a guarantee» y no valen como garantía | https://developers.cloudflare.com/r2/reference/data-location/ |
| R2 (tamaño de objeto) | Límite de tamaño de objeto frente a `MAX_UPLOAD_MB=512`: [PENDIENTE: verificar] | |
| Workers Static Assets | Plan Free: 100.000 peticiones al día; plan Paid: 5 USD al mes; las peticiones a assets estáticos son «free and unlimited», salvo las que invocan el Worker. Pages no se consultó aparte | https://developers.cloudflare.com/workers/platform/pricing/ (actualizada el 2026-11-13), https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/ |
| Containers (disponibilidad) | GA desde el 2026-04-13 | https://developers.cloudflare.com/changelog/post/2026-04-13-containers-sandbox-ga/ |
| Containers (precio) | Exige Workers Paid (5 USD al mes), que incluye 25 GiB-h de memoria, 375 vCPU-min y 200 GB-h de disco al mes. Exceso: 0,0000025 USD/GiB-s de memoria, 0,000020 USD/vCPU-s (CPU activa) y 0,00000007 USD/GB-s de disco. Egress en Europa: 0,025 USD/GB con 1 TB incluido | https://developers.cloudflare.com/containers/pricing/ |
| Containers (instancias) | vCPU / memoria / disco: `lite` 1/16, 256 MiB, 2 GB; `basic` 1/4, 1 GiB, 4 GB; `standard-1` 1/2, 4 GiB, 8 GB; `standard-2` 1, 6 GiB, 12 GB; `standard-3` 2, 8 GiB, 16 GB; `standard-4` 4, 12 GiB, 20 GB | https://developers.cloudflare.com/containers/platform-details/limits/ |
| Containers (disco) | Efímero («All disk is ephemeral by default»). Solo hay snapshots (beta, máximo 20 GB) o FUSE sobre R2, con rendimiento muy inferior | https://developers.cloudflare.com/containers/platform-details/ |
| Containers (siempre encendido) | No garantizado: se paran por inactividad (lo evita `setInactivityTimeout`), al desplegar o al reiniciar el host; no hay duración garantizada | https://developers.cloudflare.com/containers/platform-details/architecture/, https://developers.cloudflare.com/containers/faq/ |
| Containers (región o jurisdicción UE) | No documentada. Arranca en «the nearest location with a pre-fetched image» y puede moverse al reiniciar | https://developers.cloudflare.com/containers/platform-details/architecture/ |
| Containers (red privada) | Red privada entre contenedores: no documentada. Solo se accede a un contenedor por HTTP a través de un Worker o Durable Object | https://developers.cloudflare.com/containers/platform-details/architecture/ |
| D1 | Admite `--jurisdiction=eu`, pero es SQLite, no PostgreSQL | https://developers.cloudflare.com/d1/configuration/data-location/ |
| Hyperdrive | Conecta un PostgreSQL externo, solo desde Workers (no desde contenedores arbitrarios), en los planes Free y Paid. Precio y ubicación de la caché y del *pooling*: no documentados | https://developers.cloudflare.com/hyperdrive/ |
| PostgreSQL gestionado | Cloudflare no ofrece PostgreSQL gestionado propio. Hay integraciones con terceros (PlanetScale, Neon), sin región UE verificada | https://developers.cloudflare.com/hyperdrive/ |
| Zero Trust | Plan Free: 0 USD, hasta 50 usuarios | https://www.cloudflare.com/plans/sase-zero-trust.md |
| Tunnel | Que Tunnel sea gratuito no figura de forma explícita: [PENDIENTE: verificar] | |
| Regional Services / Data Localization Suite | Add-on solo Enterprise y de pago. El TLS y el procesamiento (Cache, WAF, Workers) ocurren solo en la UE; la mitigación DDoS L3/L4 es global. Sin Enterprise no hay forma documentada de limitar a la UE dónde se procesan las peticiones | https://developers.cloudflare.com/data-localization/, https://developers.cloudflare.com/data-localization/regional-services/ |

### 3.2 Encaje por componente

«Residencia UE» se refiere al criterio excluyente de `CLAUDE.md`.

| Componente | ¿Encaja? | Residencia UE | Motivo |
|---|---|---|---|
| Almacenamiento de distribuciones (R2) | Sí, con trabajo pendiente | Sí para el almacenamiento (jurisdicción `eu`, fijada al crear el bucket). El procesamiento de las peticiones no está limitado a la UE sin Enterprise | R2 es compatible con S3 y tiene egress gratis. Falta implementar `R2Storage` (hoy lanza 503, `backend/app/storage.py:140-149`) y decidir cliente y variables: trabajo de `backend`. El límite de tamaño de objeto frente a `MAX_UPLOAD_MB=512` está [PENDIENTE: verificar]. Los *location hints* no sirven como garantía y Logpush no funciona con buckets con jurisdicción |
| Frontend | Sí, con trabajo pendiente | Almacenamiento de los assets: no documentado. Procesamiento en la UE: solo garantizado con Regional Services (Enterprise) | Encaja como Workers Static Assets, pero falta el build de producción (hoy la imagen ejecuta el servidor de desarrollo de Vite, `frontend/Dockerfile:19`). Con datos sintéticos y un frontend estático el impacto de que el procesamiento no esté limitado a la UE es bajo, aunque es una decisión del responsable (apartado 6) |
| Backend FastAPI + trabajador FAIR | No, tal como está documentado | No documentada | Containers: sin región o jurisdicción UE documentada (arranca en la ubicación más cercana con la imagen precargada y puede moverse al reiniciar); sin «siempre encendido» garantizado, y el backend tiene un hilo permanente (`backend/app/fair.py:479`); sin red privada directa documentada (solo HTTP vía Worker o Durable Object, mientras el backend habla con Postgres, Fuseki y F-UJI por red interna). Las instancias cubren su memoria en tamaño (SHACL 2048 MB y Pellet 1024 MB por ejecución, `backend/app/config.py:63,67`), pero eso no resuelve lo anterior |
| F-UJI | No, tal como está documentado | No documentada | Mismos motivos que el backend. Además, `fuji-net` es una red interna sin salida (`docker-compose.yml:151-155`) y no hay red privada documentada. La imagen es `linux/amd64` con Chromium (`infra/fuji/Dockerfile`); que Containers la admita no se ha verificado |
| Fuseki | No | No documentada | El disco de Containers es efímero y Fuseki guarda el TDB2 en un volumen (`docker-compose.yml:47`). Solo hay snapshots (beta, máximo 20 GB) o FUSE sobre R2, con rendimiento muy inferior. Tampoco hay red privada ni región UE documentadas |
| PostgreSQL | No hay equivalente nativo | D1: sí (`eu`), pero es SQLite. Hyperdrive: no documentado dónde hace la caché y el *pooling* | Cloudflare no ofrece PostgreSQL gestionado propio. D1 es SQLite y el backend usa PostgreSQL (`.env.example:12`); migrar sería un cambio de capa. Hyperdrive solo conecta un PostgreSQL externo y solo desde Workers, no desde contenedores arbitrarios |
| Exposición del backend (Tunnel) y acceso (Access) | Sí, a falta de verificar el coste de Tunnel | Procesamiento en la UE: solo con Regional Services (Enterprise) | Zero Trust Free cuesta 0 USD hasta 50 usuarios. Tunnel gratuito: [PENDIENTE: verificar] |

Conclusión del apartado: con la documentación consultada, solo R2 con jurisdicción `eu` y, con las salvedades indicadas, el frontend estático encajan en Cloudflare. Backend, F-UJI, Fuseki y PostgreSQL no encajan.

## 4. Opciones de arquitectura

El proveedor de la máquina virtual en la UE **no está elegido** y no se propone ninguno: es decisión del responsable.

**Decisión 47 y F-UJI.** El encargo indica que, según la decisión 47, F-UJI evalúa por la red interna y sigue sin internet. Esa decisión no figura en `Plan.md` ni en `docs/` en esta rama; se cita tal como se recibió. Implicación: en las opciones B y C F-UJI se mantiene en `fuji-net` (`internal: true`) con `FAIR_TARGET_BASE_URL` apuntando al backend por la red interna (`.env.example:36-38`), de modo que no se abre salida a internet y no se aplican las consultas externas de `infra/README.md:117-136`. Si se quisiera evaluar la `BASE_URI` pública, habría que quitar `internal: true` y decidir sobre esas llamadas.

### A) Todo en Cloudflare: descartada

- Frontend en Static Assets, backend y F-UJI en Containers, Fuseki y PostgreSQL sin soporte equivalente.
- Motivos: Fuseki no cabe por el disco efímero de Containers; PostgreSQL no tiene equivalente nativo (D1 es SQLite, Hyperdrive solo conecta uno externo y solo desde Workers); backend y F-UJI en Containers no tienen región UE documentada, ni «siempre encendido» garantizado, ni red privada directa documentada, así que no cumplen el criterio excluyente tal como está documentado.
- Solo Containers aparecería en el coste de esta opción (apartado 5).

### B) Híbrida

- El Docker Compose actual en una máquina virtual en la UE (proveedor sin elegir).
- R2 con jurisdicción `eu` para las distribuciones (`STORAGE_BACKEND=r2`).
- Frontend en Workers Static Assets.
- Tunnel para exponer el backend sin abrir puertos en la máquina virtual.

### C) Mínima

- La máquina virtual en la UE con todos los servicios, incluido el frontend.
- Solo R2 con jurisdicción `eu` de Cloudflare, para las distribuciones.

### Trabajo que exige cada opción

| Trabajo | A | B | C |
|---|---|---|---|
| `R2Storage` (cliente y variables de credenciales, hoy sin implementar) | Sí (`backend`) | Sí (`backend`) | Sí (`backend`) |
| Build de producción del frontend (hoy solo servidor de desarrollo de Vite) | Sí (`frontend`, `infra`) | Sí (`frontend`, `infra`): `vite build` y publicación como assets | Sí si se sirve desde la máquina virtual (`frontend`, `infra`: imagen o servidor estático); el servidor de desarrollo de Vite no es una configuración de producción |
| `FORWARDED_ALLOW_IPS` (hoy fuera de `.env.example` y Compose) | No evaluado | Sí: con Tunnel el backend recibe las conexiones desde el agente del túnel; hay que fijar las IP de confianza para el límite de SPARQL y el bloqueo de login (`backend/README.md:343`) | Sí, si hay un proxy inverso delante; si no, se deja el valor por defecto |
| Copias de seguridad (Fuseki, PostgreSQL, distribuciones; hoy inexistentes) | Sin solución documentada para Fuseki y PostgreSQL | Sí: en la máquina virtual para Fuseki y PostgreSQL; las distribuciones están en R2 | Sí: igual que B |
| Límites de memoria (hoy sin cifra en ningún servicio) | Necesario para elegir instancia de Containers | Necesario para dimensionar la máquina virtual | Necesario para dimensionar la máquina virtual |
| Dominio y `BASE_URI` | Sí | Sí: apuntará al frontend y al backend según el reparto | Sí |
| Cuenta y aprobación de costes en Cloudflare | Sí | Sí | Sí (R2) |

Otros puntos: en B y C hay que añadir las variables de R2 a `.env.example`, lo que afecta a todas las capas (aviso para el orquestador). En B hay que decidir cómo llega `VITE_API_BASE_URL` al build estático, porque se resuelve en el navegador (`.env.example:80-83`). Una tarea programada con actividad real (`Plan.md:142`) solo es necesaria si el proveedor de la máquina virtual pausa máquinas inactivas.

## 5. Coste estimado

Solo la parte de Cloudflare, para la evaluación con datos sintéticos (unos pocos GB y poco tráfico). Las cifras proceden del apartado 3.1 y hay que contrastarlas con la página original.

| Concepto | Opciones B y C | Opción A |
|---|---|---|
| R2 | Unos pocos GB caben en la capa gratuita (10 GB-mes, 1 millón de operaciones clase A y 10 millones de clase B al mes). Fuera de la capa: 0,015 USD/GB-mes; egress gratis | Igual |
| Workers Static Assets (frontend) | Plan Free: 100.000 peticiones al día; las de assets estáticos son «free and unlimited», salvo las que invocan el Worker. Con poco tráfico, 0 USD | Igual, más Workers Paid |
| Zero Trust (Access) | Plan Free: 0 USD, hasta 50 usuarios | Igual |
| Tunnel | [PENDIENTE: verificar] (no figura de forma explícita como gratuito) | No aplica |
| Containers | No se usa | Exige Workers Paid (5 USD al mes) más el uso por encima de lo incluido (25 GiB-h de memoria, 375 vCPU-min y 200 GB-h de disco al mes). Descartada por encaje, no por coste; no se calcula |
| Regional Services (Enterprise) | No incluido; precio no documentado en lo consultado | Igual |
| Máquina virtual en la UE | [PENDIENTE: proveedor sin elegir] | No aplica |

Estimación para B y C: probablemente 0 USD en Cloudflare, siempre que se mantenga dentro de las capas gratuitas y esté verificado el coste de Tunnel (opción B). Es una estimación, no una comprobación; no se ha creado ninguna cuenta ni se ha ejecutado ninguna operación.

## 6. Riesgos y preguntas para el responsable

Preguntas:

1. **Proveedor de la máquina virtual en la UE.** Hace falta elegirlo para las opciones B y C. Debe cumplir la residencia en la UE y declarar el coste. Hasta entonces el coste de la máquina virtual es [PENDIENTE: proveedor sin elegir].
2. **Alcance de la residencia.** ¿Basta la jurisdicción de almacenamiento (R2 `eu`) o se exige también que el procesamiento ocurra en la UE? Lo segundo exige Regional Services (add-on Enterprise de pago); sin Enterprise no hay forma documentada de limitarlo. Con datos sintéticos y un frontend estático el impacto es bajo, pero con datos reales habría que volver a decidirlo. Los datos de defensa quedan fuera siempre.
3. **Dominio y `BASE_URI`.** Qué dominio se usa y si lo gestiona Cloudflare. Hasta entonces `BASE_URI` mantiene el valor de `.env.example`.
4. **Cuenta y costes.** Quién crea la cuenta de Cloudflare, quién aprueba los costes y quién custodia las credenciales de R2 y del túnel (secrets de GitHub Actions o variables de entorno; nunca en ficheros).
5. **Decisión 47.** Confirmar que F-UJI evalúa por la red interna y sin internet en el despliegue.

Riesgos:

- **Cifras no contrastadas.** Los datos se leyeron con una herramienta que resume; hay que contrastarlos con la página original antes de decidir.
- **Verificaciones pendientes.** Límite de tamaño de objeto de R2 frente a `MAX_UPLOAD_MB=512` ([PENDIENTE: verificar]); gratuidad de Tunnel ([PENDIENTE: verificar]); Pages no se consultó.
- **Caducidad de la clase Container el 2026-12-31.** Solo aparece citada en un resultado de búsqueda sobre https://blog.cloudflare.com/faster-agent-sandboxes/ y no está verificada. Afecta solo a la opción A, que está descartada.
- **Trabajo de otras capas sin hacer.** `R2Storage` (`backend`) y el build de producción del frontend (`frontend`, `infra`) son requisitos previos de B y C.
- **Sin copias de seguridad ni límites de memoria.** Hoy no existen en el repositorio; son requisito del despliegue en cualquier opción.
- **Los *location hints* de R2 no son garantía.** Solo vale la jurisdicción `eu`, que no se puede cambiar después de crear el bucket; un bucket creado sin ella obliga a crear otro y migrar.
- **Logpush no funciona con buckets con jurisdicción.** Los registros de acceso a R2 no podrán enviarse por esa vía.
- **Dependencia del proveedor.** Mitigada porque R2 es compatible con S3 y el acceso va por la interfaz `Storage` elegida por configuración (`backend/app/storage.py:70-81`).
