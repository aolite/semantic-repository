# 0017. El admin hereda los permisos de editor

## Estado

Aceptada

## Fecha

2026-11-14

## Contexto

El ADR 0011 define los roles sin jerarquía entre ellos. Al empezar la fase 2, el admin necesita poder publicar y versionar recursos sin tener además el rol de editor.

## Decisión

El responsable del proyecto ha decidido que el admin hereda los permisos de editor. Esta decisión modifica el ADR 0011 en el sentido de que ya no es cierto que no haya jerarquía. El resto de roles no hereda nada mientras no se decida otra cosa: el editor no hereda del miembro, ni el miembro del lector.

## Consecuencias

- Las rutas que admiten al editor admiten también al admin.
- Las rutas que admiten solo al miembro no admiten al editor ni al admin por herencia; cada ruta enumera los roles que admite.
- Las pruebas de autorización por rol (ADR 0010) deben cubrir la herencia admin→editor.
- Relacionado: [0011](0011-roles-de-usuario.md).
