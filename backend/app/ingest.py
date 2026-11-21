"""Ingesta de series de dataset DCAT-AP 3: análisis, comprobaciones, SHACL y publicación.

Flujo (compartido por ``POST /datasets`` y ``python -m app.cli load-semantic``):

1. ``parse_rdf``: Turtle o JSON-LD, resolviendo las IRIs relativas contra ``BASE_URI``.
   En JSON-LD se rechazan los contextos remotos (evita que el servidor descargue URLs).
2. ``check_structure``: exactamente una ``dcat:DatasetSeries`` con URI
   ``{BASE_URI}dataset/{slug}``; cada ``dcat:Dataset`` es ``{serie}/{version}``, con
   ``dcat:inSeries`` hacia la serie y ``dcat:version`` igual al último segmento; cada
   distribución cuelga de la URI de su versión. Todo sujeto con IRI cuelga de
   ``BASE_URI`` y, en concreto, de la serie o de ``{BASE_URI}actividad/``: así una
   ingesta no puede reescribir recursos de otra serie ni del vocabulario.
3. ``validate_shacl``: pyshacl con todas las formas de ``SEMANTIC_DIR/shapes`` y, como
   grafo de soporte, ``SEMANTIC_DIR/data/vocab-minimo.ttl``. Sin inferencia y sin cargar
   la ontología DCAT (ver ``semantic/README.md``).
4. ``publish``: sustituye **por completo** el grafo con nombre ``{BASE_URI}dataset/{slug}``
   por el contenido recibido (``PUT`` del Graph Store Protocol). Si el grafo ya tenía
   exactamente el mismo contenido (isomorfo), no se escribe nada.

Reglas de la fase 4:

- **Versiones inmutables (decisión 28).** Antes de escribir, cada versión que ya está en
  el grafo publicado tiene que venir en la petición con el mismo contenido: su subgrafo
  (``catalog.version_subgraph``: sus triples, los de sus distribuciones y su procedencia
  PROV) es isomorfo al publicado (``rdflib.compare.isomorphic``, que trata bien los nodos
  en blanco). Si falta, 409 ``version_removed``; si cambia, 409 ``version_immutable``. Los
  metadatos de la serie sí pueden cambiar y las versiones nuevas se añaden.
- **Catálogos (decisiones 29 y 49).** El grafo que se ingesta lleva exactamente un
  ``<{BASE_URI}catalogo/{slug}> dcat:dataset <serie>`` (forma
  ``itsh:DatasetSeries-catalog``). Es el único triple admitido con un sujeto fuera de la
  serie: se valida con SHACL junto con la serie, pero se guarda en el grafo del catálogo,
  no en el de la serie. El backend comprueba lo que SHACL no ve: que el catálogo existe
  y no está dado de baja (422 ``catalog``) y que la serie no está ya en **otro** catálogo
  (409 ``catalog_conflict``; moverla es ``PATCH /datasets/{slug}``).
- **Bajas (decisión 49).** Un slug dado de baja no se reutiliza: publicar una serie con
  lápida en ``{BASE_URI}bajas`` da 409 ``withdrawn``.
- **FAIR.** Las versiones nuevas (las que no estaban en el grafo publicado) se encolan
  para evaluarlas con F-UJI en segundo plano (``app.fair``).
- **Segmento reservado.** ``fichero`` no puede ser el slug de una distribución: es la ruta
  de su fichero (``{distribución}/fichero``).
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.compare import isomorphic
from rdflib.namespace import RDF
from rdflib.plugins.stores.memory import Memory
from sqlalchemy.orm import Session

from app import audit, shacl_worker
from app.config import ConfigurationError, get_settings
from app.models import AuditAction, User
from app.triplestore import TripleStore
from app.uris import DCAT, Uris, is_slug

SH = Namespace("http://www.w3.org/ns/shacl#")

RdfFormat = Literal["turtle", "json-ld"]
IngestErrorKind = Literal[
    "syntax",
    "structure",
    "uri",
    "shacl",
    "limit",
    "catalog",
    "version_removed",
    "version_immutable",
    "withdrawn",
    "catalog_conflict",
]
# Errores de ingesta que son un conflicto con lo publicado (409) y no un RDF inválido (422).
CONFLICT_KINDS = frozenset(
    {"version_removed", "version_immutable", "withdrawn", "catalog_conflict"}
)
# Qué hace ``publish`` si la serie ya está en otro catálogo: 409 (API), conservar el
# catálogo actual (``load-semantic``) o moverla.
OtherCatalog = Literal["conflict", "keep", "move"]

VOCAB_FILE = Path("data") / "vocab-minimo.ttl"
CATALOG_FILE = Path("data") / "catalogo.ttl"
CATALOGS_DIR = Path("data") / "catalogos"
SYNTHETIC_DIR = Path("data") / "sintetico"
SHAPES_DIR = Path("shapes")
VOCABULARIES_DIR = Path("vocabularios")
ONTOLOGIES_DIR = Path("ontologias")
EXTERNAL_ONTOLOGIES_FILE = ONTOLOGIES_DIR / "externas.ttl"

# Anidamiento máximo admitido en la ingesta: niveles de JSON en JSON-LD y cadenas de
# nodos en blanco anidados en cualquier formato. Un dataset DCAT-AP real usa unos pocos
# niveles (versión -> distribución -> procedencia); 64 deja mucho margen y queda lejos del
# límite de recursión de Python (1000) que usan los analizadores y serializadores.
MAX_NESTING_DEPTH = 64

# Límites del análisis (QA-G3-03, bomba de expansión por prefijos): se comprueban **mientras
# se analiza**, en cada tripleta que el analizador añade al grafo, y se aborta en cuanto se
# superan.
# - IRIs de como mucho 4096 caracteres (ninguna IRI real se acerca; un prefijo de 100 KB
#   repetido sí).
# - Como mucho ``INGEST_MAX_TRIPLES`` tripletas (100 000 por defecto).
# - Tamaño expandido (suma de la longitud de los términos de todas las tripletas) de como
#   mucho 32 veces el tamaño del cuerpo más 1 MiB, y nunca más de 32 Mi caracteres. Un
#   Turtle normal con prefijos expande entre 2 y 10 veces.
MAX_IRI_LENGTH = 4096
RESERVED_DISTRIBUTION_SLUG = "fichero"
DEFAULT_MAX_TRIPLES = 100_000
EXPANSION_FACTOR = 32
EXPANSION_FLOOR = 1024 * 1024
MAX_EXPANDED_CHARS = 32 * 1024 * 1024


@dataclass
class Issue:
    message: str
    focus_node: str | None = None
    path: str | None = None
    value: str | None = None
    severity: str = "Violation"
    source_shape: str | None = None


@dataclass
class IngestError(Exception):
    kind: IngestErrorKind
    detail: str
    issues: list[Issue] = field(default_factory=list)
    report: str | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass
class PreparedSeries:
    slug: str
    uri: str
    graph: Graph  # la serie, sin el triple de pertenencia (va al grafo del catálogo)
    versions: list[str]
    # Catálogo {BASE_URI}catalogo/{slug} del triple de pertenencia (decisión 49). Tras
    # SHACL hay exactamente uno.
    catalog_uri: str | None = None
    catalogs: list[str] = field(default_factory=list)
    base_uri: str | None = None


@dataclass
class PublishResult:
    slug: str
    uri: str
    graph_uri: str
    versions: list[str]
    triples: int
    created: bool
    changed: bool
    new_versions: list[str] = field(default_factory=list)


# --- 1. Análisis -------------------------------------------------------------


def _remote_context(value: Any) -> bool:
    """¿Hay algún ``@context`` o ``@import`` que apunte a un documento externo?"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "@context" and _context_has_reference(item):
                return True
            if _remote_context(item):
                return True
    elif isinstance(value, list):
        return any(_remote_context(item) for item in value)
    return False


