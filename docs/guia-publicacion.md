# Guía de publicación

Guía para el equipo de la Unidad IT&OT Security: cómo entrar en el repositorio semántico y cómo publicar, mover y dar de baja catálogos, datasets, vocabularios SKOS y ontologías desde la aplicación.

Los nombres de botones, títulos y mensajes de esta guía son los que muestra la interfaz en el código actual (`frontend/src`).

> **Nota: los formularios son propuestas.** El prototipo de diseño solo dibuja los botones «Publicar recurso» e «Importar SKOS». Los formularios, menús, diálogos y mensajes de publicación, edición, traslado y baja los ha propuesto `frontend` y el código los marca como [PROPUESTA]: pueden cambiar de texto y de disposición. Si algo de esta guía no coincide con lo que ves, manda la interfaz; avisa para actualizar la guía.

Esta guía describe lo que hace el repositorio hoy. Las plantillas de metadatos con licencia, punto de contacto y demás campos precargados siguen pendientes (ver [`README.md`](README.md)): hasta que el responsable aporte los valores reales, esos campos se quedan como placeholders (`[LICENCIA]`, `[CONTACTO]`…) y no se rellenan con valores inventados.

## Cómo entrar

1. Pulsa **Iniciar sesión** (barra lateral) para abrir `/login`.
2. Escribe el usuario y la contraseña y pulsa **Iniciar sesión**.
3. Las cuentas las da de alta un admin desde la API; no hay registro propio ([ADR 0015](adr/0015-alta-de-usuarios.md)). Pide una cuenta al admin de la unidad.

Para salir, **Cerrar sesión**. La sesión caduca (60 minutos por defecto, `JWT_EXPIRE_MINUTES`): si ves «La sesión ha caducado o no es válida. Vuelve a iniciar sesión.», vuelve a entrar.

Sin sesión puedes consultar todo lo público: el catálogo, las fichas, los vocabularios y la consola SPARQL, con límites de frecuencia.

## Qué puede hacer cada rol

| Rol | Qué puede hacer |
|---|---|
| Lector (anónimo) | Ver lo público: catálogos, datasets, vocabularios, ontologías y su RDF. Usar la consola SPARQL (solo lectura, con límites). Descargar las distribuciones abiertas |
| Miembro | Lo del lector, más descargar distribuciones restringidas («Iniciar sesión para descargar») y guardar consultas SPARQL propias. **No ve los botones de publicar, editar ni dar de baja** |
| Editor | Lo del miembro, más crear, editar, mover y dar de baja catálogos, datasets, vocabularios y ontologías, y publicar versiones y sustituir ontologías externas |
| Admin | Lo del editor, más gestionar usuarios (`/users` en la API) |

Los botones de escritura solo aparecen con rol editor o admin. Si un miembro intenta una escritura por la API, recibe 403.

## Antes de empezar

- **Slug.** Es el identificador corto de un recurso y forma parte de su URI. Solo admite minúsculas sin acentos, dígitos y guiones, sin guion al principio ni al final. **No se puede cambiar después** y **un slug dado de baja no se reutiliza nunca**. El formulario te muestra la URI que resultará.
- **Idioma.** Título y descripción se guardan solo en español en el piloto.
- **Las URIs** se forman con la `BASE_URI` del despliegue; no las escribas a mano en los ficheros.
- **Los ficheros RDF** (versiones de dataset, vocabularios, ontologías) pueden ser **Turtle** (`.ttl`) o **JSON-LD** (`.jsonld` o `.json`). Antes de publicar, el repositorio los valida con las formas SHACL: si fallan, no se publica nada.
- **Las versiones publicadas no se pueden modificar** ([ADR 0027](adr/0027-versiones-inmutables.md)). Para cambiar algo se publica una versión nueva.
- **Lo restringido.** Los datasets de proyectos de defensa solo publican metadatos; sus distribuciones se quedan en la infraestructura de Eurecat.
- El piloto es solo con datos sintéticos.

## Crear un catálogo

Cada dataset, vocabulario y ontología pertenece a **un solo** catálogo, así que primero hace falta uno. Los catálogos se crean desde dos sitios:

- En **Catálogos** (`/catalogos`), con el botón **Nuevo catálogo**.
- En la pantalla **Catálogo**, con **Publicar recurso**, opción **Nuevo catálogo**.

Rellena el formulario **Nuevo catálogo**:

| Campo | Notas |
|---|---|
| Slug | Obligatorio. Ver «Antes de empezar» |
| Título (en español) | Obligatorio |
| Descripción (en español) | Obligatoria |
| Publicador | Obligatorio |

