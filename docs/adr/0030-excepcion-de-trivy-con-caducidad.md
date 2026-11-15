# 0030. Excepción de Trivy con caducidad

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Trivy forma parte de las herramientas de seguridad del CI (ADR 0013). Un hallazgo sin corrección disponible bloquea el CI y obliga a decidir entre ignorarlo y esperar.

## Decisión

El responsable del proyecto ha decidido (decisión 39 de `Plan.md`) gestionar las excepciones de Trivy en un fichero `.trivyignore.yaml`, que se introduce en la PR #24. Cada excepción lleva fecha de caducidad. La fecha de la excepción actual es 2027-02-15: la caducidad fue propuesta por el orquestador y el responsable la aceptó.

Esta fase no toca ese fichero. Al llegar la fecha hay que revisar la excepción: retirarla si ya hay corrección, o renovarla con motivo y nueva fecha. El procedimiento está en [operacion.md](../operacion.md).

## Consecuencias

- Una excepción no queda abierta indefinidamente: al caducar, el CI vuelve a fallar con el hallazgo.
- Hay una revisión pendiente con fecha fija.
- `qa` propone una prueba de guarda del fichero (PR #24).
- Relacionado: [0013](0013-herramientas-seguridad-fase-1.md).
