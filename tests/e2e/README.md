# Pruebas de extremo a extremo

## Puerta G1 · entorno local listo

`test_g1_entorno_local.py` levanta el `docker-compose.yml` del repositorio y recorre el criterio de la puerta:

1. Los cuatro servicios de la fase 1 (PostgreSQL, Fuseki, backend y frontend) arrancan y están sanos; las migraciones han creado las tablas; todos se publican solo en `127.0.0.1`.
2. Fuseki admite consultas anónimas y rechaza cualquier escritura sin las credenciales del admin (regla «solo el backend escribe en el triplestore»). El frontend no recibe ningún secreto del backend, y el backend no arranca con el `JWT_SECRET` vacío de `.env.example`.
3. El primer admin se crea con la CLI del backend (`create-admin --password-stdin`).
4. El login devuelve un JWT con el rol, y `/auth/me` responde. Un usuario con byte nulo o caracteres de control recibe el 401 genérico.
5. El admin da de alta un miembro y un editor; solo el admin gestiona usuarios; nadie se sube el rol; una baja o un cambio de rol se aplican con el token vigente.
6. Todo el recorrido queda en `audit_events`, y ni la auditoría ni los logs contienen contraseñas, tokens o secretos.
7. Al terminar, apaga el entorno y borra sus volúmenes e imágenes.

## Puerta G2 · primer dataset publicado

`test_g2_catalogo.py` usa el mismo entorno (se levanta una sola vez para los dos ficheros) y recorre el criterio de la puerta:

1. Los cuatro servicios están sanos, incluido el frontend, que ya declara healthcheck. El backend recibe `SEMANTIC_DIR`, `FUSEKI_USER`, `FUSEKI_PASSWORD` y `FRONTEND_BASE_URL`, y `./semantic` está montado en solo lectura.
2. `load-semantic` carga las piezas de la fase 2 (los dos esquemas auxiliares del vocabulario mínimo, el catálogo y las tres series sintéticas), cada una en su grafo con nombre; es idempotente y queda en la auditoría como `dataset_published` con actor `cli`. Desde la fase 3 carga además vocabularios y ontologías: el recuento completo está en la prueba de G3.
3. El catálogo lista los tres datasets sintéticos; los filtros por dominio y por texto, la paginación y la validación de parámetros funcionan; el origen del frontend puede leerlo (CORS).
4. La ficha muestra la versión actual, el historial y las distribuciones; cada versión antigua tiene su ficha; lo que no existe da 404. Los placeholders del prototipo (licencia, contacto, fechas) llegan vacíos, no inventados.
5. El RDF de cada versión sale en Turtle y en JSON-LD, por `?format=` o por `Accept`.
6. La URI persistente `/dataset/{slug}` y la de una versión redirigen con 303 a la ficha del frontend cuando se pide HTML, y esa ruta del frontend responde; con `Accept` de RDF devuelven el RDF.
7. Un editor publica una serie por la API y aparece en el catálogo, en Fuseki y en la auditoría; republicar el mismo contenido no cambia nada; el admin publica por herencia; un miembro recibe 403 y un anónimo 401. También se publica en JSON-LD.
8. La ingesta que no cumple las formas SHACL se rechaza con 422 y su informe (todos los ejemplos de `semantic/examples/invalid/`), igual que la que intenta escribir fuera de su serie, la de sintaxis o `Content-Type` incorrectos, la de contexto JSON-LD remoto (sin que el backend salga a buscarlo) y la que supera `INGEST_MAX_BYTES` (413). Ningún rechazo escribe en Fuseki ni en la auditoría.
9. Todo lo sintético lleva la marca `dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>`: en el triplestore, en la API (`synthetic`) y en el RDF servido. Las series que publica la propia prueba también van marcadas.
10. Ni la auditoría, ni los logs, ni la API contienen las credenciales de Fuseki, y Fuseki sigue rechazando escrituras anónimas.

La prueba crea sus propias cuentas de editor y miembro: las de G1 terminan con el rol cambiado o dadas de baja.

Lo que esta prueba no cubre: el contenido que pinta el navegador en las pantallas Catálogo y Ficha. Solo comprueba que el frontend sirve la aplicación en esas rutas y que la API le da los datos. Las pantallas en un navegador real están en `tests/browser/` (Playwright, decisión 34).