Pulsa **Crear catálogo**. Verás «Catálogo creado.» en la ficha del catálogo. Para cambiar el título, la descripción o el publicador más tarde, entra en la ficha y usa **Editar catálogo** (el slug no cambia).

El catálogo raíz es fijo: no se crea, edita ni borra desde la aplicación.

## Publicar un dataset y una versión nueva

Un dataset es una **serie** con versiones. Se publica en dos pasos.

**1. Crear el dataset.** En **Publicar recurso**, elige **Nuevo dataset** (o hazlo desde la ficha de un catálogo, ver más abajo). Formulario **Nuevo dataset**:

| Campo | Notas |
|---|---|
| Slug | Obligatorio |
| Título (en español) | Obligatorio |
| Descripción (en español) | Obligatoria |
| Publicador (opcional) | |
| Catálogo | Obligatorio: «Elige un catálogo». «Cada dataset está en un solo catálogo. Después se puede mover sin cambiar sus URIs.» |

Pulsa **Crear dataset**. Verás «Dataset creado. Publica su primera versión con «Nueva versión».»

**2. Publicar una versión.** En la ficha del dataset, pulsa **Nueva versión**. El formulario pide el **Fichero RDF (Turtle o JSON-LD)**: el RDF de **la serie completa**, es decir, sus metadatos, **todas las versiones ya publicadas sin cambios** y la versión nueva, con sus distribuciones, procedencia PROV-O y temas. Pulsa **Publicar versión**.

- Resultado: «RDF publicado. Versiones de la serie: …». Si el RDF era idéntico al publicado: «El RDF era idéntico al publicado: no ha cambiado nada.» Si el RDF describe otra serie, la aplicación te lleva a la ficha de esa serie.
- Una versión nueva se evalúa con F-UJI en segundo plano; la puntuación FAIR aparece en la ficha cuando termina.
- Si el dataset ya está en otro catálogo y mandas un catálogo distinto, da 409: mover es explícito (ver «Mover un recurso de catálogo»).
- Como modelo de RDF, los ficheros de `semantic/data/sintetico/` son los datasets sintéticos de demostración.

**Ficheros de las distribuciones.** El formulario de versión solo sube el RDF: «Los ficheros de las distribuciones se suben aparte». La interfaz no tiene un formulario para ello; se suben con la API (`PUT /datasets/{slug}/versions/{version}/distributions/{distribución}/file`, documentada en `/docs`), hasta `MAX_UPLOAD_MB` (512 MB por defecto). Una distribución `NON_PUBLIC` no admite fichero.

**Editar los metadatos.** **Editar** en la ficha cambia título, descripción y publicador (y el catálogo, ver abajo). Si vacías el publicador, se conserva el actual.

## Publicar un vocabulario SKOS e «Importar SKOS»

Se sube un esquema SKOS (`skos:ConceptScheme`) con sus conceptos, en Turtle o JSON-LD.

- **Importar SKOS** (botón de la pantalla Catálogo y de la ficha de un catálogo) y **Publicar recurso → Nuevo vocabulario** abren **el mismo formulario**, con el mismo botón **Publicar esquema**. La diferencia es solo el título: «Importar SKOS» o «Nuevo vocabulario».
- Campos: **Fichero RDF (Turtle o JSON-LD)** y **Catálogo** («Elige un catálogo»; en la ficha de un catálogo ya viene fijado).
- Resultado: «Esquema publicado con N conceptos.» y la aplicación te lleva al Navegador SKOS del esquema.

**Republicar.** Si el esquema ya existe, se republica y el aviso es «Esquema republicado con N conceptos.». También puedes hacerlo desde la ficha del esquema, con **Republicar**. El fichero tiene que traer **todos los conceptos ya publicados**: un concepto no se quita, **se retira marcándolo con `owl:deprecated`** (y sus sustitutos con `dct:isReplacedBy`). Un concepto retirado no se puede reactivar.

**Editar.** En el Navegador SKOS, **Editar** cambia el título, la descripción y el publicador, solo en español, y el catálogo. Las etiquetas en otros idiomas y los conceptos no cambian: los conceptos se cambian republicando.

Los esquemas auxiliares (`vocab/dominio`, `vocab/tipo-dataset`) no se gestionan desde la aplicación: no verás estos botones en ellos.

## Publicar una ontología propia y una versión

