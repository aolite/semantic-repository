# Operación del piloto

Guía de operación del piloto (fase 5 de `Plan.md`): preparar el servidor, configurarlo, arrancarlo, actualizarlo, copiarlo y diagnosticarlo.

**Estado.** El despliegue está preparado por `infra` (`docker-compose.prod.yml`, `infra/caddy/`, `infra/frontend/`, `infra/scripts/`) y probado en local con hosts ficticios, pero **todavía no se ha desplegado en ningún servidor**. Los comandos de esta guía son los que recogen [`infra/README.md`](../infra/README.md), «Despliegue del piloto», y los propios ficheros; las partes que nadie ha comprobado en un servidor real están marcadas. Lo que sigue pendiente de decidir está al final.

**Alcance.** El piloto es solo con **datos sintéticos**. Los datos reales irán a una instalación limpia en servidores internos, no a este servidor. Los datasets restringidos de proyectos de defensa solo publican metadatos y sus distribuciones se quedan en infraestructura de Eurecat.

Para el entorno de desarrollo local, ver [`operacion.md`](operacion.md) e [`infra/README.md`](../infra/README.md). Todos los dominios de esta guía son ficticios (`example.org`).

## Cómo se compone el despliegue

El **mismo Docker Compose** del entorno local, con `docker-compose.prod.yml` encima:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
```

| Servicio | Papel en el piloto | Puertos en el host |
|---|---|---|
| `caddy` | Proxy inverso con HTTPS automático (Let's Encrypt) | 80 y 443 (TCP, y 443 UDP para HTTP/3) |
| `frontend` | Build estático de Vite, servido por un Caddy ligero, sin privilegios y de solo lectura | ninguno |
| `backend` | FastAPI; único componente que escribe en Fuseki y en las distribuciones | ninguno |
| `fuseki` | Triplestore; no se expone nunca (el SPARQL público va por el backend) | ninguno |
| `postgres` | Usuarios y auditoría | ninguno |
| `fuji` | Evaluador FAIR, en `fuji-net` con salida a internet | ninguno |

Volúmenes: `postgres-data`, `fuseki-data`, `distributions`, `caddy-data` (certificados y cuenta ACME) y `caddy-config`.

Dos hosts: `FRONTEND_HOST` (la aplicación) y `API_HOST` (la API y las URIs persistentes), porque comparten rutas (`/datasets/{slug}`). La `BASE_URI` del piloto es `https://{API_HOST}/semanticrepository/`. El backend sirve en la raíz; el proxy quita el prefijo `/semanticrepository` en el host de la API, de modo que `https://{API_HOST}/semanticrepository/dataset/x` llega al backend como `/dataset/x`. La API sigue accesible sin prefijo en el mismo host. El 303 de las URIs persistentes apunta a `https://{FRONTEND_HOST}/datasets/...`.

## Requisitos del servidor

- VPS en España, con Linux (Debian o Ubuntu LTS reciente), **4 vCPU, 8 GB de RAM y 240 GB de disco**. Lo contrata el responsable.
- Una IP pública y **dos nombres DNS** (`FRONTEND_HOST` y `API_HOST`) que apunten a ella.
- Puertos 80 y 443 libres.
- Salida a internet: Let's Encrypt, las comprobaciones de F-UJI y la construcción de las imágenes. Los usuarios cargan además `cdn.jsdelivr.net` en `/docs` y `/redoc` (ver «Pendiente de decidir»).
- **Docker Compose 2.24.4 o superior**: `docker-compose.prod.yml` usa las etiquetas `!reset` y `!override`.
- Los volúmenes de Docker y las copias van en el mismo disco. Una copia en la misma máquina no protege de perder el VPS: ver «Pendiente de decidir».

## Preparar el servidor

1. Actualiza el sistema. Instala Docker Engine y el plugin Compose desde el repositorio oficial de Docker. Comprueba con `docker compose version` que es 2.24.4 o superior.
2. Crea un usuario sin root (por ejemplo `itot`), añádelo al grupo `docker` y entra por SSH con clave. Desactiva el acceso SSH de root y por contraseña.
3. Cortafuegos con solo los puertos 22, 80 y 443. Con `ufw`, según `infra/README.md`:

   ```bash
   ufw default deny incoming
   ufw allow 22/tcp
   ufw allow 80/tcp
   ufw allow 443
   ufw enable
   ```

   `ufw allow 443` abre TCP y UDP, y el proxy publica 443 en los dos (HTTP/3). Docker publica sus puertos saltándose `ufw`: por eso el Compose solo publica 80 y 443 y no hay nada más que proteger. Comprueba **desde otra máquina** que el resto de puertos no responden.
