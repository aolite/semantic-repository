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

Lo que esta prueba no cubre: el contenido que pinta el navegador en las pantallas Catálogo y Ficha. Solo comprueba que el frontend sirve la aplicación en esas rutas y que la API le da los datos. Comprobar las pantallas en un navegador real necesitaría una herramienta nueva (por ejemplo, Playwright), que no está decidida en `Plan.md`.

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

- El contenido que pinta el navegador en las pantallas Vocabularios, Ficha de ontología y Navegador SKOS (misma limitación que en G2; decisión abierta 34).
- El tiempo máximo del razonador y sus fallos: cambiar `REASONER_TIMEOUT_SECONDS` exigiría otro entorno. Están en `backend/tests/test_security_g3.py`, con el Pellet real si hay Java 25 o superior.
- El workflow `publicar.yml`: no se empuja ninguna etiqueta. Su revisión estática y `publicar.py` con etiquetas hostiles están en `backend/tests/test_publicar_pipeline.py`.

### Sonda de peticiones salientes

Para comprobar que el backend no sale a buscar una URL que viene en el RDF (un `@context` remoto, un `owl:imports`), la URL apunta al endpoint SPARQL del Fuseki del propio entorno (`fuseki_probe_url` en `conftest.py`): Fuseki registra cada consulta en su log con su texto. Una ruta cualquiera de Fuseki no queda registrada, así que cada comprobación lleva una petición de control que sí debe aparecer.

### Defectos conocidos

En estas pruebas de extremo a extremo no hay ninguna marcada como `xfail`. Los hallazgos QA-G2-01 a QA-G2-04 de la revisión de la fase 2 (IRIs no válidas, anidamiento extremo, autenticación antes del cuerpo y lectura limitada a los grafos publicados) están corregidos y sus pruebas pasan, aquí y en `backend/tests/test_security_fase2.py`.

Los hallazgos QA-G3-01 a QA-G3-10 de la revisión de la fase 3 están corregidos y sus pruebas pasan sin marca, en `backend/tests/test_security_g3.py`, `test_contracts_fase3.py` y `test_publicar_pipeline.py`:

| Id | Defecto | Cómo quedó |
|---|---|---|
| QA-G3-01 | Un literal mal tipado hacía fallar a owlready2 y `POST /ontologies` respondía 500 | 422 `syntax`; el análisis va antes de escribir, también en `load-semantic`; cualquier excepción del razonador deja `consistent: null` |
| QA-G3-02 | El detalle de un fallo de Pellet publicaba una línea de la traza de Java | Detalle genérico |
| QA-G3-03 | Un prefijo largo repetido expandía el RDF unas 590 veces en memoria | Límites durante el análisis; 422 `limit` en las tres ingestas |
| QA-G3-04 | Una jerarquía `skos:broader` de 300 niveles rompía `GET /schemes/{slug}` | Profundidad máxima de 64 en la ingesta y árbol sin recursión |
| QA-G3-05 | Un predicado que RDF/XML no puede abreviar daba 500 al descargar en RDF/XML | 406 en RDF/XML; Turtle y JSON-LD siguen disponibles |
| QA-G3-06 | `POST /schemes` admitía los slugs `dominio` y `tipo-dataset` | 422 `uri`; solo los carga `load-semantic` |
| QA-G3-07 | Quedaba en `/tmp` una copia de la ontología si el razonamiento no terminaba bien | Directorio temporal propio que se borra siempre |
| QA-G3-08 | `publicar.py` admitía una etiqueta con salto de línea final | `fullmatch` |
| QA-G3-09 | `semantic/uris.md` documentaba otro grafo para los esquemas auxiliares | Documento corregido |
| QA-G3-10 | La validación SHACL no tenía límite de tiempo | Proceso hijo con `SHACL_TIMEOUT_SECONDS` y `SHACL_MEMORY_MB`; 422 `limit` |

QA-G3-13 también está corregido: el contrato añadió `auxiliary` a `SchemeDetail.kind` y el Navegador SKOS se quedaba en blanco en `/vocabularios/dominio`, adonde redirige (303) la URI de dominio de un dataset. El frontend ya contempla ese valor, muestra tal cual cualquier valor desconocido de un enumerado y tiene un error boundary. Lo cubren `test_frontend_scheme_kind_matches_the_contract`, las pruebas del propio frontend y, aquí, el caso que sigue la URI de dominio de un dataset hasta el esquema auxiliar.

No queda ningún defecto abierto de la fase 3: no hay pruebas marcadas como `xfail`.

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
| Límite de intentos de login | No hay bloqueo ni límite de frecuencia en `POST /auth/token` | `backend` |
| `/docs` y `/redoc` en el despliegue | Son públicos y cargan recursos de un CDN externo | `backend`, `infra` |
| Revocación de tokens | Una cuenta reactivada vuelve a aceptar los tokens emitidos antes de la baja, hasta que caducan | `backend` |
| Pantallas en un navegador real | No hay herramienta decidida (decisión abierta 34); la prueba no ejecuta el JavaScript del frontend | `qa`, `frontend` |
| Versiones de ontología inmutables | Republicar una versión ya publicada con otro contenido la sustituye y recalcula sus métricas (para los datasets es la decisión abierta 28) | `backend` |
| QA-G3-11 · Búsqueda `q` de vocabularios | Busca también en el espacio de nombres, que contiene `BASE_URI`: con el valor por defecto, `q=itot` devuelve todo lo propio | `backend`, `frontend` |
| QA-G3-12 · Dependencias Java de Pellet | pip-audit no cubre los JAR que incluye owlready2. `infra` propone un job `imagen-backend` con Trivy en `ci.yml` (falla con hallazgos críticos, sin subir resultados); está pendiente de que el responsable lo acepte. Si se queda, `test_publicar_pipeline.py` comprueba que va fijado por commit y sin permisos de más | `infra`, `qa` |
| Jerarquía de `itot` · `IED ⊑ ActivoIndustrial` | Tras la decisión 38 la ontología solo lleva la jerarquía que cita el prototipo; esta relación la decide el responsable | `semantico` |
| QA-G2-05 · El catálogo RDF tras publicar por la API | `POST /datasets` no añade la serie a `dcat:dataset` del grafo del catálogo, que solo cambia con `load-semantic` | `backend`, `semantico` |
| QA-G2-06 · Búsqueda por URI | El campo de búsqueda dice «Título, concepto o URI», pero `q` solo busca en título, descripción y temas | `frontend`, `backend` |
| QA-G2-07 · Paginación del catálogo | La pantalla pide una sola página de 100 recursos; con más, el contador muestra el total pero faltan tarjetas | `frontend` |
