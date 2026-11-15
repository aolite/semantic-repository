# 0028. Búsqueda por URI y 303 al HTML en las URIs persistentes

## Estado

Aceptada

## Fecha

2026-11-15

## Contexto

Las pruebas de las fases 2 y 3 detectaron dos comportamientos que no encajan con lo esperado:

- El parámetro `q` del catálogo y de los vocabularios buscaba también en el espacio de nombres declarado del recurso. Con el `BASE_URI` por defecto, `q=itot` devolvía todo.
- Una URI persistente sin cabecera `Accept` devolvía Turtle, de modo que un navegador o un cliente genérico veía RDF crudo.

## Decisión

El responsable del proyecto ha decidido (decisiones 30 y 31 de `Plan.md`):

- **Búsqueda.** `q`, en `/datasets` y en `/vocabularies`, busca en título, descripción, temas o etiquetas y en la URI completa del recurso (subcadena, sin distinguir mayúsculas). Ya no busca en el espacio de nombres declarado. El texto «Título, concepto o URI» del prototipo se mantiene.
- **Negociación de contenido.** En las URIs persistentes (`/dataset/…`, `/onto/…`, `/vocab/…`), sin `Accept`, con `*/*` o con `text/html`, la respuesta es un 303 a la pantalla del frontend. Solo un `Accept` de RDF (Turtle, JSON-LD, RDF/XML) devuelve RDF.

## Consecuencias

- Los clientes que dependían de recibir Turtle sin `Accept` deben pedirlo. Cambia el comportamiento de la fase 2, y `qa` actualiza la e2e de G3.
- Un navegador que sigue una URI persistente llega a la ficha, que es lo esperado en datos enlazados.
- La búsqueda por URI es más precisa: una subcadena de la URI del recurso ya no coincide con todos los recursos que comparten espacio de nombres.
- Relacionado: [0006](0006-base-uri-configurable.md), [0018](0018-access-url-de-distribuciones.md).