4. DNS: crea los registros **A** (y **AAAA**, si el VPS tiene IPv6) de `FRONTEND_HOST` y `API_HOST` hacia la IP del servidor, **antes del primer arranque**. Sin ellos, Let's Encrypt no puede emitir los certificados.
5. Clona el repositorio en el servidor, por ejemplo en `/srv/semantic-repository`.

## Variables del `.env`

`cp .env.example .env`, edita los valores y protege el fichero con `chmod 600 .env`. `.env` está en `.gitignore`: no lo subas nunca, y no escribas valores reales en ningún fichero versionado. Los de `.env.example` son ficticios.

### Las que hay que cambiar en el servidor

| Variable | Qué es |
|---|---|
| `JWT_SECRET` | Secreto de los tokens. Mínimo 32 caracteres; se genera con `openssl rand -hex 32`. Vacío en el ejemplo: el backend no arranca sin él |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciales y nombre de la base de datos de usuarios y auditoría |
| `DATABASE_URL` | Debe llevar el mismo usuario, contraseña y base que las tres anteriores |
| `FUSEKI_ADMIN_PASSWORD` | Contraseña del usuario `admin` de Fuseki, que solo administra (lo usa `backup.sh`) |
| `FUSEKI_USER`, `FUSEKI_BACKEND_PASSWORD` | Usuario `backend` y su contraseña: es con el que la API escribe en Fuseki |
| `FUJI_USERNAME`, `FUJI_PASSWORD` | Autenticación Basic de la API de F-UJI, que usa el backend |
| `FRONTEND_HOST`, `API_HOST` | Los dos nombres de host públicos. **Solo el nombre**, sin `https://` ni barra |
| `CADDY_TLS` | El email de contacto de Let's Encrypt (avisos de caducidad). El valor del ejemplo, `internal`, es la CA interna de Caddy: solo vale para pruebas, porque los navegadores la rechazan |

Ni `FUSEKI_ADMIN_PASSWORD` ni `FUSEKI_BACKEND_PASSWORD` pueden llevar `,` `=` `\` `#` ni `;` (formato de `shiro.ini`): si los llevan, Fuseki no arranca.

### Las que `docker-compose.prod.yml` fija por ti

Tienen prioridad sobre las del `.env`; no hace falta cambiarlas:

| Variable | Valor en el piloto |
|---|---|
| `BASE_URI` | `https://{API_HOST}/semanticrepository/` |
| `FRONTEND_BASE_URL` | `https://{FRONTEND_HOST}` |
| `CORS_ORIGINS` | `https://{FRONTEND_HOST}` |
| `VITE_API_BASE_URL`, `VITE_BASE_URI` | Derivadas de `API_HOST`; se incrustan en el build del frontend |
| `FAIR_TARGET_BASE_URL` | Vacía: F-UJI evalúa la `BASE_URI` pública (decisión 47) |
| `FORWARDED_ALLOW_IPS` | `10.254.77.2`, la IP fija de Caddy en la red `proxy-net` (ver «IP del cliente») |

`FRONTEND_HOST` y `API_HOST` se incrustan en el build del frontend: si cambian, hay que reconstruir (`up -d --build`).

### Opcionales

| Variable | Por defecto | Qué es |
|---|---|---|
| `PROXY_HTTP_PORT`, `PROXY_HTTPS_PORT` | 80 y 443 | Puertos del proxy en el host. En el servidor no los cambies: Let's Encrypt los exige |
| `PROXY_MAX_BODY_RDF` | `11MiB` | Tamaño máximo de petición del API en general (RDF, JSON, SPARQL). Debe ser mayor o igual que `INGEST_MAX_BYTES` (10 MiB por defecto) |
| `PROXY_MAX_BODY_UPLOAD` | `520MiB` | Tamaño máximo de la subida de ficheros de distribución. Debe ser mayor o igual que `MAX_UPLOAD_MB` (512 por defecto) |
| `APP_COMMIT` | vacío | Commit desplegado (ver «Actualizar») |
| `REASONER_JAVA_MEMORY_MB` | `1024` | Heap de la JVM de Pellet (el razonador). Se puede cambiar desde `.env`; el límite de memoria del backend está en `docker-compose.prod.yml` |
| `BACKUP_DIR`, `BACKUP_RETENTION_DAYS` | `$HOME/itot-backups` y 14 | Las lee `backup.sh` del `.env` (ver «Copias de seguridad») |