## Puerta G4 · FAIR y versiones

`test_g4_fair_versiones.py` usa el mismo entorno, con F-UJI real dentro del Compose (red interna `fuji-net`), y se ejecuta después de G3. Recorre el criterio de la puerta:

1. Los cinco servicios están sanos; F-UJI no publica ningún puerto y no tiene salida a internet. El usuario `backend` escribe en Fuseki, `admin` administra, y las contraseñas no son intercambiables ni valen las de `.env.example`.
2. Cada versión actual de los tres datasets sintéticos recibe una evaluación F-UJI real (`done`) visible en `/datasets/{slug}` y en la tarjeta del catálogo, con su informe en `report_url`. Las puntuaciones y el nivel de madurez son los del `summary` del informe, sin cambios. Reevaluar exige editor y deja `fair_evaluated`; recargar los datos no reevalúa lo ya evaluado.
3. Una versión nueva se añade y se evalúa; las anteriores no cambian (mismo RDF, misma evaluación). Alterar una versión publicada, abrir sus `accessRights` o quitarla da 409 y no escribe nada, ni en el triplestore ni en la auditoría ni en la cola FAIR.
4. Descargas: las 8 distribuciones sintéticas son `RESTRICTED` y todas tienen fichero. Una distribución sin fichero sale como `unavailable` y da 404 (serie de prueba propia). Un miembro las descarga byte a byte con enlace firmado (un solo uso, que caduca de verdad y no vale para otro fichero ni si está manipulado) o con sesión; un anónimo no. Una serie nueva cubre `PUBLIC` (cualquiera), `RESTRICTED` y `NON_PUBLIC` (nunca admite fichero). Path traversal, subida por rol e inmutabilidad de los ficheros.
5. Negociación (decisión 31): sin `Accept`, con `*/*` o con el `Accept` de un navegador, 303 a la ficha del frontend; RDF solo con un `Accept` de RDF.
6. Login: 5 fallos dan 401 y el siguiente intento 429 con `Retry-After`, aunque la contraseña sea correcta; una baja invalida los tokens y reactivar no los revive.
7. SPARQL público: consultas `SELECT`, `ASK`, `CONSTRUCT` y `DESCRIBE`, las tres de referencia, y rechazo de actualizaciones, `SERVICE`, `FROM` ajeno y consultas de más de 20 KB; una consulta costosa da 504 y una grande se trunca con `X-Result-Truncated`. Un miembro guarda una consulta personal que otro no ve (404 al tocarla) y tiene un límite por usuario.
8. Límite de frecuencia por IP (anónimo) y por usuario, sin burlarlo con cabeceras de proxy. Va la última y espera al inicio de un minuto, porque agota el cupo.
9. Ni la auditoría ni los logs de ningún servicio contienen secretos.

La prueba de caducidad espera de verdad `DOWNLOAD_LINK_TTL_SECONDS` y la de límites espera al inicio de un minuto: G4 tarda unos tres minutos más que G3.

Puntuación real de F-UJI 4.0.1 con los datos sintéticos (versión actual de cada dataset): total 52.08 (F 35.71, A 100, I 50, R 50), con madurez 2.0 en `modbus-tcp-testbed` y 1.75 en los otros dos.

## Decisión 49 · CRUD de catálogos y datasets

`test_g5_crud_catalogos.py` usa el mismo entorno y va **después de G4** (por el nombre). Su última prueba da de baja un dataset sintético (`ejemplos-adversarios-vision`): nada que se ejecute después puede contar con él, ni se puede repetir sobre el mismo entorno (el slug no se reutiliza). Cubre:

1. Roles en cada endpoint nuevo (`POST/PATCH/DELETE` de catálogos y datasets): anónimo 401, miembro 403, token manipulado 401, y un rechazo no escribe en Fuseki ni en la auditoría.
2. CRUD de catálogos y datasets por editor y admin; el catálogo raíz no cambia; mover un dataset (un solo catálogo, URIs y versiones intactas); el 409 al borrar un catálogo con datasets (con su lista) y el 409 por slug dado de baja.
3. 410 en JSON, HTML (sin `Accept`, `*/*`, `text/html` y el de un navegador, con el título escapado) y RDF (Turtle, JSON-LD y RDF/XML), también por prefijo (versión, distribución y fichero, incluida una versión que nunca existió).
4. Las bajas **no salen en el SPARQL público contra Fuseki real**: consultas con `GRAPH ?g`, `GRAPH <bajas>`, `VALUES`, `BIND`, `FILTER`, `UNION`, subconsultas, `CONSTRUCT`, `DESCRIBE`, `FROM`/`FROM NAMED` (400), variantes de la IRI, `SERVICE`, escrituras y parámetros `default-graph-uri` del cliente. Un control consulta Fuseki directamente y comprueba que la lápida existe (y que el grafo por defecto de Fuseki la vería sin el filtro del backend).
5. Inyección al construir el RDF desde el JSON (títulos con comillas, `"""`, IRIs y literales tipados; slugs hostiles) y que la baja elimine los ficheros (también en un dataset con distribución `NON_PUBLIC`).
6. Auditoría de cada operación, sin títulos ni secretos.
7. `load-semantic` conserva lo hecho desde la aplicación (catálogos, datasets, traslados) y no resucita lo dado de baja.

### Defectos de la decisión 49

**QA-49-01** (altas y bajas simultáneas perdían enlaces del raíz y lápidas) y **QA-49-02** (un fichero huérfano quedaba en disco al dar de baja un dataset) están corregidos: sus pruebas pasan sin marca. Además se comprueba que no queda ningún advisory lock retenido y que `load-semantic` y la API se serializan.

**QA-49-03** (ráfagas de escrituras: 500 por pool agotado y `/auth/me` parado) también está corregido. Se comprueba con 20 altas simultáneas (todas 201, `/auth/me` sin esperas) y con el bloqueo retenido desde otro proceso (`psql`): las escrituras vencen a los 30 s con 503 y `Retry-After: 5`, sin escribir nada, mientras las lecturas siguen respondiendo.

## Puerta G3 · vocabularios cargados

`test_g3_vocabularios.py` usa el mismo entorno y se ejecuta después de G1 y G2. Recorre el criterio de la puerta:

1. La imagen del backend lleva Java 25 o superior para Pellet y el backend no se ejecuta como root; las variables del razonador son opcionales (`REASONER_TIMEOUT_SECONDS`, `REASONER_JAVA_MEMORY_MB`) y la migración `0002` ha creado la tabla `ontology_metrics`.
2. `load-semantic` carga los 20 ficheros de `semantic/` en 21 grafos: 5 esquemas de dominio, 4 corporativos, los 2 auxiliares de `vocab-minimo.ttl`, 5 versiones de ontología, las externas, el catálogo y las 3 series. Calcula las métricas de cada versión de ontología con owlready2 y la consistencia con Pellet (el de verdad, dentro del contenedor), es idempotente sin recalcular métricas y queda en la auditoría como `ontology_published` y `scheme_published` con actor `cli`.
3. `/vocabularies` da los recuentos 3/3/4/5 (propias, externas, corporativos y de dominio) y filtra por `kind`, `domain` y `q`; `domain=pqc` devuelve `pqc` y `did`; los esquemas auxiliares no tienen tarjeta; todo lo propio lleva la marca de sintético y las externas no.
4. La ficha de `itot` trae las métricas (13 clases, ninguna propiedad, 8 axiomas lógicos, 2 imports y 0 % de documentación, tras la decisión 38), la consistencia de Pellet, el versionado con su historial, los imports enlazados con las externas, su uso en el catálogo y los conceptos SKOS que usa. Las versiones antiguas tienen ficha y métricas; lo que no existe da 404; el RDF sale en Turtle, JSON-LD y RDF/XML. Los placeholders del prototipo llegan vacíos.
5. El árbol del esquema `ot` (con `alt_labels`) y el detalle de cada concepto; el concepto `modbus-tcp` con sus usos en datasets y ontologías; los esquemas corporativos.
6. Las URIs persistentes `/onto/…` y `/vocab/…` redirigen con 303 a las rutas del frontend (`/ontologias/{slug}?version=`, `/vocabularios/[corp/]{slug}?concepto=`), que responden; con `Accept` de RDF devuelven el RDF; lo que no existe da 404 también en HTML.
7. Un editor publica una ontología (con métricas y consistencia de Pellet) y un esquema SKOS, y aparecen en el listado, en Fuseki, en PostgreSQL y en la auditoría; republicar el mismo contenido no recalcula nada; el admin publica por herencia una versión nueva; una ontología inconsistente se publica con el aviso; también en JSON-LD. Un miembro recibe 403 y un anónimo 401. El `owl:imports` de la ontología publicada apunta al Fuseki del entorno y nadie lo descarga (ni owlready2 ni Pellet).
8. Lo que no cumple las formas SHACL se rechaza con 422 y su informe (todos los ejemplos de `semantic/examples/invalid/ontologias-vocabularios/`), igual que lo que intenta describir otro recurso (otra ontología o versión, un esquema, el catálogo, `vocab/dominio`, una serie), los slugs reservados `externas`, `corp`, `dominio` y `tipo-dataset`, las versiones incoherentes, el XML (415), los contextos JSON-LD remotos y lo que supera los límites de expansión o de profundidad (422 `limit`). Ningún rechazo escribe en Fuseki, en `ontology_metrics` ni en la auditoría.
9. El dominio de los datasets es el `dct:subject` del esquema de sus temas, con la etiqueta del concepto de `vocab/dominio` (la ficha de Modbus muestra «OT / ICS»); un tema del esquema `did` da el dominio `pqc`, y un tema de un esquema publicado por la API, el dominio que declara ese esquema.
10. Las descargas (`?download=1`) de ontologías, esquemas y datasets llevan `Content-Disposition` con un nombre seguro `{slug}-{versión}.{ttl|jsonld|rdf}`; sin el parámetro, no.
11. Ni la auditoría, ni `ontology_metrics`, ni los logs, ni la API contienen secretos, rutas del contenedor o trazas; Fuseki sigue rechazando escrituras anónimas; no quedan procesos de Pellet y el entorno sigue sano.

