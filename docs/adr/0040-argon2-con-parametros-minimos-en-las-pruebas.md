# 0040. argon2id con parámetros mínimos en las pruebas del backend

## Estado

Aceptada

## Fecha

2026-11-26

## Contexto

Las contraseñas se guardan con argon2id. Con los parámetros de producción, la batería de pruebas del backend es lenta.

## Decisión

El responsable del proyecto ha decidido (decisión 52 de `Plan.md`):

- Las pruebas usan argon2id con parámetros mínimos, para que la batería sea rápida.
- Producción sigue con `m=65536, t=3, p=4`, valores que fija una prueba.
- Las pruebas que dependen del coste real (tiempo de login, hash de relleno) usan los parámetros de producción.

## Consecuencias

- Una prueba falla si los parámetros de producción cambian sin querer.
- Las pruebas de tiempo de login y de hash de relleno son más lentas que el resto, porque usan el coste real.
- Relacionado: [0026](0026-login-y-revocacion-de-tokens.md), [0010](0010-alcance-pruebas-seguridad.md).