El resto de variables de `.env.example` (límites de SPARQL, bloqueo de login, descargas, F-UJI, ingesta…) tienen valores por defecto razonables para el piloto y se explican en el propio fichero.

**IP del cliente.** Detrás del proxy, el backend recibe la IP real en `X-Forwarded-For`. Caddy, el backend y el frontend comparten la red `proxy-net` (subred `10.254.77.0/24`); Caddy tiene la IP fija `10.254.77.2` y solo está en esa red, y el backend confía en `X-Forwarded-For` solo si la conexión viene de ahí (`FORWARDED_ALLOW_IPS=10.254.77.2`, nunca `*`). Caddy sustituye el `X-Forwarded-For` que traiga el cliente, y una cabecera falsificada desde otro contenedor (por ejemplo, F-UJI) no cambia la IP. Así el límite de SPARQL anónimo y el bloqueo de login son por cliente y no del proxy entero. Si la subred chocara con una red del servidor, se cambian en `docker-compose.prod.yml` la subred, la IP de Caddy, la misma IP en `FORWARDED_ALLOW_IPS` y el `ip_range` (ver `infra/README.md`).

## Primer arranque

Para no repetir los ficheros en cada comando, exporta en tu sesión:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
export APP_COMMIT=$(git rev-parse --short HEAD)   # opcional: commit desplegado
```

Después, desde la carpeta del repositorio:

```bash
docker compose config -q                         # valida; falla si falta una variable obligatoria
docker compose up -d --build --wait --wait-timeout 900
docker compose ps                                # todos healthy
docker compose exec -T backend python -m app.cli load-semantic
docker compose exec -it backend python -m app.cli create-admin --username <nombre>
```

- La primera construcción es lenta (imágenes del frontend, el backend y F-UJI, que descarga su navegador).
- La primera vez, Caddy pide los certificados a Let's Encrypt; tarda unos segundos y los DNS tienen que apuntar ya al servidor.
- `load-semantic` carga las formas, los datos sintéticos, las ontologías y los vocabularios, validando antes con SHACL. Es idempotente. Si algo falla, no carga nada y sale con código 1.
- `create-admin` pide la contraseña por teclado (`--password-stdin` sirve para scripts). La contraseña no se escribe en ningún fichero ni se pasa como argumento. Es el primer admin ([ADR 0015](adr/0015-alta-de-usuarios.md)); el admin da de alta al resto de usuarios desde la API (`/users`, documentada en `/docs`).
- `APP_COMMIT` llega al backend; **cuando esté disponible** (`backend` lo prepara en otra PR), `/health` informará de la versión y del commit desplegado.

## Comprobar el despliegue

A mano:

- `https://{FRONTEND_HOST}` carga la aplicación.
- `https://{API_HOST}/health/ready` responde `ok`.
- `curl -i https://{API_HOST}/semanticrepository/dataset/<slug>` da 303 al frontend, y con `-H 'Accept: text/turtle'` da el RDF.
- `https://{API_HOST}/docs` se ve.
- El inicio de sesión funciona.

Con la prueba de humo (`tests/smoke`; su README describe todas las variables):

```bash
export SMOKE_EDITOR_USER=... SMOKE_EDITOR_PASSWORD=...   # no las escribas en ficheros
SMOKE_FRONTEND_URL=https://repositorio.example.org \
SMOKE_API_URL=https://api.example.org \
SMOKE_BASE_URI=https://api.example.org/semanticrepository/ \
SMOKE_CHECK_PORTS=1 \
  uv run --frozen --project backend pytest tests/smoke -v
```

