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
2. `load-semantic` carga las cinco piezas (vocabulario mínimo, catálogo y tres series sintéticas), cada una en su grafo con nombre; es idempotente y queda en la auditoría como `dataset_published` con actor `cli`.
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

### Defectos conocidos

Ninguno: no hay pruebas marcadas como `xfail`. Los hallazgos QA-G2-01 a QA-G2-04 de la revisión de la fase 2 (IRIs no válidas, anidamiento extremo, autenticación antes del cuerpo y lectura limitada a los grafos publicados) están corregidos y sus pruebas pasan, aquí y en `backend/tests/test_security_fase2.py`. Un defecto nuevo se marcaría con `xfail` estricto y su identificador hasta que el agente dueño lo corrija.

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
| Estas pruebas en CI | La rama de `infra` de la fase 2 propone un job `e2e`; está pendiente de la decisión del responsable (decisión abierta 25) | `infra` |
| Pantallas en un navegador real | No hay herramienta decidida; la prueba no ejecuta el JavaScript del frontend | `qa`, `frontend` |
| QA-G2-05 · El catálogo RDF tras publicar por la API | `POST /datasets` no añade la serie a `dcat:dataset` del grafo del catálogo, que solo cambia con `load-semantic` | `backend`, `semantico` |
| QA-G2-06 · Búsqueda por URI | El campo de búsqueda dice «Título, concepto o URI», pero `q` solo busca en título, descripción y temas | `frontend`, `backend` |
| QA-G2-07 · Paginación del catálogo | La pantalla pide una sola página de 100 recursos; con más, el contador muestra el total pero faltan tarjetas | `frontend` |