def _context_has_reference(context: Any) -> bool:
    if isinstance(context, str):
        return True
    if isinstance(context, list):
        return any(_context_has_reference(item) for item in context)
    if isinstance(context, dict):
        if "@import" in context:
            return True
        return any(_remote_context(item) for item in context.values())
    return False


def _json_depth_exceeds(document: Any, limit: int) -> bool:
    """¿Supera el documento ``limit`` niveles de anidamiento? Iterativo, sin recursión."""
    stack: list[tuple[Any, int]] = [(document, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, dict):
            children = value.values()
        elif isinstance(value, list):
            children = value
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def _too_deep() -> IngestError:
    return IngestError(
        "syntax",
        f"El RDF supera el anidamiento máximo de {MAX_NESTING_DEPTH} niveles",
    )


class _LimitExceededError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _LimitedStore(Memory):
    """Store en memoria que cuenta lo que añade el analizador y aborta al superar los
    límites. Va en el store, y no en ``Graph.add``, porque algunos analizadores (JSON-LD)
    escriben en el store a través de otro objeto ``Graph``."""

    def __init__(self, max_triples: int, max_chars: int) -> None:
        super().__init__()
        self._max_triples = max_triples
        self._max_chars = max_chars
        self._count = 0
        self._chars = 0
        self.limits_active = True

    def add(self, triple: Any, context: Any, quoted: bool = False) -> None:
        if self.limits_active:
            self._check(triple)
        super().add(triple, context, quoted)

    def _check(self, triple: Any) -> None:
        self._count += 1
        if self._count > self._max_triples:
            raise _LimitExceededError(
                f"El RDF supera el máximo de {self._max_triples} tripletas por ingesta"
            )
        for term in triple:
            if isinstance(term, URIRef):
                size = len(term)
                if size > MAX_IRI_LENGTH:
                    raise _LimitExceededError(
                        f"Hay una IRI de {size} caracteres; el máximo es {MAX_IRI_LENGTH}"
                    )
            elif isinstance(term, RdfLiteral):
                size = len(term) + (len(term.datatype) if term.datatype else 0)
            else:
                size = len(str(term))
            self._chars += size
        if self._chars > self._max_chars:
            raise _LimitExceededError(
                "El RDF expandido es demasiado grande para el tamaño del documento "
                f"(más de {self._max_chars} caracteres): revisa los prefijos"
            )


def _limit_error(exc: BaseException) -> _LimitExceededError | None:
    """El límite superado, aunque el analizador lo haya envuelto en otra excepción."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, _LimitExceededError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _new_limited_graph(size: int, max_triples: int) -> Graph:
    max_chars = min(MAX_EXPANDED_CHARS, EXPANSION_FACTOR * size + EXPANSION_FLOOR)
    return Graph(store=_LimitedStore(max_triples, max_chars))


def _stop_limits(graph: Graph) -> None:
    store = graph.store
    if isinstance(store, _LimitedStore):
        store.limits_active = False


def parse_rdf(
    data: bytes,
    rdf_format: RdfFormat,
    base_uri: str,
    *,
    max_triples: int = DEFAULT_MAX_TRIPLES,
) -> Graph:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError("syntax", "El RDF debe estar en UTF-8") from exc
    if rdf_format == "json-ld":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise IngestError(
                "syntax", f"JSON-LD no válido: {exc.msg} (línea {exc.lineno})"
            ) from exc
        except RecursionError as exc:
            raise _too_deep() from exc
        if _json_depth_exceeds(document, MAX_NESTING_DEPTH):
            raise _too_deep()
        if _remote_context(document):
            raise IngestError(
                "syntax",
                "JSON-LD con contextos remotos (@context con URL o @import): no se admiten; "
                "incluye el contexto en el propio documento",
            )
    graph = _new_limited_graph(len(data), max_triples)
    try:
        graph.parse(data=text, format=rdf_format, publicID=base_uri)
    except RecursionError as exc:
        raise _too_deep() from exc
    except Exception as exc:
        limit = _limit_error(exc)
        if limit is not None:
            raise IngestError("limit", limit.message) from None
        raise IngestError("syntax", f"RDF no válido ({rdf_format}): {_short(exc)}") from exc
    _stop_limits(graph)
    if len(graph) == 0:
        raise IngestError("syntax", "El RDF está vacío")
    check_terms(graph)
    return graph


def check_terms(graph: Graph) -> None:
    """IRIs válidas y anidamiento de nodos en blanco acotado (QA-G2-01 y QA-G2-02).

    - Toda IRI del grafo (sujeto, predicado, objeto o tipo de dato de un literal) debe ser
      absoluta y no contener los caracteres que excluyen la producción IRIREF de
      Turtle/N-Triples/SPARQL (espacio, controles, ``<>"{}|^`\\``). rdflib las deja pasar
      al analizar, pero después rompen el N-Triples que se envía a Fuseki o la lectura.
    - Una cadena de nodos en blanco anidados (cada uno referenciado una sola vez, como
      ``[ p [ p [ … ] ] ]``) no puede superar ``MAX_NESTING_DEPTH`` niveles: los
      serializadores los anidan de forma recursiva al devolver el RDF. Las listas RDF
      (``rdf:rest``) no cuentan como anidamiento.
    """
    bad: dict[str, Issue] = {}
    for triple in graph:
        for position, term in zip(("sujeto", "predicado", "objeto"), triple, strict=True):
            candidates = [term]
            if isinstance(term, RdfLiteral) and term.datatype is not None:
                candidates = [term.datatype]
            for candidate in candidates:
                if isinstance(candidate, URIRef) and not _valid_iri(str(candidate)):
                    key = str(candidate)
                    bad.setdefault(
                        key,
                        Issue(
                            "IRI no válida: debe ser absoluta y no puede contener espacios, "
                            'caracteres de control ni <>"{}|^`\\',
                            focus_node=None if position == "sujeto" else _node_text(triple[0]),
                            value=repr(key)[1:-1],
                        ),
                    )
    if bad:
        raise IngestError("uri", "Hay IRIs no válidas", list(bad.values()))

    # Padre único de cada nodo en blanco que solo aparece una vez como objeto.
    parents: dict[BNode, Any] = {}
    seen_twice: set[BNode] = set()
    for subject, predicate, obj in graph:
        if isinstance(obj, BNode) and predicate != RDF.rest:
            if obj in parents:
                seen_twice.add(obj)
            parents[obj] = subject
    for node in seen_twice:
        parents.pop(node, None)
    for start in parents:
        depth, node = 0, start
        visited: set[Any] = set()
        while isinstance(node, BNode) and node in parents and node not in visited:
            visited.add(node)  # un ciclo de nodos en blanco no es anidamiento infinito
            depth += 1
            if depth > MAX_NESTING_DEPTH:
                raise _too_deep()
            node = parents[node]


_IRI_FORBIDDEN = re.compile(r'[<>"{}|^`\\\x00-\x20\x7f]')
_IRI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _valid_iri(value: str) -> bool:
    return bool(_IRI_SCHEME.match(value)) and not _IRI_FORBIDDEN.search(value)


def _short(exc: Exception, limit: int = 300) -> str:
    message = " ".join(str(exc).split())
    return message[:limit] + ("…" if len(message) > limit else "")


# --- 2. Estructura y URIs ----------------------------------------------------


def check_structure(graph: Graph, uris: Uris) -> PreparedSeries:
    series_nodes = sorted(set(graph.subjects(RDF.type, DCAT.DatasetSeries)), key=str)
    if len(series_nodes) != 1:
        raise IngestError(
            "structure",
            f"Se espera exactamente una dcat:DatasetSeries por ingesta; hay {len(series_nodes)}",
        )
    series = series_nodes[0]
    if not isinstance(series, URIRef):
        raise IngestError("uri", "La dcat:DatasetSeries debe tener IRI, no un nodo en blanco")
    series_uri = str(series)
    slug = uris.series_slug(series_uri)
    if slug is None or not is_slug(slug):
        raise IngestError(
            "uri",
            f"La URI de la serie debe ser {uris.dataset_ns}{{slug}} (slug en minúsculas, dígitos "
            "y guiones)",
            [Issue("URI de serie fuera del patrón", focus_node=series_uri)],
        )

    issues: list[Issue] = []
    versions: list[str] = []
    version_prefixes: dict[str, str] = {}
    for node in sorted(set(graph.subjects(RDF.type, DCAT.Dataset)), key=str):
        if not isinstance(node, URIRef):
            issues.append(Issue("Cada dcat:Dataset (versión) necesita IRI", focus_node=str(node)))
            continue
        version = uris.version_from_uri(series_uri, str(node))
        if version is None:
            issues.append(
                Issue(
                    f"La URI de una versión debe ser {series_uri}/{{MAYOR.MENOR.PARCHE}}",
                    focus_node=str(node),
                )
            )
            continue
        declared = [str(v) for v in graph.objects(node, DCAT.version)]
        if declared and declared != [version]:
            issues.append(
                Issue(
                    "dcat:version no coincide con el último segmento de la URI",
                    focus_node=str(node),
                    path=str(DCAT.version),
                    value=", ".join(declared),
                )
            )
        in_series = list(graph.objects(node, DCAT.inSeries))
        if in_series and in_series != [series]:
            issues.append(
                Issue(
                    "dcat:inSeries debe apuntar a la serie de esta ingesta",
                    focus_node=str(node),
                    path=str(DCAT.inSeries),
                    value=", ".join(str(v) for v in in_series),
                )
            )
        versions.append(version)
        version_prefixes[str(node)] = f"{node}/"

    for version_node in version_prefixes:
        for dist in graph.objects(URIRef(version_node), DCAT.distribution):
            if not isinstance(dist, URIRef):
                continue
            prefix = version_prefixes[version_node]
            if not str(dist).startswith(prefix):
                issues.append(
                    Issue(
                        "Una distribución debe colgar de la URI de su versión ({version}/{dist})",
                        focus_node=str(dist),
                    )
                )
                continue
            segment = str(dist)[len(prefix) :]
            if not is_slug(segment):
                issues.append(
                    Issue(
                        "El último segmento de una distribución ({version}/{dist}) debe ser un "
                        "slug",
                        focus_node=str(dist),
                    )
                )
            elif segment == RESERVED_DISTRIBUTION_SLUG:
                issues.append(
                    Issue(
                        f"'{RESERVED_DISTRIBUTION_SLUG}' es un segmento reservado (la ruta del "
                        "fichero de la distribución): no puede ser el slug de una distribución",
                        focus_node=str(dist),
                    )
                )

    # Pertenencia (decisión 49): «<{BASE_URI}catalogo/{slug}> dcat:dataset <serie>» es el
    # único triple admitido con un catálogo como sujeto.
    catalogs: list[str] = []
    membership: list[tuple] = []
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value == uris.root_catalog:
            issues.append(
                Issue(
                    "El catálogo raíz no lista series: la serie pertenece a un catálogo "
                    f"{uris.catalog_ns}{{slug}}",
                    focus_node=value,
                )
            )
            continue
        if uris.catalog_slug(value) is None:
            continue
        for _, predicate, obj in graph.triples((subject, None, None)):
            if predicate == DCAT.dataset and obj == series:
                membership.append((subject, predicate, obj))
                catalogs.append(value)
            else:
                issues.append(
                    Issue(
                        "Del catálogo solo se admite «<catálogo> dcat:dataset <serie>»: sus "
                        "metadatos se editan en /catalogs/{slug}",
                        focus_node=value,
                        path=str(predicate),
                    )
                )

    allowed_prefixes = (f"{series_uri}/", uris.activity_ns)
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value == series_uri or value.startswith(allowed_prefixes):
            continue
        if value == uris.root_catalog or uris.catalog_slug(value) is not None:
            continue
        if not value.startswith(uris.base):
            message = "El recurso no cuelga de BASE_URI"
        else:
            message = (
                "Una ingesta de serie solo puede describir la serie, sus versiones y "
                "distribuciones, y actividades PROV ({BASE_URI}actividad/…)"
            )
        issues.append(Issue(message, focus_node=value))

    if issues:
        raise IngestError("uri", "Hay recursos con URIs fuera del patrón", issues)
    versions.sort(key=lambda v: tuple(int(p) for p in v.split(".")))
    series_graph = graph
    if membership:
        series_graph = Graph()
        for prefix, namespace in graph.namespaces():
            series_graph.bind(prefix, namespace, override=True, replace=True)
        for triple in graph:
            if triple not in membership:
                series_graph.add(triple)
    return PreparedSeries(
        slug=slug,
        uri=series_uri,
        graph=series_graph,
        versions=versions,
        catalog_uri=catalogs[0] if len(catalogs) == 1 else None,
        catalogs=sorted(catalogs),
        base_uri=uris.base,
    )


def add_membership(graph: Graph, uris: Uris, catalog_slug: str) -> Graph:
    """Añade «<{BASE_URI}catalogo/{slug}> dcat:dataset <serie>» antes de validar
    (``POST /datasets?catalog={slug}``). Si el RDF ya declara otro catálogo, 422."""
    series = [s for s in graph.subjects(RDF.type, DCAT.DatasetSeries) if isinstance(s, URIRef)]
    if len(series) != 1:
        return graph  # check_structure dará el error
    catalog = URIRef(uris.catalog(catalog_slug))
    declared = {c for c in graph.subjects(DCAT.dataset, series[0]) if c != catalog}
    if declared:
        raise IngestError(
            "catalog",
            "El RDF declara otro catálogo que el parámetro catalog",
            [Issue("Catálogo distinto del parámetro", focus_node=str(c)) for c in sorted(declared)],
        )
    graph.add((catalog, DCAT.dataset, series[0]))
    return graph


# --- 3. SHACL ----------------------------------------------------------------


@lru_cache(maxsize=4)
def _load_shapes(semantic_dir: Path, base_uri: str) -> Graph:
    shapes_dir = semantic_dir / SHAPES_DIR
    files = sorted(shapes_dir.glob("*.ttl"))
    if not files:
        raise FileNotFoundError(f"No hay formas SHACL en {shapes_dir}")
    shapes = Graph()
    for path in files:
        shapes.parse(path, format="turtle", publicID=base_uri)
    return shapes


@lru_cache(maxsize=4)
def _load_support(semantic_dir: Path, base_uri: str) -> Graph | None:
    path = semantic_dir / VOCAB_FILE
    if not path.is_file():
        return None
    graph = Graph()
    graph.parse(path, format="turtle", publicID=base_uri)
    return graph


@lru_cache(maxsize=4)
def _shapes_nt(semantic_dir: Path, base_uri: str) -> bytes:
    return _load_shapes(semantic_dir, base_uri).serialize(format="nt", encoding="utf-8")


@lru_cache(maxsize=4)
def _support_nt(semantic_dir: Path, base_uri: str) -> bytes | None:
    support = _load_support(semantic_dir, base_uri)
    return support.serialize(format="nt", encoding="utf-8") if support is not None else None


def _shacl_limits() -> tuple[float, int]:
    try:
        settings = get_settings()
    except ConfigurationError:  # pragma: no cover - sin configuración (scripts sueltos)
        return 60.0, 2048
    return settings.shacl_timeout_seconds, settings.shacl_memory_mb


def clear_caches() -> None:
    _load_shapes.cache_clear()
    _load_support.cache_clear()
    _shapes_nt.cache_clear()
    _support_nt.cache_clear()


def _node_text(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, BNode):
        return f"_:{node}"
    if isinstance(node, RdfLiteral):
        return str(node)
    return str(node)


def validate_shacl(
    graph: Graph, semantic_dir: Path, base_uri: str, *, support: bool = True
) -> None:
    """Valida con todas las formas. ``support=False`` no mezcla el vocabulario mínimo
    (las ontologías y los esquemas se validan solos: pyshacl mezcla el grafo de soporte
    con el de datos, y un esquema se validaría junto a otra copia de sí mismo)."""
    shapes_nt = _shapes_nt(semantic_dir, base_uri)
    support_nt = _support_nt(semantic_dir, base_uri) if support else None
    timeout, memory = _shacl_limits()
    try:
        outcome = shacl_worker.validate(
            graph.serialize(format="nt", encoding="utf-8"),
            shapes_nt,
            support_nt,
            timeout_seconds=timeout,
            memory_mb=memory,
        )
    except shacl_worker.ShaclLimitError as exc:
        if exc.reason == "timeout":
            detail = (
                f"La validación SHACL superó el tiempo máximo ({timeout:g} s, "
                "SHACL_TIMEOUT_SECONDS): divide el RDF o reduce su tamaño"
            )
        else:
            detail = (
                f"La validación SHACL superó la memoria máxima ({memory} MB, SHACL_MEMORY_MB): "
                "divide el RDF o reduce su tamaño"
            )
        raise IngestError("limit", detail) from None
    except shacl_worker.ShaclWorkerError:
        raise IngestError("shacl", "No se ha podido completar la validación SHACL") from None
    if outcome.conforms:
        return
    results = Graph().parse(data=outcome.results_nt, format="nt")
    text = outcome.report
    issues: list[Issue] = []
    for result in results.subjects(RDF.type, SH.ValidationResult):
        messages = [str(m) for m in results.objects(result, SH.resultMessage)]
        severity = results.value(result, SH.resultSeverity)
        issues.append(
            Issue(
                message=" / ".join(messages) or "Violación SHACL",
                focus_node=_node_text(results.value(result, SH.focusNode)),
                path=_node_text(results.value(result, SH.resultPath)),
                value=_node_text(results.value(result, SH.value)),
                severity=str(severity).rsplit("#", 1)[-1] if severity else "Violation",
                source_shape=_node_text(results.value(result, SH.sourceShape)),
            )
        )
    issues.sort(key=lambda i: (i.focus_node or "", i.source_shape or "", i.message))
    raise IngestError(
        "shacl",
        f"El RDF no cumple las formas SHACL ({len(issues)} resultado(s))",
        issues,
        report=str(text),
    )


def validate_plain(graph: Graph, semantic_dir: Path, base_uri: str) -> None:
    """SHACL sobre un grafo que no es una serie (vocabulario, catálogo)."""
    check_terms(graph)
    validate_shacl(graph, semantic_dir, base_uri)


# --- Todo junto --------------------------------------------------------------


def prepare_series(graph: Graph, uris: Uris, semantic_dir: Path) -> PreparedSeries:
    check_terms(graph)  # antes que la estructura y SHACL (también si el grafo no viene
    # de parse_rdf, como en las pruebas o en un uso futuro)
    prepared = check_structure(graph, uris)
    # SHACL ve la serie con su triple de pertenencia (itsh:DatasetSeries-catalog).
    validate_shacl(graph, semantic_dir, uris.base)
    return prepared


def store_graph(store: TripleStore, graph_uri: str, graph: Graph) -> tuple[bool, bool]:
    """Sustituye el grafo con nombre. Devuelve ``(created, changed)``.

    Exige credenciales de escritura aunque el contenido no haya cambiado, para que una
    configuración incompleta se detecte siempre.
    """
    store.ensure_writable()
    current = store.get_graph(graph_uri)
    created = len(current) == 0
    if not created and isomorphic(current, graph):
        return False, False
    store.put_graph(graph_uri, graph)
    return created, True


def published_versions(graph: Graph, series_uri: str) -> dict[str, URIRef]:
    """Versiones (``dcat:Dataset`` con ``dcat:inSeries`` a la serie) por URI."""
    series = URIRef(series_uri)
    return {
        str(node): node
        for node in graph.subjects(DCAT.inSeries, series)
        if isinstance(node, URIRef) and (node, RDF.type, DCAT.Dataset) in graph
    }


def check_immutable(current: Graph, prepared: PreparedSeries) -> list[str]:
    """Decisión 28. Devuelve las URIs de las versiones nuevas o lanza 409.

    Cada versión publicada tiene que venir con un subgrafo isomorfo al publicado.
    """
    from app.catalog import version_subgraph  # evita la importación circular

    series = URIRef(prepared.uri)
    before = published_versions(current, prepared.uri)
    after = published_versions(prepared.graph, prepared.uri)
    removed = sorted(set(before) - set(after))
    if removed:
        raise IngestError(
            "version_removed",
            "Faltan versiones ya publicadas: las versiones son inmutables y la serie se envía "
            "siempre con todas ellas",
            [
                Issue("Versión publicada que no viene en la petición", focus_node=uri)
                for uri in removed
            ],
        )
    changed = [
        uri
        for uri in sorted(before)
        if not isomorphic(
            version_subgraph(current, series, before[uri]),
            version_subgraph(prepared.graph, series, after[uri]),
        )
    ]
    if changed:
        raise IngestError(
            "version_immutable",
            "Hay versiones ya publicadas con otro contenido: las versiones son inmutables; "
            "publica los cambios como una versión nueva",
            [Issue("Versión publicada con contenido distinto", focus_node=uri) for uri in changed],
        )
    return sorted(set(after) - set(before))


def check_catalog(
    store: TripleStore, prepared: PreparedSeries, *, other: OtherCatalog = "conflict"
) -> str | None:
    """Lo que SHACL no ve de la pertenencia (decisión 49). Devuelve el catálogo en el que
    quedará la serie (``None`` si no hay que tocar la pertenencia).

    - Serie dada de baja: 409 ``withdrawn`` (los slugs no se reutilizan).
    - Serie ya en otro catálogo: 409 ``catalog_conflict`` (``other="conflict"``), se
      conserva el actual (``"keep"``) o se mueve (``"move"``).
    - Catálogo que no existe o está dado de baja: 422 ``catalog``.
    """
    from app import bajas  # evita la importación circular

    if prepared.base_uri is None:
        return None
    uris = Uris(prepared.base_uri)
    if bajas.get_tombstone(store, uris, prepared.uri) is not None:
        raise IngestError(
            "withdrawn",
            "La serie se dio de baja: su slug no se puede reutilizar",
            [Issue("Serie dada de baja", focus_node=prepared.uri)],
        )
    target = prepared.catalog_uri
    if target is None:
        return None
    current = bajas.series_catalogs(store, uris, prepared.uri)
    if current and target not in current:
        if other == "conflict":
            raise IngestError(
                "catalog_conflict",
                "La serie ya está en otro catálogo: para moverla, edita sus metadatos "
                "(PATCH /datasets/{slug} con «catalog»)",
                [Issue("Catálogo actual de la serie", focus_node=c) for c in sorted(current)],
            )
        if other == "keep":
            return sorted(current)[0]
    if current == {target}:
        return target
    if not bajas.catalog_exists(store, target):
        gone = bajas.get_tombstone(store, uris, target) is not None
        raise IngestError(
            "catalog",
            "El catálogo está dado de baja" if gone else "El catálogo no existe",
            [Issue("Catálogo de la serie", focus_node=target, path=str(DCAT.dataset))],
        )
    return target


def publish(
    store: TripleStore, prepared: PreparedSeries, *, other: OtherCatalog = "conflict"
) -> PublishResult:
    """Comprueba la inmutabilidad y el catálogo, escribe la serie (si cambia) y la deja
    en su catálogo."""
    from app import bajas  # evita la importación circular

    store.ensure_writable()
    current = store.get_graph(prepared.uri)
    new_versions = check_immutable(current, prepared)
    target = check_catalog(store, prepared, other=other)
    created = len(current) == 0
    changed = created or not isomorphic(current, prepared.graph)
    if changed:
        store.put_graph(prepared.uri, prepared.graph)
    if target is not None and prepared.base_uri is not None:
        bajas.set_membership(store, Uris(prepared.base_uri), prepared.uri, target)
    return PublishResult(
        slug=prepared.slug,
        uri=prepared.uri,
        graph_uri=prepared.uri,
        versions=prepared.versions,
        triples=len(prepared.graph),
        created=created,
        changed=changed,
        new_versions=new_versions,
    )


def merge_root_catalog(
    current: Graph, loaded: Graph, uris: Uris, withdrawn: set[str] | frozenset[str] = frozenset()
) -> Graph:
    """Catálogo raíz para ``load-semantic`` (decisión 49): ``data/catalogo.ttl`` más los
    ``dcat:catalog`` publicados (catálogos creados por la API), sin los catálogos dados de
    baja. Los ``dcat:dataset`` del modelo de la fase 4 (el raíz listaba series) se quitan."""
    root = URIRef(uris.root_catalog)
    merged = Graph()
    for triple in loaded:
        if triple[0] == root and triple[1] == DCAT.dataset:
            continue
        if triple[0] == root and triple[1] == DCAT.catalog and str(triple[2]) in withdrawn:
            continue
        merged.add(triple)
    for catalog in current.objects(root, DCAT.catalog):
        if (
            isinstance(catalog, URIRef)
            and uris.catalog_slug(str(catalog)) is not None
            and str(catalog) not in withdrawn
        ):
            merged.add((root, DCAT.catalog, catalog))
    return merged


def merge_catalog(current: Graph, loaded: Graph, catalog_uri: str) -> Graph:
    """Catálogo ``data/catalogos/{slug}.ttl`` para ``load-semantic``: sus metadatos y los
    ``dcat:dataset`` ya publicados. Los ``dcat:dataset`` del fichero no se copian: la
    pertenencia la aporta cada serie (su triple), y así ``load-semantic`` no deshace un
    traslado hecho desde la aplicación."""
    catalog = URIRef(catalog_uri)
    merged = Graph()
    for triple in loaded:
        if triple[0] == catalog and triple[1] == DCAT.dataset:
            continue
        merged.add(triple)
    for series in current.objects(catalog, DCAT.dataset):
        merged.add((catalog, DCAT.dataset, series))
    return merged


def check_catalog_structure(graph: Graph, uris: Uris, catalog_uri: str) -> None:
    """Un catálogo ``{BASE_URI}catalogo/{slug}``: solo él (y nodos en blanco), un nivel."""
    node = URIRef(catalog_uri)
    issues: list[Issue] = []
    found = set(graph.subjects(RDF.type, DCAT.Catalog))
    if found != {node}:
        issues.append(Issue(f"Tiene que describir exactamente un dcat:Catalog, {catalog_uri}"))
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        if subject != node:
            issues.append(Issue("Recurso que no es el catálogo", focus_node=str(subject)))
    for item in graph.objects(node, DCAT.catalog):
        issues.append(
            Issue(
                "Solo el catálogo raíz agrupa catálogos (un solo nivel)",
                focus_node=catalog_uri,
                value=str(item),
            )
        )
    for item in graph.objects(node, DCAT.dataset):
        if not isinstance(item, URIRef) or uris.series_slug(str(item)) is None:
            issues.append(
                Issue(
                    f"dcat:dataset tiene que ser una serie {uris.dataset_ns}{{slug}}",
                    focus_node=catalog_uri,
                    value=str(item),
                )
            )
    if issues:
        raise IngestError("uri", "El catálogo no sigue el patrón", issues)


def parse_file(path: Path, base_uri: str, *, max_triples: int = DEFAULT_MAX_TRIPLES) -> Graph:
    """Fichero Turtle de ``SEMANTIC_DIR``, con los mismos límites que la API."""
    graph = _new_limited_graph(path.stat().st_size, max_triples)
    try:
        graph.parse(path, format="turtle", publicID=base_uri)
    except Exception as exc:
        limit = _limit_error(exc)
        if limit is not None:
            raise IngestError("limit", f"{path.name}: {limit.message}") from None
        raise IngestError("syntax", f"{path.name}: Turtle no válido: {_short(exc)}") from exc
    _stop_limits(graph)
    check_terms(graph)
    return graph


def publish_and_audit(
    store: TripleStore,
    session: Session,
    prepared: PreparedSeries,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
    other: OtherCatalog = "conflict",
) -> PublishResult:
    """Publica la serie y registra en auditoría quién publicó qué serie.

    Se escribe primero en el triplestore y después se confirma la auditoría: si Fuseki
    falla no queda un evento de una publicación que no ha ocurrido.
    """
    result = publish(store, prepared, other=other)
    if result.new_versions:
        from app import fair  # evita la importación circular

        fair.enqueue(session, result.new_versions, requested_by=actor, commit=False)
    audit.record(
        session,
        AuditAction.DATASET_PUBLISHED,
        actor=actor,
        actor_username=actor_username,
        details={
            "series": result.uri,
            "slug": result.slug,
            "catalog": prepared.catalog_uri,
            "graph": result.graph_uri,
            "versions": result.versions,
            "triples": result.triples,
            "created": result.created,
            "changed": result.changed,
            "new_versions": result.new_versions,
            "via": via,
        },
    )
    session.commit()
    if result.new_versions:
        from app import fair

        fair.notify()
    return result