- Sin `SMOKE_EDITOR_*` y sin `SMOKE_ALLOW_WRITE=1`, la prueba **no escribe nada**.
- `SMOKE_API_URL` va **sin** el prefijo `/semanticrepository`; `SMOKE_BASE_URI` sí lo lleva.
- `SMOKE_CHECK_PORTS=1` comprueba que 3030, 13030, 5432 y 15432 no responden desde donde la lanzas. No sustituye a revisar el cortafuegos del VPS desde otra red.
- Con `SMOKE_ALLOW_WRITE=1` y un editor, crea y borra un catálogo `smoke-<hex>`. Como el borrado es lógico ([ADR 0037](adr/0037-crud-de-catalogos-y-datasets.md)), el slug queda dado de baja y los eventos de auditoría permanecen. Úsala solo contra el entorno propio del proyecto.
- Los avisos (falta de cabeceras, API que no informa de su versión, ningún dataset con evaluación FAIR) no hacen fallar la prueba y se listan al final.

La prueba se ejecuta desde una máquina con el repositorio y `uv`, no hace falta que sea el VPS.

## Actualizar a una versión nueva

```bash
git pull                                         # o: git switch --detach <etiqueta>
export APP_COMMIT=$(git rev-parse --short HEAD)
infra/scripts/backup.sh                          # copia antes de actualizar
docker compose up -d --build --wait --wait-timeout 900
```

(Con `COMPOSE_FILE` exportado, como en el primer arranque.)

- Las migraciones de la base de datos las aplica el backend al arrancar.
- Si la actualización cambia datos semánticos, vuelve a lanzar `load-semantic`. La aplicación manda en bajas, traslados y contenido de los esquemas ([ADR 0037](adr/0037-crud-de-catalogos-y-datasets.md), [0038](adr/0038-vocabularios-y-ontologias-en-los-catalogos.md)): `load-semantic` no las deshace.
- Si cambian `FRONTEND_HOST` o `API_HOST`, el `--build` reconstruye el frontend.

### Marcha atrás de una actualización

Antes de actualizar, `backup.sh` (ya está en los pasos de arriba). Si la versión nueva falla:

```bash
git switch --detach <etiqueta-o-commit-anterior>
export APP_COMMIT=$(git rev-parse --short HEAD)
docker compose up -d --build --wait --wait-timeout 900
```

- Esto vuelve al código anterior **conservando los datos**, y **solo vale si la actualización no aplicó migraciones nuevas** de la base de datos. Las migraciones de Alembic solo avanzan: el código viejo no funciona con un esquema más nuevo.
- Si la versión nueva aplicó una migración, hay que volver a la versión anterior **y** restaurar la copia previa a la actualización con `restore.sh` (ver «Restaurar»). Se pierden los cambios hechos desde esa copia.
- `infra` lo probó en local: cambio a un commit anterior y vuelta, con la pila funcionando y los datos intactos. No se ha probado una migración real hacia atrás.

## Copias de seguridad y restauración

### Qué guarda `backup.sh`

`infra/scripts/backup.sh` crea una carpeta nueva `BACKUP_DIR/<fecha UTC>/` con:

| Fichero | Contenido |
|---|---|
| `postgres.dump` | `pg_dump` en formato custom (usuarios y auditoría) |
| `fuseki.nq.gz` | Volcado N-Quads de todos los grafos, por la API de administración de Fuseki (usuario admin, desde dentro del contenedor) |
| `distributions.tar.gz` | Volumen de distribuciones |
| `SHA256SUMS` | Sumas de los tres ficheros |

Se puede lanzar las veces que haga falta: cada ejecución crea su carpeta y nunca modifica las anteriores. Si falla, no deja una copia a medias y sale con código distinto de 0. Usa un bloqueo para no solaparse (si queda uno huérfano, el mensaje indica qué carpeta `.lock` borrar). Necesita los servicios `postgres`, `fuseki` y `backend` en marcha.

**No incluye, a propósito,** el volumen `caddy-data` (certificados y clave de la cuenta ACME): Caddy los vuelve a emitir solo la primera vez que arranca en un servidor nuevo. Let's Encrypt limita las emisiones por dominio, así que no repitas arranques desde cero sin necesidad; para las pruebas usa `CADDY_TLS=internal`.

Tampoco incluye el `.env`: guárdalo aparte, por un canal seguro (contiene los secretos).

### Programación, retención y ubicación

- **Cron diario** (`crontab -e` del usuario `itot`), según `infra/README.md`:

  ```
  30 3 * * * cd /srv/semantic-repository && infra/scripts/backup.sh >> $HOME/itot-backup.log 2>&1
  ```