- **Publicar recurso → Nueva ontología**: sube una versión de una ontología propia (`owl:Ontology` con un `owl:versionIRI`) en Turtle o JSON-LD, y elige el catálogo. Botón **Publicar ontología**.
- En la ficha de una ontología que ya existe, **Nueva versión** pide el fichero con un `owl:versionIRI` que **no esté publicado**. Botón **Publicar versión**.

El repositorio valida con SHACL y **calcula las métricas y la consistencia** de la ontología antes de publicarla. Avisos: «Versión X de la ontología publicada.» o, si ya existía la ontología, «Versión X de la ontología sustituida.». Las versiones publicadas no se pueden modificar. Los metadatos de una ontología van en cada versión, así que para cambiarlos hay que publicar una versión nueva; en la ficha solo se puede **Mover de catálogo**.

El prefijo VANN (`vann:preferredNamespacePrefix`) de una ontología o esquema no puede coincidir con el de otro recurso publicado (tampoco con el de una ontología externa), ni con el de uno dado de baja.

## Sustituir una ontología externa

Las ontologías externas (las de otros organismos) quedan **fuera de los catálogos**. No se editan campo a campo ni se dan de baja: solo se **sustituyen enteras**, y cada sustitución genera una **versión nueva** que pasa a ser la actual. Las versiones anteriores no cambian ([ADR 0039](adr/0039-sustitucion-de-ontologias-externas-por-versiones.md)).

1. Abre la ficha de la ontología externa (`/ontologias/externas/{slug}`).
2. Pulsa **Sustituir ontología**. El diálogo avisa de qué versión se generará.
3. Rellena el formulario:

   | Campo | Notas |
   |---|---|
   | Fichero de la ontología (Turtle o JSON-LD) | «El fichero completo, tal como lo publica su organismo». Debe declarar la ontología con su IRI oficial (`owl:Ontology`) |
   | Título (en español) | Obligatorio; viene relleno con el actual |
   | Descripción (en español, opcional) | |
   | Versión del publicador (opcional) | La que le da su organismo (`owl:versionInfo`) |
   | Prefijo | Obligatorio. Minúsculas sin acentos y dígitos, empezando por una letra |
   | Espacio de nombres | Obligatorio. URI completa que empiece por `http://` o `https://` |
   | Publicador (opcional) | |
   | Notas de la versión (en español, opcional) | Qué cambia respecto a la versión anterior |

4. Pulsa **Sustituir ontología**. Verás «Ontología sustituida: se ha generado la versión N, que pasa a ser la actual.»

## Publicar desde la ficha de un catálogo

La ficha de un catálogo (`/catalogos/{slug}`) lleva los mismos botones que la pantalla Catálogo: **Importar SKOS** y **Publicar recurso**, pero con el catálogo ya fijado.

- El menú **Publicar recurso** ofrece **Nuevo dataset**, **Nuevo vocabulario** y **Nueva ontología**. No hay «Nuevo catálogo»: los catálogos no agrupan otros catálogos.
- Los formularios dicen «… en este catálogo» (por ejemplo, «Nuevo dataset en este catálogo») y muestran «Catálogo: …» en lugar del selector.
- La ficha lista los datasets, los vocabularios SKOS y las ontologías del catálogo, y tiene **Editar catálogo** y **Dar de baja**.

## Mover un recurso de catálogo

Cada recurso está en un solo catálogo. Mover un recurso **no cambia sus URIs ni sus versiones publicadas**.

- **Dataset:** en su ficha, **Editar**, y cambia el selector **Catálogo**. Aviso: «Cambios guardados. El dataset se ha movido de catálogo.»
- **Vocabulario SKOS:** en el Navegador SKOS, **Editar**, y cambia el selector **Catálogo**. Aviso: «Cambios guardados. El esquema se ha movido de catálogo.»
- **Ontología propia:** en su ficha, **Mover de catálogo**; elige el **Catálogo de destino** y pulsa **Mover**. Aviso: «La ontología se ha movido de catálogo.» Si eliges el mismo catálogo: «Elige un catálogo distinto del actual.»

## Dar de baja

**Dar de baja** (botón rojo de contorno en las fichas de catálogo, dataset, vocabulario y ontología) pide confirmación en un diálogo. La baja es un **borrado lógico**, no físico:

- El recurso **deja de aparecer en los listados y en las consultas SPARQL**.
- Su URI **responde 410 Gone** con una ficha mínima, en lugar de un error genérico. Es la **lápida**: título, URI, fecha de baja (`prov:invalidatedAtTime`) y estado `adms:status` Withdrawn. Si la fecha no está disponible, la ficha muestra el placeholder `[FECHA]`.
- Su **slug no se puede reutilizar** (y, en esquemas y ontologías, tampoco su prefijo VANN).
- **Datasets:** se eliminan los **ficheros de todas sus distribuciones**.
- Solo el catálogo, el dataset (serie), el esquema y la ontología tienen lápida. Sus versiones, conceptos, distribuciones y ficheros responden 410 por arrastre.
- La aplicación no tiene una acción para deshacer una baja.

Cuándo no se puede (409):

- **Catálogo con contenido.** Solo se da de baja un catálogo vacío. Mueve o da de baja antes sus datasets, vocabularios y ontologías. El diálogo lista los que siguen dentro.
- **409 «en uso»** (esquemas y ontologías). Un recurso no se puede dar de baja si otros recursos **vivos** dependen de él, para no dejar referencias rotas en versiones publicadas, que no cambian. Cuenta como uso, entre otros casos:
  - un concepto de un esquema que es tema (`dcat:theme`) de una versión de dataset vivo;
  - un concepto que es sujeto (`dct:subject`) de una ontología viva, o destino de `skos:related` o de una correspondencia (`*Match`) desde otro esquema vivo, o sustituto (`dct:isReplacedBy`) desde otro esquema vivo;
  - una ontología que otra ontología viva importa (`owl:imports`) o cuyos términos usa, o a la que una versión de dataset viva se ajusta (`dct:conformsTo`).

  El diálogo muestra la lista «Recursos que lo usan». Para darlo de baja, primero hay que dar de baja los que lo usan.

## Errores típicos

Los mensajes son los que ve el usuario.

