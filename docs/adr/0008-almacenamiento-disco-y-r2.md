# 0008. Almacenamiento de distribuciones: disco en el MVP y Cloudflare R2 en el despliegue

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

Las distribuciones de los datasets necesitan almacenamiento. En local basta el disco; en el despliegue se quiere almacenamiento de objetos. Los datasets restringidos de defensa solo publican metadatos y sus distribuciones se quedan en infraestructura de Eurecat. La residencia de datos en la UE es criterio excluyente para servicios externos.

## Decisión

- MVP: disco de la máquina (un volumen de Docker).
- Despliegue: Cloudflare R2, compatible con S3, cuando se configure.
- El backend accede a través de una interfaz de almacenamiento con dos implementaciones, disco y R2. Se elige una u otra por configuración, sin cambiar el código.

## Consecuencias

- El backend no depende de una implementación concreta.
- Antes de usar R2 hay que comprobar la residencia de datos en la UE.
- Qué otros componentes pueden alojarse en Cloudflare sigue abierto (decisión 12 de `Plan.md`).