- **Retención:** `BACKUP_RETENTION_DAYS` días (14 por defecto). Borra las copias más antiguas y conserva siempre la más reciente, aunque sea más vieja.
- **Ubicación:** `BACKUP_DIR` (por defecto `$HOME/itot-backups`), con permisos 700 y ficheros 600. Está en el mismo disco que los datos.
- **Variables:** `backup.sh` lee del `.env` solo `BACKUP_DIR` y `BACKUP_RETENTION_DAYS`, sin hacer `source` del fichero. Una variable definida en el entorno de quien lo lanza (por ejemplo, en la línea de cron) tiene prioridad sobre el `.env`. No guarda secretos: las credenciales las toma del entorno de los contenedores.
- **Registro:** el cron escribe siempre en `$HOME/itot-backup.log`. Revísalo de vez en cuando (`tail $HOME/itot-backup.log`): un fallo solo se ve ahí, o por la ausencia de carpetas nuevas.
- **Copia fuera del VPS:** pendiente de decidir (ver el último apartado).

### Restaurar

**La restauración es destructiva: sustituye por completo los datos actuales de PostgreSQL, Fuseki y distribuciones.** Sin `--yes` no hace nada. Antes de lanzarla:

1. Elige la carpeta de copia que quieres restaurar y comprueba que contiene los cuatro ficheros.
2. Si los datos actuales pueden valer algo, haz antes una copia con `backup.sh`.
3. Avisa al equipo: durante la restauración, el backend y el proxy están parados.

