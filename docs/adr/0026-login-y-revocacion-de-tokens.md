# 0026. Límite de intentos de login y revocación de tokens

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

El login es público y emite JWT (ADR 0011, ADR 0015). Sin límite de intentos permite probar contraseñas sin freno, y sin revocación un token de un usuario dado de baja sigue valiendo hasta que caduca.

## Decisión

El responsable del proyecto ha decidido (decisión 18 de `Plan.md`):

- **Bloqueo por intentos.** Cinco fallos en 15 minutos para el mismo par (usuario, IP) bloquean ese par durante 15 minutos. El quinto fallo responde todavía 401; el bloqueo empieza en el intento siguiente, que recibe 429 con cabecera `Retry-After`. El bloqueo se aplica aunque la contraseña sea correcta, y un login correcto pone a cero el contador de ese par. El orquestador propuso estos valores y el responsable los aceptó.
- **Valores configurables.** Van por variables de entorno (`LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_MINUTES`, `LOGIN_LOCKOUT_MINUTES`), con esos valores por defecto.
- **Auditoría.** `login_failure` guarda el `username` intentado, truncado y sin caracteres de control. No guarda contraseñas ni tokens.
- **Revocación.** Una baja invalida todos los tokens emitidos antes. El contrato de la fase 4 lo implementa con un campo `users.tokens_valid_after`: un token con `iat` anterior da 401. También se actualiza al cambiar la contraseña o el rol. Reactivar una cuenta no revive los tokens viejos.

Los contadores van en PostgreSQL, para que valgan con varios procesos del backend.

## Consecuencias

- Un atacante no puede probar contraseñas libremente. Un usuario legítimo puede quedar bloqueado 15 minutos si falla cinco veces.
- Registrar el `username` de los fallos ayuda a detectar ataques, pero guarda un texto que escribe el cliente: por eso se trunca y se sanea.
- Una baja o un cambio de rol surten efecto de inmediato, sin esperar a la caducidad del JWT.
- El esquema de PostgreSQL crece con una migración.
- Relacionado: [0007](0007-postgresql-usuarios-auditoria.md), [0011](0011-roles-de-usuario.md), [0015](0015-alta-de-usuarios.md).
