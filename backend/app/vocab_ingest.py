"""Ingesta de ontologías (una versión) y de esquemas SKOS (fase 3).

Misma estrategia que la de series de dataset (``app.ingest``), compartida por
``POST /ontologies``, ``POST /schemes`` y ``python -m app.cli load-semantic``:

1. ``ingest.parse_rdf``: Turtle o JSON-LD, IRIs relativas contra ``BASE_URI``, sin
   contextos remotos, IRIs válidas y anidamiento máximo.
2. Estructura y URIs:
   - **Ontología**: exactamente una ``owl:Ontology`` con URI ``{BASE_URI}onto/{slug}`` y
     exactamente un ``owl:versionIRI`` ``{BASE_URI}onto/{slug}/{version}``.
     ``owl:versionInfo`` (si está) coincide con la versión; ``owl:priorVersion`` y
     ``owl:backwardCompatibleWith`` apuntan a versiones anteriores de la misma ontología.
     Los sujetos bajo ``BASE_URI`` solo pueden ser la ontología, su ``versionIRI`` o sus
     términos (``{BASE_URI}onto/{slug}#Término``). Se admiten sujetos externos (fuera de
     ``BASE_URI``), como las declaraciones de términos importados que añaden los editores
     de ontologías: viven en el grafo de la versión y no afectan a ningún otro grafo.
   - **Esquema**: exactamente un ``skos:ConceptScheme`` con URI ``{BASE_URI}vocab/{slug}``
     (dominio) o ``{BASE_URI}vocab/corp/{slug}`` (corporativo). Todo sujeto con IRI es el
     esquema o un concepto ``{esquema}/{slug}``.
   - **Ontologías externas** (solo ``load-semantic``): ningún sujeto bajo ``BASE_URI``.
3. SHACL con todas las formas de ``SEMANTIC_DIR/shapes``, sin grafo de soporte (la versión
   o el esquema se validan solos).
4. Guardado: la versión de ontología en el grafo de su ``versionIRI``; el esquema, en el de
   su URI; las externas, en ``{BASE_URI}onto/externas``. Se sustituye el grafo completo y,
   si el contenido es isomorfo al guardado, no se reescribe. Las versiones de ontología
   son inmutables (decisión 28): una ``versionIRI`` ya publicada con otro contenido da 409
   ``version_immutable``. Los esquemas SKOS no cambian en la fase 4 (su versión no forma
   parte de la URI).

En las ontologías, antes de escribir se calculan las métricas OWL y la consistencia
(``app.owl_metrics``), que se guardan en PostgreSQL junto con la auditoría.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rdflib import BNode, Graph, URIRef
from rdflib.compare import isomorphic, to_canonical_graph
from rdflib.namespace import OWL, RDF
from sqlalchemy.orm import Session

from app import audit, ingest, owl_metrics
from app.config import Settings
from app.ingest import IngestError, Issue
from app.models import AuditAction, OntologyMetricsRecord, User
from app.triplestore import TripleStore
from app.uris import AUXILIARY_SCHEME_SLUGS, SKOS, Uris, is_slug, version_key

# --- Ontologías -----------------------------------------------------------------------


@dataclass
class PreparedOntology:
    slug: str
    version: str
    uri: str
    version_iri: str
    graph: Graph


@dataclass
class OntologyPublishResult:
    slug: str
    version: str
    uri: str
    version_iri: str
    graph_uri: str
    triples: int
    created: bool
    changed: bool
    metrics: dict[str, Any]
    consistency: dict[str, Any]
    metrics_recomputed: bool


def check_ontology_structure(graph: Graph, uris: Uris) -> PreparedOntology:
    ontologies = sorted(set(graph.subjects(RDF.type, OWL.Ontology)), key=str)
    if len(ontologies) != 1:
        raise IngestError(
            "structure",
            f"Se espera exactamente una owl:Ontology por ingesta; hay {len(ontologies)}",
        )
    node = ontologies[0]
    if not isinstance(node, URIRef):
        raise IngestError("uri", "La owl:Ontology debe tener IRI, no un nodo en blanco")
    uri = str(node)
    slug = uris.ontology_slug(uri)
    if slug is None:
        raise IngestError(
            "uri",
            f"La URI de la ontología debe ser {uris.onto_ns}{{slug}} (slug en minúsculas, "
            "dígitos y guiones; 'externas' está reservado)",
            [Issue("URI de ontología fuera del patrón", focus_node=uri)],
        )
    version_iris = list(graph.objects(node, OWL.versionIRI))
    if len(version_iris) != 1 or not isinstance(version_iris[0], URIRef):
        raise IngestError(
            "structure",
            "La ontología necesita exactamente un owl:versionIRI (IRI)",
            [Issue("owl:versionIRI ausente o repetido", focus_node=uri, path=str(OWL.versionIRI))],
        )
    version_iri = str(version_iris[0])
    parts = uris.ontology_version_parts(version_iri)
    if parts is None or parts[0] != slug:
        raise IngestError(
            "uri",
            f"owl:versionIRI debe ser {uri}/{{MAYOR.MENOR.PARCHE}}",
            [Issue("versionIRI fuera del patrón", focus_node=uri, value=version_iri)],
        )
    version = parts[1]

    issues: list[Issue] = []
    declared = [str(v) for v in graph.objects(node, OWL.versionInfo)]
    if declared and declared != [version]:
        issues.append(
            Issue(
                "owl:versionInfo no coincide con el último segmento de owl:versionIRI",
                focus_node=uri,
                path=str(OWL.versionInfo),
                value=", ".join(declared),
            )
        )
    for prop in (OWL.priorVersion, OWL.backwardCompatibleWith, OWL.incompatibleWith):
        for target in graph.objects(node, prop):
            target_parts = uris.ontology_version_parts(str(target))
            if (
                target_parts is None
                or target_parts[0] != slug
                or version_key(target_parts[1]) >= version_key(version)
            ):
                issues.append(
                    Issue(
                        "Debe apuntar a una versión anterior de la misma ontología "
                        f"({uri}/{{versión}})",
                        focus_node=uri,
                        path=str(prop),
                        value=str(target),
                    )
                )

    term_prefix = f"{uri}#"
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value in (uri, version_iri) or value.startswith(term_prefix):
            continue
        if value.startswith(uris.base):
            issues.append(
                Issue(
                    "Una ingesta de ontología solo puede describir, bajo BASE_URI, la "
                    "ontología, su versionIRI y sus términos ({ontología}#Término)",
                    focus_node=value,
                )
            )
    if issues:
        raise IngestError("uri", "Hay recursos con URIs fuera del patrón", issues)
    return PreparedOntology(
        slug=slug, version=version, uri=uri, version_iri=version_iri, graph=graph
    )


def check_ontology_immutable(store: TripleStore, prepared: PreparedOntology) -> None:
    """Decisión 28: una ``owl:versionIRI`` ya publicada no cambia de contenido.

    Con el mismo contenido (isomorfo) la ingesta es idempotente; con otro, 409
    ``version_immutable``. Se comprueba antes de calcular métricas y de escribir.
    """
    current = store.get_graph(prepared.version_iri)
    if len(current) and not isomorphic(current, prepared.graph):
        raise IngestError(
            "version_immutable",
            "La versión de la ontología ya está publicada con otro contenido: las versiones "
            "son inmutables; publica los cambios con un owl:versionIRI nuevo",
            [Issue("Versión publicada con contenido distinto", focus_node=prepared.version_iri)],
        )


def prepare_ontology(graph: Graph, uris: Uris, settings: Settings) -> PreparedOntology:
    ingest.check_terms(graph)
    prepared = check_ontology_structure(graph, uris)
    ingest.validate_shacl(graph, settings.semantic_dir, uris.base, support=False)
    return prepared


def content_hash(graph: Graph) -> str:
    """SHA-256 del grafo canónico (independiente del orden y de los nodos en blanco)."""
    canonical = to_canonical_graph(graph)
    lines = sorted(
        line
        for line in canonical.serialize(format="nt", encoding="utf-8").decode().splitlines()
        if line.strip()
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _tool_name() -> str:
    import owlready2

    version = getattr(owlready2, "VERSION", "?")
    return f"owlready2 {version}; {owl_metrics.REASONER_NAME} (incluido en owlready2)"


def compute_ontology_metrics(
    prepared: PreparedOntology, settings: Settings
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri)
    consistency = owl_metrics.check_consistency(
        prepared.graph,
        prepared.uri,
        timeout_seconds=settings.reasoner_timeout_seconds,
        java_memory_mb=settings.reasoner_java_memory_mb,
    )
    return metrics.to_dict(), consistency.to_dict()


@dataclass
class OntologyAnalysis:
    """Métricas y consistencia de una versión, calculadas antes de escribir nada."""

    digest: str
    metrics: dict[str, Any]
    consistency: dict[str, Any]
    recomputed: bool


def analyze_ontology(
    prepared: PreparedOntology, settings: Settings, session: Session
) -> OntologyAnalysis:
    """Calcula (o reutiliza, si el contenido no cambió) métricas y consistencia.

    Se llama **antes de escribir** en la API y en ``load-semantic``. Si owlready2 no puede
    leer la ontología, lanza ``IngestError`` (422) y no se escribe nada (QA-G3-01).
    """
    digest = content_hash(prepared.graph)
    record = session.get(OntologyMetricsRecord, prepared.version_iri)
    if record is not None and record.content_hash == digest:
        return OntologyAnalysis(digest, record.metrics, record.consistency, recomputed=False)
    try:
        metrics, consistency = compute_ontology_metrics(prepared, settings)
    except owl_metrics.OntologyLoadError as exc:
        issues = [Issue("Literal que no cumple su tipo de datos", value=v) for v in exc.values]
        raise IngestError("syntax", exc.message, issues) from None
    return OntologyAnalysis(digest, metrics, consistency, recomputed=True)


def publish_ontology_and_audit(
    store: TripleStore,
    session: Session,
    prepared: PreparedOntology,
    settings: Settings,
    *,
    analysis: OntologyAnalysis | None = None,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
) -> OntologyPublishResult:
    """Escribe la versión y guarda métricas y auditoría.

    Orden: métricas (``analyze_ontology``, antes de llamar aquí) -> triplestore ->
    PostgreSQL (métricas y auditoría en la misma transacción). Si Fuseki falla, no queda ni
    el registro de métricas ni la auditoría.
    """
    if analysis is None:
        analysis = analyze_ontology(prepared, settings, session)
    digest, recompute = analysis.digest, analysis.recomputed
    metrics, consistency = analysis.metrics, analysis.consistency
    record = session.get(OntologyMetricsRecord, prepared.version_iri)

    store.ensure_writable()
    check_ontology_immutable(store, prepared)
    created, changed = ingest.store_graph(store, prepared.version_iri, prepared.graph)

    if recompute:
        if record is None:
            record = OntologyMetricsRecord(version_iri=prepared.version_iri)
            session.add(record)
        record.ontology_iri = prepared.uri
        record.content_hash = digest
        record.metrics = metrics
        record.consistency = consistency
        record.tool = _tool_name()
        record.computed_at = datetime.now(UTC)
    audit.record(
        session,
        AuditAction.ONTOLOGY_PUBLISHED,
        actor=actor,
        actor_username=actor_username,
        details={
            "ontology": prepared.uri,
            "slug": prepared.slug,
            "version": prepared.version,
            "version_iri": prepared.version_iri,
            "graph": prepared.version_iri,
            "triples": len(prepared.graph),
            "created": created,
            "changed": changed,
            "metrics_recomputed": recompute,
            "consistent": consistency.get("consistent"),
            "via": via,
        },
    )
    session.commit()
    return OntologyPublishResult(
        slug=prepared.slug,
        version=prepared.version,
        uri=prepared.uri,
        version_iri=prepared.version_iri,
        graph_uri=prepared.version_iri,
        triples=len(prepared.graph),
        created=created,
        changed=changed,
        metrics=metrics,
        consistency=consistency,
        metrics_recomputed=recompute,
    )


# --- Esquemas SKOS --------------------------------------------------------------------


@dataclass
class PreparedScheme:
    slug: str
    corp: bool
    uri: str
    graph: Graph
    concepts: int


@dataclass
class SchemePublishResult:
    slug: str
    corp: bool
    uri: str
    graph_uri: str
    concepts: int
    triples: int
    created: bool
    changed: bool


# Profundidad máxima de la jerarquía de un esquema (QA-G3-04): niveles de skos:broader
# (o de skos:narrower) desde una raíz. 64, como el anidamiento máximo de la ingesta; los
# esquemas reales tienen pocos niveles y el árbol de la API se sirve con esa profundidad.
MAX_CONCEPT_DEPTH = 64


def concept_depth(graph: Graph, scheme: URIRef) -> int:
    """Mayor número de niveles por debajo de una raíz, sin recursión. Los ciclos no
    alargan la cadena (cada concepto se visita una vez por recorrido)."""
    prefix = f"{scheme}/"
    concepts = {c for c in graph.subjects(RDF.type, SKOS.Concept) if str(c).startswith(prefix)}
    parents: dict = {c: set() for c in concepts}
    for child, parent in graph.subject_objects(SKOS.broader):
        if child in concepts and parent in concepts and child != parent:
            parents[child].add(parent)
    for parent, child in graph.subject_objects(SKOS.narrower):
        if child in concepts and parent in concepts and child != parent:
            parents[child].add(parent)
    depth: dict = {}
    for start in concepts:
        if start in depth:
            continue
        stack = [(start, iter(parents[start]))]
        on_path = {start}
        while stack:
            node, pending = stack[-1]
            nxt = next(pending, None)
            if nxt is None:
                stack.pop()
                on_path.discard(node)
                above = [depth.get(p, 0) + 1 for p in parents[node] if p not in on_path]
                depth[node] = max(above, default=0)
                continue
            if nxt in on_path or nxt in depth:
                continue
            on_path.add(nxt)
            stack.append((nxt, iter(parents[nxt])))
    return max(depth.values(), default=0)


def check_scheme_structure(
    graph: Graph, uris: Uris, *, allow_auxiliary: bool = False
) -> PreparedScheme:
    """``allow_auxiliary``: admite ``vocab/dominio`` y ``vocab/tipo-dataset``, que solo
    carga ``load-semantic`` desde ``data/vocab-minimo.ttl`` (QA-G3-06)."""
    schemes = sorted(set(graph.subjects(RDF.type, SKOS.ConceptScheme)), key=str)
    if len(schemes) != 1:
        raise IngestError(
            "structure",
            f"Se espera exactamente un skos:ConceptScheme por ingesta; hay {len(schemes)}",
        )
    node = schemes[0]
    if not isinstance(node, URIRef):
        raise IngestError("uri", "El skos:ConceptScheme debe tener IRI, no un nodo en blanco")
    uri = str(node)
    parts = uris.scheme_parts(uri)
    if parts is None:
        raise IngestError(
            "uri",
            f"La URI del esquema debe ser {uris.vocab_ns}{{slug}} o {uris.corp_vocab_ns}{{slug}} "
            "(slug en minúsculas, dígitos y guiones; 'corp' está reservado)",
            [Issue("URI de esquema fuera del patrón", focus_node=uri)],
        )
    slug, corp = parts
    if not corp and slug in AUXILIARY_SCHEME_SLUGS and not allow_auxiliary:
        raise IngestError(
            "uri",
            f"'{slug}' es un esquema auxiliar reservado: solo se carga con load-semantic "
            "desde data/vocab-minimo.ttl",
            [Issue("Slug de esquema reservado", focus_node=uri)],
        )
    prefix = f"{uri}/"
    issues: list[Issue] = []
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value == uri or (value.startswith(prefix) and is_slug(value[len(prefix) :])):
            continue
        issues.append(
            Issue(
                "Una ingesta de esquema solo puede describir el esquema y sus conceptos "
                "({esquema}/{slug})",
                focus_node=value,
            )
        )
    if issues:
        raise IngestError("uri", "Hay recursos con URIs fuera del patrón", issues)
    depth = concept_depth(graph, node)
    if depth > MAX_CONCEPT_DEPTH:
        raise IngestError(
            "limit",
            f"La jerarquía de conceptos tiene {depth} niveles; el máximo es {MAX_CONCEPT_DEPTH}",
        )
    concepts = sum(1 for c in set(graph.subjects(RDF.type, SKOS.Concept)) if isinstance(c, URIRef))
    return PreparedScheme(slug=slug, corp=corp, uri=uri, graph=graph, concepts=concepts)


def split_schemes(graph: Graph, uris: Uris) -> list[PreparedScheme]:
    """Reparte un fichero con varios esquemas (``data/vocab-minimo.ttl``: ``dominio`` y
    ``tipo-dataset``) en un grafo por esquema: cada esquema con los triples de su URI, de
    sus conceptos (``{esquema}/…``) y de los nodos en blanco que cuelgan de ellos. Falla si
    sobra algún triple."""
    schemes = sorted(
        {s for s in graph.subjects(RDF.type, SKOS.ConceptScheme) if isinstance(s, URIRef)},
        key=str,
    )
    used: set[tuple] = set()
    result: list[PreparedScheme] = []
    for scheme in schemes:
        part = Graph()
        prefix = f"{scheme}/"
        pending = [s for s in set(graph.subjects()) if s == scheme or str(s).startswith(prefix)]
        seen: set = set()
        while pending:
            subject = pending.pop()
            if subject in seen:
                continue
            seen.add(subject)
            for triple in graph.triples((subject, None, None)):
                part.add(triple)
                used.add(triple)
                if isinstance(triple[2], BNode):
                    pending.append(triple[2])
        result.append(check_scheme_structure(part, uris, allow_auxiliary=True))
    leftover = [t for t in graph if t not in used]
    if leftover:
        raise IngestError(
            "uri",
            "Hay triples que no pertenecen a ningún esquema del fichero",
            [Issue("Triple fuera de los esquemas", focus_node=str(leftover[0][0]))],
        )
    return result


def prepare_scheme(graph: Graph, uris: Uris, settings: Settings) -> PreparedScheme:
    ingest.check_terms(graph)
    prepared = check_scheme_structure(graph, uris)
    ingest.validate_shacl(graph, settings.semantic_dir, uris.base, support=False)
    return prepared


def publish_scheme_and_audit(
    store: TripleStore,
    session: Session,
    prepared: PreparedScheme,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
) -> SchemePublishResult:
    created, changed = ingest.store_graph(store, prepared.uri, prepared.graph)
    audit.record(
        session,
        AuditAction.SCHEME_PUBLISHED,
        actor=actor,
        actor_username=actor_username,
        details={
            "scheme": prepared.uri,
            "slug": prepared.slug,
            "corp": prepared.corp,
            "graph": prepared.uri,
            "concepts": prepared.concepts,
            "triples": len(prepared.graph),
            "created": created,
            "changed": changed,
            "via": via,
        },
    )
    session.commit()
    return SchemePublishResult(
        slug=prepared.slug,
        corp=prepared.corp,
        uri=prepared.uri,
        graph_uri=prepared.uri,
        concepts=prepared.concepts,
        triples=len(prepared.graph),
        created=created,
        changed=changed,
    )


# --- Ontologías externas (solo referencia) --------------------------------------------


def prepare_external(graph: Graph, uris: Uris, settings: Settings) -> Graph:
    ingest.check_terms(graph)
    issues = [
        Issue(
            "Las ontologías externas se describen solo por referencia: ningún recurso puede "
            "colgar de BASE_URI",
            focus_node=str(subject),
        )
        for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str)
        if str(subject).startswith(uris.base)
    ]
    if issues:
        raise IngestError("uri", "Hay recursos con URIs fuera del patrón", issues)
    if not any(isinstance(o, URIRef) for o in graph.subjects(RDF.type, OWL.Ontology)):
        raise IngestError("structure", "El fichero de externas no describe ninguna owl:Ontology")
    ingest.validate_shacl(graph, settings.semantic_dir, uris.base, support=False)
    return graph