Lo que esta prueba no cubre:

- El contenido que pinta el navegador en las pantallas Vocabularios, Ficha de ontología y Navegador SKOS: está en `tests/browser/` (Playwright, decisión 34).
- El tiempo máximo del razonador y sus fallos: cambiar `REASONER_TIMEOUT_SECONDS` exigiría otro entorno. Están en `backend/tests/test_security_g3.py`, con el Pellet real si hay Java 25 o superior.
- El workflow `publicar.yml`: no se empuja ninguna etiqueta. Su revisión estática y `publicar.py` con etiquetas hostiles están en `backend/tests/test_publicar_pipeline.py`.

### Sonda de peticiones salientes

Para comprobar que el backend no sale a buscar una URL que viene en el RDF (un `@context` remoto, un `owl:imports`), la URL apunta al endpoint SPARQL del Fuseki del propio entorno (`fuseki_probe_url` en `conftest.py`): Fuseki registra cada consulta en su log con su texto. Una ruta cualquiera de Fuseki no queda registrada, así que cada comprobación lleva una petición de control que sí debe aparecer.

### Defectos conocidos

Los hallazgos de las fases 2 y 3 (QA-G2-01 a QA-G2-07 y QA-G3-01 a QA-G3-13) están corregidos: sus pruebas pasan sin marca, aquí y en `backend/tests/`. En la fase 4 lo corrigieron las decisiones 28 a 30 y 44 (versiones inmutables, `q` por URI, catálogo en `dcat:dataset` y `IED ⊑ ActivoIndustrial`), con pruebas en `test_g4_fair_versiones.py`.

Hallazgos de la fase 4: **todos cerrados** y sus pruebas pasan sin marca (reverificación sobre `integracion/fase4`).

| Id | Capa | Defecto | Estado |
|---|---|---|---|
| QA-G4-01 | `backend` | F-UJI no llegaba a los metadatos (8.33 sobre 100) | Cerrado: evalúa la URL del RDF; 52.08 con los datos sintéticos (madurez 1.75 o 2.0). El informe público muestra la URI persistente y no el host interno |
| QA-G4-02 | `backend` | El log de acceso escribía el `?token=` firmado | Cerrado: `token=[oculto]` |
| QA-G4-03 | `backend` | Un `SELECT` de más de 32 MB daba 400 en vez de truncarse | Cerrado: truncado en streaming con `X-Result-Truncated` |
| QA-G4-04 | `frontend` | Se perdía lo escrito en el editor antes de cargar las consultas guardadas | Cerrado (`tests/browser/`) |
| QA-G4-05 | `backend` | Subidas simultáneas del mismo fichero daban 500 | Cerrado: 200 idempotente o 409 `file_exists` |