| Dónde | Mensaje | Qué hacer |
|---|---|---|
| Cualquier formulario | «La sesión ha caducado o no es válida. Vuelve a iniciar sesión.» | Entra de nuevo |
| Cualquier formulario | «Tu cuenta no tiene permiso para esta acción: hace falta el rol editor o admin.» | Pide el rol al admin |
| Cualquier formulario | «No se ha podido conectar con la API.» | Reintenta; si persiste, avisa a quien opera el servidor |
| Cualquier formulario | «El repositorio no está disponible ahora mismo. Inténtalo más tarde.» (503) | Espera |
| Cualquier formulario | «El servidor está ocupado; inténtalo de nuevo en unos segundos.» | Otra persona está escribiendo; reintenta |
| Login | «Introduce el usuario y la contraseña.» / «Usuario o contraseña incorrectos.» | Corrige los datos |
| Login | «No se ha podido iniciar sesión. Inténtalo de nuevo más tarde.» | Con varios fallos seguidos, el par usuario e IP se bloquea unos minutos (15 por defecto), aunque la contraseña sea correcta: espera |
| Slug | «Solo minúsculas sin acentos, dígitos y guiones, sin guion al principio ni al final.» | Corrige el slug |
| Slug | «Ya existe un recurso con ese slug. Elige otro.» (409) | Elige otro slug |
| Slug | «Ese slug es de un recurso dado de baja y no se reutiliza. Elige otro.» (409) | Elige otro slug |
| Campos | «Este campo es obligatorio.» / «Revisa los campos marcados.» | Rellena los campos marcados |
| Fichero | «Elige un fichero Turtle (.ttl) o JSON-LD (.jsonld).» | Revisa la extensión |
| Fichero | «Formato no admitido: sube un fichero Turtle (.ttl) o JSON-LD (.jsonld).» (415) | Ídem |
| Fichero | «El fichero supera el tamaño máximo que admite la API.» (413) | Reduce el fichero (RDF: 10 MiB por defecto) |
| Catálogo | «Elige el catálogo en el que se publica.» | Elige uno en el selector |
| Catálogo | «Todavía no hay catálogos: crea uno antes de publicar.» | Crea un catálogo |
| Catálogo | «El catálogo indicado no existe o se dio de baja.» | Elige otro |
| Catálogo | «El catálogo todavía tiene datasets, vocabularios u ontologías. Muévelos a otro catálogo (desde su ficha) o dalos de baja antes.» | Vacía el catálogo |
| RDF | «El RDF tiene errores de sintaxis.» | Valida el fichero |
| RDF | «La estructura del RDF no es válida para el recurso que se publica.» | Revisa que describe el recurso correcto |
| RDF | «Alguna URI no sigue el patrón del repositorio.» | Usa la `BASE_URI` |
| RDF | «Los datos no cumplen las reglas de validación (SHACL).» | Mira la lista de incidencias bajo el mensaje |
| RDF | «El RDF supera un límite de la ingesta (tamaño, número de tripletas o tiempo de validación).» | Divide o reduce el RDF |
| Dataset | «Falta una versión ya publicada: el fichero tiene que incluir la serie con todas sus versiones publicadas, sin cambios.» | Incluye todas las versiones |
| Dataset | «Una versión ya publicada viene con otro contenido: las versiones publicadas no se pueden modificar.» | Deja las versiones antiguas como estaban; publica una nueva |
| Dataset | «La serie ya está en otro catálogo. Para cambiarla de catálogo, usa «Editar» en la ficha del dataset.» | Mueve con **Editar** |
| Dataset | «La versión usa temas (dcat:theme) que son conceptos retirados. Cámbialos por sus sustitutos, si los tienen.» | La lista indica los «Sustitutos» |
| Dataset | «La versión usa temas (dcat:theme) del repositorio que no son conceptos de un esquema publicado (no existen o su esquema se dio de baja).» | Usa temas que existan |
| Esquema | «Faltan conceptos que ya estaban publicados en el esquema. Un concepto no se quita: se retira marcándolo con owl:deprecated (y sus sustitutos con dct:isReplacedBy).» | Vuelve a incluirlos |
| Esquema | «Un concepto retirado (owl:deprecated) vuelve a estar activo: reactivar conceptos retirados no está previsto.» | Mantenlo retirado |
| Esquema | «Algún sustituto (dct:isReplacedBy) no es un concepto vivo de este esquema o de otro publicado.» | Corrige el sustituto |
| Esquema u ontología | «El esquema ya está en otro catálogo. Para cambiarlo de catálogo, usa «Editar» en su ficha del Navegador SKOS.» / «La ontología ya está en otro catálogo. Para cambiarla de catálogo, usa «Mover de catálogo» en su ficha.» | Mueve desde la ficha |
| Esquema u ontología | «El prefijo VANN (vann:preferredNamespacePrefix) ya lo usa otro recurso publicado. Usa otro prefijo.» | Cambia el prefijo |
| Esquema u ontología | «El prefijo VANN (vann:preferredNamespacePrefix) era de un recurso dado de baja y no se reutiliza. Usa otro prefijo.» | Cambia el prefijo |
| Esquema u ontología | «Esa URI es de un esquema dado de baja y no se reutiliza.» / «Esa URI es de una ontología dada de baja y no se reutiliza.» | Usa otra URI |
| Ontología externa | «Esta acción no está disponible para este recurso: una ontología externa solo se sustituye entera («Sustituir ontología» en su ficha) y un esquema auxiliar solo cambia con sus ficheros y la carga semántica.» (403) | Usa **Sustituir ontología** |
| Ontología externa | «El fichero no declara la ontología con su IRI oficial (owl:Ontology) o algún campo del formulario no es válido.» | Revisa el fichero y los campos |
| Ontología externa | «El fichero describe recursos con URIs del repositorio: una ontología externa no puede usarlas.» | Usa el fichero oficial |
| Ontología externa | «Otra persona acaba de sustituir esta ontología; recarga la ficha y vuelve a intentarlo.» | Recarga |
| Prefijo y espacio de nombres | «Solo minúsculas sin acentos y dígitos, empezando por una letra.» / «Escribe una URI completa, que empiece por http:// o https://.» | Corrige el campo |
| Baja | «No se puede dar de baja: lo usan recursos publicados. Antes hay que dar de baja los recursos que lo usan (las versiones publicadas no cambian).» (409) | Mira «Recursos que lo usan» |
| Recurso dado de baja | «El recurso se dio de baja.» / ««{título}» se dio de baja.» (410) | El recurso ya no está |
| Recurso inexistente | «El catálogo no existe.», «El dataset no existe.», «El esquema no existe.», «La ontología no existe.» (404) | Recarga y comprueba el enlace |

Los mensajes de validación SHACL y de incidencias llevan debajo una lista de hasta 10 incidencias con el nodo afectado.

## Más información

- Decisiones: [ADR 0037](adr/0037-crud-de-catalogos-y-datasets.md), [0038](adr/0038-vocabularios-y-ontologias-en-los-catalogos.md) y [0039](adr/0039-sustitucion-de-ontologias-externas-por-versiones.md).
- Contrato de URIs y de las lápidas: `semantic/uris.md`.
- Operación del servidor: [`operacion-piloto.md`](operacion-piloto.md).
