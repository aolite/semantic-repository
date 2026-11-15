# Operación

Este documento recoge los procedimientos de operación del entorno local que la fase 4 hace necesarios. La guía completa de operación (arranque, variables de entorno, copias de seguridad, restauración y despliegue) es un entregable de la fase 5 y no está escrita todavía. Para el arranque básico, ver [`infra/README.md`](../infra/README.md).

Los comandos marcados **[PENDIENTE DE INTEGRACIÓN]** dependen de cambios de `infra` y `backend` que aún no están en `main`. El orquestador los completa al integrar la fase.

## Recargar el entorno local desde cero tras la corrección de itot 1.2.0

**Cuándo.** Si tu entorno se cargó con la versión anterior de `semantic/ontologias/itot/1.2.0.ttl`. La corrección añade `IED rdfs:subClassOf ActivoIndustrial` ([ADR 0035](adr/0035-correccion-de-itot-1-2-0.md)). Las versiones son inmutables ([ADR 0027](adr/0027-versiones-inmutables.md)): `load-semantic` sobre un entorno que ya tiene esa versión con otro contenido da 409 `version_immutable`.

**Qué se pierde.** Todo el contenido del entorno local: triplestore, usuarios y auditoría de PostgreSQL y, si borras todos los volúmenes, los ficheros de distribución. Solo es válido para un entorno de desarrollo con datos sintéticos.

Pasos:

1. Para el entorno y borra los volúmenes. `docker compose down -v` borra los tres volúmenes del proyecto: `postgres-data`, `fuseki-data` y `distributions` (ver `infra/README.md`):

   ```bash
   docker compose down -v
   ```

   Si prefieres borrar solo Fuseki y PostgreSQL, el proyecto de Compose se llama `itot`, así que los volúmenes son `itot_fuseki-data` y `itot_postgres-data`. Borra entonces también `itot_distributions`: si PostgreSQL se vacía y el almacenamiento conserva los ficheros, la recarga puede chocar con ficheros ya existentes. **[PENDIENTE DE INTEGRACIÓN]** Confirmar con `backend` el comportamiento de `load-semantic` en ese caso.

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

   **[PENDIENTE DE INTEGRACIÓN]** En la fase 4, `load-semantic` también sube los ficheros sintéticos de distribución ([ADR 0032](adr/0032-ficheros-de-distribucion-sinteticos.md)) y encola la evaluación FAIR de cada versión nueva. Confirmar con `backend` si la salida o los argumentos del comando cambian.

5. **[PENDIENTE DE INTEGRACIÓN]** Comprobar el resultado: métricas de la ontología `itot` 1.2.0 y evaluación FAIR de las versiones. Las métricas nuevas las informa `semantico`.

## Migrar al usuario `backend` de Fuseki

**Cuándo.** En un entorno ya levantado antes de la fase 4, donde el backend escribe en Fuseki con `admin`. Según el contrato de la fase 4, el backend pasa a usar un usuario propio con permiso de escritura en el dataset, y `admin` queda para administración. Las consultas anónimas de solo lectura no cambian.

Pasos, según el contrato:

1. Añade a `.env` la variable `FUSEKI_BACKEND_PASSWORD` con una contraseña propia. En `.env.example` hay un valor ficticio. Evita `/`, `&` y `\`, igual que con `FUSEKI_ADMIN_PASSWORD`: la imagen de Fuseki aplica las contraseñas con `sed`. **[PENDIENTE DE INTEGRACIÓN]** Confirmar la restricción con `infra`.
2. El backend usa `FUSEKI_USER=backend`. **[PENDIENTE DE INTEGRACIÓN]** Confirmar con `infra` si el Compose lo fija o si hay que ponerlo en `.env`.
3. Recrea los servicios para que Fuseki cargue la nueva política (`infra/fuseki/shiro.ini`) y el backend las nuevas credenciales:

   ```
   [PENDIENTE DE INTEGRACIÓN]: comando exacto de infra
   ```

4. Comprueba que el backend sigue publicando y que una escritura anónima en Fuseki se sigue rechazando. **[PENDIENTE DE INTEGRACIÓN]** Comando de comprobación de `infra`.

Los datos del volumen `fuseki-data` no se tocan en esta migración: cambia la política de acceso, no el contenido.

## Revisar la excepción de Trivy al caducar

**Cuándo.** El 2027-02-15 caduca la excepción registrada en `.trivyignore.yaml` ([ADR 0030](adr/0030-excepcion-de-trivy-con-caducidad.md)). El fichero se introduce en la PR #24 y esta fase no lo toca. A partir de esa fecha, el CI vuelve a fallar con el hallazgo si no se revisa.

Pasos:

1. Abre `.trivyignore.yaml` y localiza la excepción y su motivo.
2. Comprueba si ya hay una versión corregida del componente afectado.
3. Si la hay, actualiza el componente y borra la excepción.
4. Si no la hay, decide con el responsable del proyecto si se renueva. Una renovación lleva el motivo y una nueva fecha de caducidad, y se hace por PR.
5. **[PENDIENTE DE INTEGRACIÓN]** Comando para ejecutar Trivy en local y comprobar el resultado, que debe confirmar `infra` o `qa`.