Un hallazgo nuevo se marca con `xfail(strict=True)` y su `QA-G4-NN` hasta que se corrija.

### Requisitos

- Docker con Compose v2.24 o posterior (la prueba usa `!override` en un fichero de Compose adicional).
- [uv](https://docs.astral.sh/uv/). La prueba solo usa la biblioteca estándar de Python y pytest, que ya es dependencia de desarrollo del backend: no añade dependencias.

### Ejecución

Desde la raíz del repositorio:

```sh
uv run --project backend pytest tests/e2e -v
```

La primera vez construye las imágenes del backend y del frontend, así que tarda unos minutos. Sin Docker disponible, las pruebas se saltan; con `E2E_REQUIRE_DOCKER=1` fallan en lugar de saltarse.

| Variable | Efecto |
|---|---|
| `E2E_REQUIRE_DOCKER=1` | Falla si no hay Docker (para CI o para validar la puerta) |
| `E2E_KEEP=1` | No apaga el entorno al terminar, para inspeccionarlo. El nombre del proyecto se imprime al final; se apaga con `docker compose -p <proyecto> down -v --rmi local` |
| `E2E_UP_TIMEOUT` | Segundos de espera a que los servicios estén sanos (por defecto, 900) |
| `E2E_ATTACH_PROJECT` y `E2E_ATTACH_ENV_FILE` | Solo para desarrollar las pruebas: usan un entorno ya levantado (nombre del proyecto de Compose y su fichero de entorno) en vez de levantar otro. No lo apagan |

### Aislamiento

- **Proyecto de Compose propio:** `itot-e2e-<aleatorio>`. No toca el proyecto `itot` de desarrollo ni sus volúmenes.
- **Puertos:** elige cuatro puertos libres en `127.0.0.1` y se los pasa al Compose con `POSTGRES_HOST_PORT`, `FUSEKI_HOST_PORT`, `BACKEND_HOST_PORT` y `FRONTEND_HOST_PORT`. Da igual que 5432, 3030, 8000 o 5173 estén ocupados.
- **Entorno:** no lee ni escribe el `.env` de la raíz. Genera uno temporal a partir de `.env.example` (así comprueba también que `.env.example` documenta todas las variables necesarias) y rellena los secretos con valores aleatorios, incluido `JWT_SECRET`, que en `.env.example` va vacío. `CORS_ORIGINS`, `VITE_API_BASE_URL` y `FRONTEND_BASE_URL` se ajustan a los puertos elegidos. Con un fichero de Compose adicional generado en una carpeta temporal, hace que el `env_file` del backend apunte a él. Es lo único que cambia respecto al `docker-compose.yml` real.
- **Credenciales:** las contraseñas de PostgreSQL, Fuseki, el secreto JWT y las contraseñas de las cuentas se generan en cada ejecución con `secrets`. No hay ninguna fija ni versionada.
- **Alcance:** todas las peticiones van a `127.0.0.1`. El cliente HTTP de la prueba rechaza cualquier otra URL.

### Decisiones pendientes que la prueba no cubre

Estos puntos no son defectos ni llevan `xfail`: son decisiones que `Plan.md` no fija y que corresponden al responsable. Cuando se decidan, se añade aquí la prueba correspondiente.

| Punto | Situación actual | Dueño cuando se decida |
|---|---|---|
| `/docs` y `/redoc` en el despliegue | Son públicos y cargan recursos de un CDN externo | `backend`, `infra` |
| QA-G3-12 · Dependencias Java de Pellet | pip-audit no cubre los JAR que incluye owlready2. `infra` propone un job `imagen-backend` con Trivy en `ci.yml` (falla con hallazgos críticos, sin subir resultados); está pendiente de que el responsable lo acepte. Si se queda, `test_publicar_pipeline.py` comprueba que va fijado por commit y sin permisos de más | `infra`, `qa` |
