# 0018. `dcat:accessURL` de las distribuciones

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Cada distribución de un dataset necesita un `dcat:accessURL`. Las URIs del repositorio son persistentes y se construyen a partir de `BASE_URI` (ADR 0006). Las distribuciones se guardan en disco o en R2 según la configuración (ADR 0008), y algunas serán restringidas.

## Decisión

El responsable del proyecto ha decidido que el `dcat:accessURL` de una distribución es la URI de la propia distribución, construida a partir de `BASE_URI`. El backend resuelve esa URI y aplica el control de acceso por rol. La descarga restringida llega en la fase 4.

## Consecuencias

- La URL no depende de dónde esté almacenado el fichero, así que cambiar de disco a R2 no rompe los enlaces.
- El acceso se controla siempre en el backend, también para las distribuciones públicas.
- Hasta la fase 4 no se implementa la descarga restringida.
- Relacionado: [0006](0006-base-uri-configurable.md), [0008](0008-almacenamiento-disco-y-r2.md), [0011](0011-roles-de-usuario.md).