Pasos:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
infra/scripts/restore.sh --yes ~/itot-backups/<carpeta-de-la-copia>
```

El script, por orden:

1. Comprueba las sumas SHA-256 y que existen los cuatro ficheros. Si no coinciden, se detiene.
2. Para `backend` y `caddy`.
3. Restaura PostgreSQL (`pg_restore --clean`).
4. Vacía Fuseki (`DROP ALL`) y carga el N-Quads.
5. Vacía y restaura el volumen de distribuciones.
6. Arranca de nuevo `backend` y `caddy`, también si algo falla a medias.

Los servicios `postgres` y `fuseki` tienen que estar en marcha antes. Después, comprueba con la prueba de humo y entrando en la aplicación. `infra` probó en local copia, borrado de los tres almacenes y restauración: mismos recuentos de cuádruples, usuarios y ficheros, y el login funcionando.

### Restaurar en un servidor nuevo

Por ejemplo, tras perder el VPS. Según `infra/README.md`:

1. Prepara el servidor como en «Preparar el servidor». Los DNS tienen que apuntar ya al servidor nuevo: Caddy emite certificados nuevos.
2. Copia el `.env` (por tu canal seguro; no está en las copias) y la carpeta de la copia (`scp -r`).
3. Levanta la pila vacía con el «Primer arranque», **sin** `load-semantic` ni `create-admin`.
4. Ejecuta `infra/scripts/restore.sh --yes <carpeta-de-la-copia>` sobre ella.

Los usuarios, los datos y las distribuciones vuelven con la copia. Usa el mismo `JWT_SECRET` que el servidor viejo si quieres que las sesiones abiertas sigan valiendo. `infra` lo probó en local: pila borrada con sus volúmenes, levantada vacía y restaurada desde una carpeta copiada (895 cuádruples, 1 usuario, 9 ficheros, login y RDF correctos).

## Logs y diagnóstico

```bash
docker compose ps                               # estado y salud de cada servicio
docker compose logs --tail=200 backend          # también: caddy, fuseki, fuji, postgres, frontend
docker compose logs -f caddy                    # en directo
docker stats --no-stream                        # memoria y CPU de cada contenedor frente a su límite
```

- Todos los servicios rotan sus logs (`json-file`, 10 MB por fichero, 5 ficheros).
- El registro de acceso de Caddy sale por la salida estándar (JSON) y oculta el valor de `?token=` de los enlaces de descarga firmados, como hace el backend.
- Para saber si un contenedor murió por falta de memoria: `docker inspect -f '{{.State.OOMKilled}}' $(docker compose ps -q fuseki)`. Cambia `fuseki` por el servicio que quieras mirar.

### Límites de memoria

Cifras de partida para 8 GB, sin carga real: la suma es de unos 6,4 GB y deja el resto al sistema y a la caché de disco.

| Servicio | Límite | Notas |
|---|---|---|
| `fuseki` | 2 GB | `JAVA_TOOL_OPTIONS=-Xms256m -Xmx1g` |
| `backend` | 2,5 GB | Pellet con `REASONER_JAVA_MEMORY_MB=1024`; la validación SHACL conserva su `SHACL_MEMORY_MB` |
| `fuji` | 1,25 GB | Chromium; en reposo ronda 450 MB |
| `postgres` | 512 MB | |
| `caddy` | 128 MB | |
| `frontend` | 64 MB | |

Un contenedor que supera su límite se reinicia (`restart: unless-stopped`). Los límites de memoria (`mem_limit`) y el heap de Fuseki (`JAVA_TOOL_OPTIONS`) están escritos en `docker-compose.prod.yml`, **no** son variables del `.env`: ajustarlos es un cambio de ese fichero, por PR de `infra`. El heap de Pellet sí se cambia desde `.env` con `REASONER_JAVA_MEMORY_MB` (1024 por defecto); si lo subes, comprueba que cabe en el límite del backend. Mide primero con `docker stats` durante el uso real del piloto. El ajuste definitivo está pendiente de decidir.

## Certificados

- Caddy pide y renueva los certificados de Let's Encrypt de los dos hosts por su cuenta. `CADDY_TLS` es el email de contacto al que Let's Encrypt avisa de las caducidades.
- Se guardan en el volumen `caddy-data` (y la configuración en `caddy-config`). **No los borres**: Let's Encrypt limita las emisiones por dominio. Las copias de seguridad no los incluyen a propósito: en un servidor nuevo Caddy los emite otra vez, pero no reinstales desde cero muchas veces. Ojo, `docker compose down -v` borra **todos** los volúmenes, también los datos.
- Let's Encrypt solo emite certificados: no recibe datos del repositorio.
- Si falla la emisión, `docker compose logs caddy` dice por qué. Causas habituales: el DNS no apunta al servidor, los puertos 80 o 443 están cerrados, o se agotó el límite de emisiones.
- La prueba de humo avisa si un certificado caduca en menos de 14 días.
- Con `CADDY_TLS=internal` los navegadores rechazan el certificado, y F-UJI tampoco confía en esa CA, así que las evaluaciones FAIR no funcionan. Es solo para pruebas locales.

## Incidencias típicas

**Fuseki sin memoria o que se reinicia.**
- Síntomas: consultas que fallan o tardan, `docker compose ps` muestra reinicios, el log de `fuseki` acaba de golpe.
- Diagnóstico: `docker inspect -f '{{.State.OOMKilled}}' $(docker compose ps -q fuseki)`, `docker stats --no-stream` y `docker compose logs fuseki`.
- Remedio: subir el límite y el heap en `docker-compose.prod.yml` (PR de `infra`) y recrear con `docker compose up -d`. Si el servidor se queda corto en conjunto, bajar la carga de otros servicios o ampliar el VPS es decisión del responsable.

**F-UJI no puede evaluar.** La ficha del dataset muestra la evaluación como fallida, o se queda en pendiente.
- Mira `docker compose logs fuji backend`.
- Comprueba que `fuji` está `healthy` y que `FAIR_TARGET_BASE_URL` está vacía en el backend (la fija el Compose de producción). Con `BASE_URI` mal resuelta, las evaluaciones fallan con «F-UJI respondió 500».
- F-UJI evalúa la `BASE_URI` pública: necesita DNS resuelto, certificado válido y salida a internet. Con `tls internal` no puede.
- Cada versión nueva de dataset encola su evaluación; el trabajador de la API la recoge cada `FAIR_WORKER_POLL_SECONDS` (10 s por defecto). Un editor o admin puede pedir otra con `POST /datasets/{slug}/versions/{version}/fair`.
- La API y el resto de la aplicación funcionan aunque F-UJI no esté disponible.
- [PENDIENTE] Si hay un fallo por una llamada saliente bloqueada, qué servicios se admiten depende de una decisión pendiente (ver el último apartado).

**413 por tamaño.** El proxy y el backend limitan los tamaños, cada uno por su lado:

| Qué | Proxy | Backend |
|---|---|---|
| RDF, JSON y SPARQL | `PROXY_MAX_BODY_RDF` (11 MiB) | `INGEST_MAX_BYTES` (10 MiB) |
| Fichero de distribución | `PROXY_MAX_BODY_UPLOAD` (520 MiB) | `MAX_UPLOAD_MB` (512) |
| Host del frontend | 1 MiB, fijo | no aplica |

Si se cambia un límite del backend, hay que cambiar también el del proxy (el del proxy debe ser algo mayor). Los errores que genera el propio proxy (413, 502 y 503) llevan cabeceras CORS para el host del frontend, así que el navegador los ve con su código real y no como un fallo de red. Qué verá el usuario:
- **413 en un formulario** (publicar versión, esquema u ontología, sustituir una externa, crear, editar…): «El fichero supera el tamaño máximo que admite la API.» Es el mismo texto si lo corta el proxy o el backend. En el formulario de un RDF, el texto habla de «fichero» aunque el límite sea el del RDF.
- **413 en la consola SPARQL** (al ejecutar o al guardar una consulta): «La consulta supera el tamaño máximo permitido.»
- **502**: la interfaz no tiene mensaje propio y muestra el genérico del formulario (por ejemplo, «No se ha podido publicar la versión.»). **503** sin `Retry-After`: «El repositorio no está disponible ahora mismo. Inténtalo más tarde.»
- Para distinguir quién respondió, mira el log de `caddy` (`docker compose logs caddy`).

**Bloqueo de login.** Tras `LOGIN_MAX_FAILURES` fallos (5 por defecto) de un usuario desde una IP dentro de `LOGIN_WINDOW_MINUTES` (15), ese par queda bloqueado `LOGIN_LOCKOUT_MINUTES` (15): la API responde 429 con `Retry-After`, **aunque la contraseña sea correcta** ([ADR 0026](adr/0026-login-y-revocacion-de-tokens.md)).
- La interfaz no distingue el 429: muestra «No se ha podido iniciar sesión. Inténtalo de nuevo más tarde.». Dile a la persona que espere el tiempo del bloqueo.
- El bloqueo es por usuario e IP: otra persona, o la misma desde otra IP, no se ve afectada. Para que sea así, el backend debe ver la IP real del cliente (ver «IP del cliente»).
- No hay en el repositorio un comando para desbloquear a mano (el CLI solo tiene `create-admin` y `load-semantic`). [PENDIENTE] Si hace falta, decidirlo con `backend`.

**«El servidor está ocupado»** (503 con `Retry-After`): otra escritura tiene el bloqueo de catálogos y datasets. Es pasajero; el tiempo máximo de espera es `CATALOG_LOCK_TIMEOUT_SECONDS` (30 por defecto).

## Decidido por el responsable (2026-11-27)

1. **Sin copias fuera del VPS** (decisión 54). El piloto es un prototipo para mostrar, con datos sintéticos: no se copian las copias a otro sitio. `backup.sh` sigue disponible para copias locales, por ejemplo antes de una actualización, pero perder el VPS supone perder también sus copias.
2. **F-UJI consulta servicios externos** (decisión 55). Se acepta para el piloto: con salida a internet (decisión 47), F-UJI puede llamar, entre otros, a Mendeley Data (Elsevier) con el identificador y la URL de la página. La tabla completa está en `infra/README.md`, «Llamadas salientes de F-UJI». La instalación con datos reales se decidirá aparte.
3. **`cdn.jsdelivr.net` en `/docs` y `/redoc`** (decisión 56, que confirma la 24). Swagger UI y ReDoc cargan scripts y estilos de ese CDN en el navegador de quien los abre, y la CSP de esas rutas lo permite.
4. **Sin job `smoke-prod` en CI** (decisión 57). Solo queda `compose-prod`, que valida la configuración del Compose y de los Caddyfile. La prueba de humo se ejecuta a mano contra el despliegue.

## Pendiente

- **El ajuste real de la memoria.** Los límites de arriba son cifras de partida. Hay que medirlos con `docker stats` durante el uso del piloto y fijar los definitivos.

También están pendientes, sin ser decisiones de esta lista: los hosts reales (decisión 3, «los hosts reales, en la fase 5») y que `/health` informe de la versión y el commit (PR #57).
