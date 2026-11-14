# Pruebas de extremo a extremo

## Puerta G1 · entorno local listo

`test_g1_entorno_local.py` levanta el `docker-compose.yml` del repositorio y recorre el criterio de la puerta:

1. Los cuatro servicios de la fase 1 (PostgreSQL, Fuseki, backend y frontend) arrancan y están sanos; las migraciones han creado las tablas.
2. El primer admin se crea con la CLI del backend (`create-admin --password-stdin`).
3. El login devuelve un JWT con el rol, y `/auth/me` responde.
4. El admin da de alta un miembro y un editor; solo el admin gestiona usuarios; nadie se sube el rol; una baja o un cambio de rol se aplican con el token vigente.
5. Todo el recorrido queda en `audit_events`, y ni la auditoría ni los logs contienen contraseñas, tokens o secretos.
6. Al terminar, apaga el entorno y borra sus volúmenes e imágenes.

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
- **Entorno:** no lee ni escribe el `.env` de la raíz. Genera uno temporal a partir de `.env.example` (así comprueba también que `.env.example` documenta todas las variables necesarias), sustituye los secretos por valores aleatorios y, con un fichero de Compose adicional generado en una carpeta temporal, hace que `env_file` apunte a él. Es lo único que cambia respecto al `docker-compose.yml` real.
- **Credenciales:** las contraseñas de PostgreSQL, Fuseki, el secreto JWT y las contraseñas de las cuentas se generan en cada ejecución con `secrets`. No hay ninguna fija ni versionada.
- **Alcance:** todas las peticiones van a `127.0.0.1`. El cliente HTTP de la prueba rechaza cualquier otra URL.

### Pruebas marcadas como `xfail`

Las pruebas con `@pytest.mark.xfail(strict=True)` documentan defectos abiertos, con su gravedad y su agente dueño en el motivo. Mientras el defecto exista aparecen como `xfailed`; cuando se corrija, la prueba pasará, pytest lo marcará como fallo (`XPASS(strict)`) y habrá que quitar la marca.
