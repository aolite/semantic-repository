# Operación

Este documento recoge los procedimientos de operación del entorno local que la fase 4 hace necesarios. La guía completa de operación (arranque, variables de entorno, copias de seguridad, restauración y despliegue) es un entregable de la fase 5 y no está escrita todavía. Para el arranque básico, ver [`infra/README.md`](../infra/README.md).

## Recargar el entorno local desde cero tras la corrección de itot 1.2.0

**Cuándo.** Si tu entorno se cargó con la versión anterior de `semantic/ontologias/itot/1.2.0.ttl`. La corrección añade `IED rdfs:subClassOf ActivoIndustrial` ([ADR 0035](adr/0035-correccion-de-itot-1-2-0.md)). Las versiones son inmutables ([ADR 0027](adr/0027-versiones-inmutables.md)): `load-semantic` sobre un entorno que ya tiene esa versión con otro contenido da 409 `version_immutable`.

**Qué se pierde.** Todo el contenido del entorno local: triplestore, usuarios y auditoría de PostgreSQL y, si borras todos los volúmenes, los ficheros de distribución. Solo es válido para un entorno de desarrollo con datos sintéticos.

Pasos:

1. Para el entorno y borra los volúmenes. `docker compose down -v` borra los tres volúmenes del proyecto: `postgres-data`, `fuseki-data` y `distributions` (ver `infra/README.md`):

   ```bash
   docker compose down -v
   ```

   Si prefieres borrar solo Fuseki y PostgreSQL, el proyecto de Compose se llama `itot`, así que los volúmenes son `itot_fuseki-data` y `itot_postgres-data`. Borra entonces también `itot_distributions`: si PostgreSQL se vacía y el almacenamiento conserva los ficheros, la recarga puede chocar con ficheros ya existentes. Según `backend/app/cli.py`, `load-semantic` compara el SHA-256 de cada fichero sintético con el registro de PostgreSQL solo si ese registro existe; con PostgreSQL vacío no hay registro con el que comparar, así que no detecta ese choque. [PENDIENTE] El comportamiento de `distributions.upload` sobre un fichero que ya está en el almacenamiento sin registro en PostgreSQL no se ha comprobado: lo más seguro es borrar los tres volúmenes a la vez.

2. Levanta el entorno y espera a que todos los servicios estén `healthy`:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

3. Vuelve a crear el primer administrador, porque PostgreSQL se ha vaciado:

   ```bash
   docker compose exec -it backend python -m app.cli create-admin --username <nombre>
   ```

4. Vuelve a cargar los datos de `semantic/`:

   ```bash
   docker compose exec backend python -m app.cli load-semantic
   ```

   El comando no tiene argumentos. Valida todo antes de escribir y, si algo falla, no carga nada (sale con código 1). En la fase 4, además de esquemas, ontologías, catálogo y series:

   - Sube los ficheros sintéticos de distribución de `semantic/data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}` ([ADR 0032](adr/0032-ficheros-de-distribucion-sinteticos.md)) con las mismas reglas que la API: la distribución debe estar descrita en `data/sintetico/`, no puede ser `NON_PUBLIC` y no puede superar `MAX_UPLOAD_MB`. Que falte el fichero de una distribución no es un error.
   - Encola la evaluación FAIR de cada versión nueva de dataset. La evalúa el trabajador de la API, no el comando.
   - Escribe una línea por fichero. Las series muestran, por ejemplo, `evaluación FAIR encolada para N`; los ficheros, `subido` o `sin cambios`.
   - Es idempotente: repetirlo no reescribe lo que no ha cambiado.

5. Comprueba el resultado. Espera unos segundos a que el trabajador FAIR evalúe las versiones (se activa cada `FAIR_WORKER_POLL_SECONDS`, 10 s por defecto) y consulta la API, que es pública:

   ```bash
   # Métricas de itot 1.2.0
   curl -s "http://localhost:8000/ontologies/itot?version=1.2.0"
   # Evaluación FAIR de la versión actual de un dataset (<slug> es el de una serie cargada)
   curl -s "http://localhost:8000/datasets/<slug>"
   ```

   En la primera respuesta, `metrics.classes` debe valer 13, `metrics.logical_axioms` 8 y `consistency.consistent` `true` (el razonador es Pellet). Son las cifras que documenta `semantic/README.md` para esa versión (la corrección de `IED` no las cambia). En la segunda, `version.fair.status` pasa de `pending` o `running` a `done`, y entonces `version.fair.total` lleva la puntuación de F-UJI; si queda en `failed`, mira `docker compose logs fuji backend`. Para pedir una nueva evaluación, `POST /datasets/{slug}/versions/{version}/fair` (rol editor o admin) la encola y responde 202.

## Migrar al usuario `backend` de Fuseki

**Cuándo.** En un entorno ya levantado antes de la fase 4, donde el backend escribe en Fuseki con `admin`. Según el contrato de la fase 4, el backend pasa a usar un usuario propio con permiso de escritura en el dataset, y `admin` queda para administración. Las consultas anónimas de solo lectura no cambian.

Pasos:

1. Añade a `.env` las variables nuevas de `.env.example`: como mínimo `FUSEKI_BACKEND_PASSWORD` (con una contraseña propia), `FUJI_USERNAME` y `FUJI_PASSWORD`. El Compose se detiene con un mensaje si falta alguna. Ni `FUSEKI_BACKEND_PASSWORD` ni `FUSEKI_ADMIN_PASSWORD` pueden contener `,` `=` `\` `#` ni `;`, porque son separadores del formato de `shiro.ini`. `infra/fuseki/entrypoint.sh` genera ese fichero con `awk` (no con `sed`, así que `/` y `&` no dan problemas) y, si encuentra uno de esos caracteres, Fuseki no arranca.
2. El backend debe usar `FUSEKI_USER=backend`. `docker-compose.yml` lo fija con `${FUSEKI_USER:-backend}`: si no defines `FUSEKI_USER`, vale `backend`. Pero si tu `.env` antiguo tiene `FUSEKI_USER=admin`, ese valor gana, y el backend fallaría con 401 porque recibe la contraseña de `FUSEKI_BACKEND_PASSWORD`. Cambia esa línea a `FUSEKI_USER=backend` (o bórrala).
3. Reconstruye y recrea los servicios. Fuseki regenera `shiro.ini` en cada arranque y el backend recibe las nuevas credenciales; además se construye `fuji`:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

4. Comprueba que el backend escribe y que una escritura anónima se rechaza (la petición no escribe nada: inserta cero tripletas). Sustituye `<contraseña>` por `FUSEKI_BACKEND_PASSWORD`:

   ```bash
   # Con el usuario backend: no debe dar 401 ni 403
   curl -s -o /dev/null -w '%{http_code}\n' -u backend:<contraseña> \
     -X POST http://127.0.0.1:3030/itot/update --data-urlencode 'update=INSERT DATA {}'
   # Sin credenciales: debe dar 401
   curl -s -o /dev/null -w '%{http_code}\n' \
     -X POST http://127.0.0.1:3030/itot/update --data-urlencode 'update=INSERT DATA {}'
   ```

   Si has cambiado `FUSEKI_HOST_PORT`, usa ese puerto. Para comprobar también al backend, repite `docker compose exec backend python -m app.cli load-semantic`: debe terminar sin errores del triplestore.

Los datos del volumen `fuseki-data` no se tocan en esta migración: cambia la política de acceso, no el contenido.

## Revisar la excepción de Trivy al caducar

**Cuándo.** El 2027-02-15 caduca la excepción registrada en `.trivyignore.yaml` ([ADR 0030](adr/0030-excepcion-de-trivy-con-caducidad.md)). El fichero se introduce en la PR #24 y esta fase no lo toca. A partir de esa fecha, el CI vuelve a fallar con el hallazgo si no se revisa.

Pasos:

1. Abre `.trivyignore.yaml` y localiza la excepción y su motivo.
2. Comprueba si ya hay una versión corregida del componente afectado.
3. Si la hay, actualiza el componente y borra la excepción.
4. Si no la hay, decide con el responsable del proyecto si se renueva. Una renovación lleva el motivo y una nueva fecha de caducidad, y se hace por PR.
5. Para ejecutar Trivy en local como en CI, construye la imagen del backend y analízala con los mismos parámetros que el job `imagen-backend` de `.github/workflows/ci.yml` (Trivy v0.76.2, severidad `CRITICAL`, fallo con `exit-code 1`, paquetes del sistema y de bibliotecas). Con Docker, sin instalar Trivy:

   ```bash
   docker build -t backend-scan:local backend
   docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.76.2 \
     image --severity CRITICAL --exit-code 1 --pkg-types os,library backend-scan:local
   ```

   [PENDIENTE] Este comando es una traducción de los parámetros del CI, no una orden copiada del repositorio, y no se ha ejecutado. Además, `.trivyignore.yaml` no existe todavía en la integración de la fase 4 (llega con la PR #24), así que este comando no aplica ninguna excepción. Cuando exista, hay que montarlo y pasarlo con `--ignorefile`; `infra` debe confirmar cómo lo lee el job de CI.

## Operación detrás de un proxy inverso

El límite de frecuencia de SPARQL anónimo (`SPARQL_RATE_ANON_PER_MIN`, por IP) y el bloqueo de login (por usuario e IP) usan la IP de la conexión (`request.client.host`) y nunca leen `X-Forwarded-For` por su cuenta. Detrás de un proxy inverso, si uvicorn no confía en el proxy, todas las peticiones llegan con la IP del proxy: todos los clientes comparten el mismo cupo y un solo cliente puede bloquear el login de los demás.

Qué hace hoy el repositorio: `backend/docker-entrypoint.sh` arranca `uvicorn app.main:app --host 0.0.0.0 --port 8000` sin pasar `--forwarded-allow-ips`, y ni `docker-compose.yml` ni `.env.example` mencionan `FORWARDED_ALLOW_IPS`. Según `backend/README.md`, uvicorn solo reescribe la IP con esa cabecera si la conexión viene de una IP de `FORWARDED_ALLOW_IPS` (por defecto `127.0.0.1`).

**Tarea pendiente del despliegue (fase 5):** configurar uvicorn para que confíe en `X-Forwarded-For` solo del proxy, con la variable `FORWARDED_ALLOW_IPS` (o `--forwarded-allow-ips`) apuntando a la IP o red del proxy. No uses `*` si el backend es alcanzable sin pasar por el proxy, porque cualquiera podría falsear su IP. [PENDIENTE] No hay configuración probada en el repositorio: el valor concreto depende del proxy elegido en el despliegue.

## Recursos de Docker

`qa` observó lo siguiente con una máquina virtual de Docker de 4 GB: un stack completo (con F-UJI) funcionaba, pero al levantar dos stacks a la vez Fuseki se reinició. No hay una cifra mínima garantizada. Si ejecutas las pruebas e2e o de pantallas (que levantan su propio Compose) mientras tienes tu entorno de desarrollo arriba, o si Fuseki se reinicia sin motivo aparente (`docker compose ps`, `docker compose logs fuseki`), da más memoria a Docker o para uno de los stacks.
