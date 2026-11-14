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
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pyshacl import validate as shacl_validate
from rdflib import BNode, Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.compare import isomorphic
from rdflib.namespace import RDF
from sqlalchemy.orm import Session

from app import audit
from app.models import AuditAction, User
from app.triplestore import TripleStore
from app.uris import DCAT, Uris, is_slug

SH = Namespace("http://www.w3.org/ns/shacl#")

RdfFormat = Literal["turtle", "json-ld"]
IngestErrorKind = Literal["syntax", "structure", "uri", "shacl"]

VOCAB_FILE = Path("data") / "vocab-minimo.ttl"
CATALOG_FILE = Path("data") / "catalogo.ttl"
SYNTHETIC_DIR = Path("data") / "sintetico"
SHAPES_DIR = Path("shapes")


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
    graph: Graph
    versions: list[str]


@dataclass
class PublishResult:
    slug: str
    uri: str
    graph_uri: str
    versions: list[str]
    triples: int
    created: bool
    changed: bool


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


def parse_rdf(data: bytes, rdf_format: RdfFormat, base_uri: str) -> Graph:
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
        if _remote_context(document):
            raise IngestError(
                "syntax",
                "JSON-LD con contextos remotos (@context con URL o @import): no se admiten; "
                "incluye el contexto en el propio documento",
            )
    graph = Graph()
    try:
        graph.parse(data=text, format=rdf_format, publicID=base_uri)
    except Exception as exc:
        raise IngestError("syntax", f"RDF no válido ({rdf_format}): {_short(exc)}") from exc
    if len(graph) == 0:
        raise IngestError("syntax", "El RDF está vacío")
    return graph


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
            if isinstance(dist, URIRef) and not str(dist).startswith(
                version_prefixes[version_node]
            ):
                issues.append(
                    Issue(
                        "Una distribución debe colgar de la URI de su versión ({version}/{dist})",
                        focus_node=str(dist),
                    )
                )

    allowed_prefixes = (f"{series_uri}/", uris.activity_ns)
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value == series_uri or value.startswith(allowed_prefixes):
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
    return PreparedSeries(slug=slug, uri=series_uri, graph=graph, versions=versions)


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


def clear_caches() -> None:
    _load_shapes.cache_clear()
    _load_support.cache_clear()


def _node_text(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, BNode):
        return f"_:{node}"
    if isinstance(node, RdfLiteral):
        return str(node)
    return str(node)


def validate_shacl(graph: Graph, semantic_dir: Path, base_uri: str) -> None:
    shapes = _load_shapes(semantic_dir, base_uri)
    support = _load_support(semantic_dir, base_uri)
    conforms, results, text = shacl_validate(
        graph,
        shacl_graph=shapes,
        ont_graph=support,
        inference="none",
        abort_on_first=False,
        allow_warnings=True,
        meta_shacl=False,
        advanced=False,
    )
    if conforms:
        return
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
    validate_shacl(graph, semantic_dir, base_uri)


# --- Todo junto --------------------------------------------------------------


def prepare_series(graph: Graph, uris: Uris, semantic_dir: Path) -> PreparedSeries:
    prepared = check_structure(graph, uris)
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


def publish(store: TripleStore, prepared: PreparedSeries) -> PublishResult:
    created, changed = store_graph(store, prepared.uri, prepared.graph)
    return PublishResult(
        slug=prepared.slug,
        uri=prepared.uri,
        graph_uri=prepared.uri,
        versions=prepared.versions,
        triples=len(prepared.graph),
        created=created,
        changed=changed,
    )


def parse_file(path: Path, base_uri: str) -> Graph:
    graph = Graph()
    try:
        graph.parse(path, format="turtle", publicID=base_uri)
    except Exception as exc:
        raise IngestError("syntax", f"{path.name}: Turtle no válido: {_short(exc)}") from exc
    return graph


def publish_and_audit(
    store: TripleStore,
    session: Session,
    prepared: PreparedSeries,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
) -> PublishResult:
    """Publica la serie y registra en auditoría quién publicó qué serie.

    Se escribe primero en el triplestore y después se confirma la auditoría: si Fuseki
    falla no queda un evento de una publicación que no ha ocurrido.
    """
    result = publish(store, prepared)
    audit.record(
        session,
        AuditAction.DATASET_PUBLISHED,
        actor=actor,
        actor_username=actor_username,
        details={
            "series": result.uri,
            "slug": result.slug,
            "graph": result.graph_uri,
            "versions": result.versions,
            "triples": result.triples,
            "created": result.created,
            "changed": result.changed,
            "via": via,
        },
    )
    session.commit()
    return result
