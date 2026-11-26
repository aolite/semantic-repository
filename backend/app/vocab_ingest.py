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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic, to_canonical_graph
from rdflib.namespace import OWL, RDF, XSD
from sqlalchemy.orm import Session

from app import audit, bajas, ingest, owl_metrics
from app.config import Settings
from app.ingest import IngestError, Issue, OtherCatalog
from app.models import AuditAction, OntologyMetricsRecord, User, WithdrawnPrefix
from app.sparql import iri, iri_list, literal, render
from app.triplestore import TripleStore
from app.uris import AUXILIARY_SCHEME_SLUGS, DCAT, DCT, SKOS, VANN, Uris, is_slug, version_key
from app.write_lock import catalog_write_lock

# --- Pertenencia a un catálogo (decisión 50) -------------------------------------------
#
# Como las series (decisión 49): el grafo que se valida lleva «<{BASE_URI}catalogo/{slug}>
# dcat:resource <recurso>» (o la API lo añade a partir de ``?catalog={slug}``), las formas
# exigen exactamente uno (``itsh:ConceptSchemeCatalogShape``, ``itsh:OwnOntology-catalog``),
# y el backend lo guarda en el grafo del catálogo, no en el del esquema ni en el de la
# versión de ontología (que es inmutable).


def _membership(
    graph: Graph, uris: Uris, resource: URIRef
) -> tuple[set[tuple], list[str], list[Issue]]:
    """Separa los triples de pertenencia. Devuelve ``(triples, catálogos, problemas)``."""
    triples: set[tuple] = set()
    catalogs: list[str] = []
    issues: list[Issue] = []
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value == uris.root_catalog:
            issues.append(
                Issue(
                    "El catálogo raíz no lista esquemas ni ontologías: el recurso pertenece a "
                    f"un catálogo {uris.catalog_ns}{{slug}}",
                    focus_node=value,
                )
            )
            continue
        if uris.catalog_slug(value) is None:
            continue
        for triple in graph.triples((subject, None, None)):
            if triple[1] == DCAT.resource and triple[2] == resource:
                triples.add(triple)
                catalogs.append(value)
            else:
                issues.append(
                    Issue(
                        "Del catálogo solo se admite «<catálogo> dcat:resource <recurso>»: sus "
                        "metadatos se editan en /catalogs/{slug}",
                        focus_node=value,
                        path=str(triple[1]),
                    )
                )
    return triples, sorted(catalogs), issues


def _is_catalog_subject(uris: Uris, value: str) -> bool:
    return value == uris.root_catalog or uris.catalog_slug(value) is not None


def _without(graph: Graph, triples: set[tuple]) -> Graph:
    if not triples:
        return graph
    result = Graph()
    for prefix, namespace in graph.namespaces():
        result.bind(prefix, namespace, override=True, replace=True)
    for triple in graph:
        if triple not in triples:
            result.add(triple)
    return result


def add_resource_membership(graph: Graph, uris: Uris, catalog_slug: str) -> Graph:
    """Añade «<{BASE_URI}catalogo/{slug}> dcat:resource <recurso>» antes de validar
    (``POST /schemes?catalog=`` y ``POST /ontologies?catalog=``). El recurso es el único
    ``skos:ConceptScheme`` o la única ``owl:Ontology`` del grafo; si no lo hay, no se añade
    nada (la estructura dará el error). Si el RDF ya declara otro catálogo, 422."""
    candidates = [
        s for s in graph.subjects(RDF.type, SKOS.ConceptScheme) if isinstance(s, URIRef)
    ] + [s for s in graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)]
    if len(candidates) != 1:
        return graph
    resource = candidates[0]
    catalog = URIRef(uris.catalog(catalog_slug))
    declared = {c for c in graph.subjects(DCAT.resource, resource) if c != catalog}
    if declared:
        raise IngestError(
            "catalog",
            "El RDF declara otro catálogo que el parámetro catalog",
            [Issue("Catálogo distinto del parámetro", focus_node=str(c)) for c in sorted(declared)],
        )
    graph.add((catalog, DCAT.resource, resource))
    return graph


def resource_prefix(graph: Graph, resource: str) -> str | None:
    value = graph.value(URIRef(resource), VANN.preferredNamespacePrefix)
    return str(value) if isinstance(value, Literal) and str(value) else None


def withdrawn_prefix_owner(session: Session, prefix: str | None) -> str | None:
    """URI del recurso dado de baja que tenía ``prefix``, o ``None`` si está libre."""
    if not prefix:
        return None
    record = session.get(WithdrawnPrefix, prefix)
    return record.resource_uri if record is not None else None


# Recursos propios vivos (esquemas, también los auxiliares, y versiones de ontologías
# propias) que declaran el prefijo VANN $prefix en su propio grafo (el del esquema o el de
# una versión), salvo $resource. Las ontologías externas
# (sujetos fuera de BASE_URI, en {BASE_URI}onto/externas) no cuentan.
_PREFIX_OWNERS = """CONSTRUCT { ?r <http://purl.org/vocab/vann/preferredNamespacePrefix> ?p }
WHERE {
  GRAPH ?g { ?r <http://purl.org/vocab/vann/preferredNamespacePrefix> ?p }
  FILTER(isIRI(?r) && ?r != $resource && STR(?p) = $prefix)
  FILTER(STRSTARTS(STR(?g), $vocab_ns) || STRSTARTS(STR(?g), $onto_ns))
  FILTER(STRSTARTS(STR(?r), $vocab_ns) || STRSTARTS(STR(?r), $onto_ns))
  FILTER(?g = ?r || STRSTARTS(STR(?g), CONCAT(STR(?r), "/")))
}"""


def live_prefix_owners(
    store: TripleStore, uris: Uris, prefix: str | None, resource: str
) -> list[str]:
    """Otros recursos vivos que usan ``prefix`` (QA-50-01)."""
    if not prefix:
        return []
    graph = store.construct(
        render(
            _PREFIX_OWNERS,
            resource=iri(resource),
            prefix=literal(prefix),
            vocab_ns=literal(uris.vocab_ns),
            onto_ns=literal(uris.onto_ns),
        )
    )
    return sorted({str(s) for s in graph.subjects() if isinstance(s, URIRef)})


def check_resource_publication(
    store: TripleStore,
    session: Session,
    uris: Uris,
    resource: str,
    prefix: str | None,
    catalog_uri: str | None,
    *,
    other: OtherCatalog = "conflict",
) -> str | None:
    """Lo que SHACL no ve al publicar un esquema o una versión de ontología (decisión 50,
    reglas 2, 3 y 7 de ``semantic/uris.md``). Devuelve el catálogo en el que quedará.

    - Recurso dado de baja: 409 ``withdrawn`` (el slug no se reutiliza).
    - Prefijo VANN de un recurso dado de baja: 409 ``prefix_withdrawn``.
    - Prefijo VANN que ya usa **otro** recurso vivo (QA-50-01): 409 ``prefix_in_use``.
    - Recurso ya en otro catálogo: 409 ``catalog_conflict`` (``other="conflict"``, la API;
      moverlo es ``PATCH``) o se conserva el actual (``"keep"``, ``load-semantic``).
    - Catálogo que no existe o está dado de baja: 422 ``catalog``.
    """
    if bajas.get_tombstone(store, uris, resource) is not None:
        raise IngestError(
            "withdrawn",
            "El recurso se dio de baja: su URI no se puede reutilizar",
            [Issue("Recurso dado de baja", focus_node=resource)],
        )
    owner = withdrawn_prefix_owner(session, prefix)
    if owner is not None and owner != resource:
        raise IngestError(
            "prefix_withdrawn",
            f"El prefijo VANN «{prefix}» era de un recurso dado de baja y no se reutiliza",
            [
                Issue(
                    "Prefijo de un recurso dado de baja",
                    focus_node=resource,
                    path=str(VANN.preferredNamespacePrefix),
                    value=owner,
                )
            ],
        )
    owners = live_prefix_owners(store, uris, prefix, resource)
    if owners:
        raise IngestError(
            "prefix_in_use",
            f"El prefijo VANN «{prefix}» ya lo usa otro esquema u ontología: elige otro",
            [
                Issue(
                    "Prefijo de otro recurso vivo",
                    focus_node=resource,
                    path=str(VANN.preferredNamespacePrefix),
                    value=owner,
                )
                for owner in owners
            ],
        )
    current = bajas.resource_catalogs(store, uris, resource)
    target = catalog_uri
    if current and (target is None or target not in current):
        if other == "conflict":
            raise IngestError(
                "catalog_conflict",
                "El recurso ya está en otro catálogo: para moverlo, edita sus metadatos "
                "(PATCH con «catalog»)",
                [Issue("Catálogo actual del recurso", focus_node=c) for c in sorted(current)],
            )
        return sorted(current)[0]
    if target is None:
        return None
    if current == {target}:
        return target
    if not bajas.catalog_exists(store, target):
        gone = bajas.get_tombstone(store, uris, target) is not None
        raise IngestError(
            "catalog",
            "El catálogo está dado de baja" if gone else "El catálogo no existe",
            [Issue("Catálogo del recurso", focus_node=target, path=str(DCAT.resource))],
        )
    return target


# --- Ontologías -----------------------------------------------------------------------


@dataclass
class PreparedOntology:
    slug: str
    version: str
    uri: str
    version_iri: str
    graph: Graph  # la versión, sin el triple de pertenencia (va al grafo del catálogo)
    catalog_uri: str | None = None
    catalogs: list[str] = field(default_factory=list)
    base_uri: str = ""


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
    catalog_uri: str | None = None


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

    membership, catalogs, membership_issues = _membership(graph, uris, node)
    issues.extend(membership_issues)
    term_prefix = f"{uri}#"
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value in (uri, version_iri) or value.startswith(term_prefix):
            continue
        if _is_catalog_subject(uris, value):
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
        slug=slug,
        version=version,
        uri=uri,
        version_iri=version_iri,
        graph=_without(graph, membership),
        catalog_uri=catalogs[0] if len(catalogs) == 1 else None,
        catalogs=catalogs,
        base_uri=uris.base,
    )


def check_not_external(store: TripleStore, uris: Uris, graph: Graph) -> None:
    """Decisión 50 (reglas 5 y 12): una ontología externa (grafo ``{BASE_URI}onto/externas``)
    no se crea ni se cambia desde la aplicación: si el RDF describe una ``owl:Ontology`` que
    ya está entre las externas, 403 ``not_managed``. (``{BASE_URI}onto/externas`` como URI
    de ontología es un slug reservado: 422 ``uri`` en la estructura.)"""
    nodes = [n for n in graph.subjects(RDF.type, OWL.Ontology) if isinstance(n, URIRef)]
    if not nodes:
        return
    external = store.get_graph(uris.external_ontologies_graph)
    found = sorted(str(n) for n in nodes if (n, RDF.type, OWL.Ontology) in external)
    if found:
        raise IngestError(
            "not_managed",
            "Las ontologías externas no se gestionan desde la aplicación: solo cambian con "
            "ontologias/externas.ttl y load-semantic",
            [Issue("Ontología externa", focus_node=uri) for uri in found],
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
    # SHACL ve la versión con su triple de pertenencia (itsh:OwnOntology-catalog).
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
    other: OtherCatalog = "conflict",
) -> OntologyPublishResult:
    """Escribe la versión, la deja en su catálogo y guarda métricas y auditoría.

    Orden: métricas (``analyze_ontology``, antes de llamar aquí) -> triplestore ->
    PostgreSQL (métricas y auditoría en la misma transacción). Si Fuseki falla, no queda ni
    el registro de métricas ni la auditoría. Las comprobaciones contra lo publicado
    (inmutabilidad, baja, prefijo, catálogo) y las escrituras van con el bloqueo de las
    escrituras del catálogo (decisión 50: la pertenencia vive en el grafo del catálogo).
    """
    if analysis is None:
        analysis = analyze_ontology(prepared, settings, session)
    with catalog_write_lock(session):
        return _publish_ontology(
            store, session, prepared, analysis, actor, actor_username, via, other
        )


def _publish_ontology(
    store: TripleStore,
    session: Session,
    prepared: PreparedOntology,
    analysis: OntologyAnalysis,
    actor: User | None,
    actor_username: str | None,
    via: str,
    other: OtherCatalog,
) -> OntologyPublishResult:
    digest, recompute = analysis.digest, analysis.recomputed
    metrics, consistency = analysis.metrics, analysis.consistency
    uris = Uris(prepared.base_uri)

    store.ensure_writable()
    check_ontology_immutable(store, prepared)
    target = check_resource_publication(
        store,
        session,
        uris,
        prepared.uri,
        resource_prefix(prepared.graph, prepared.uri),
        prepared.catalog_uri,
        other=other,
    )
    record = session.get(OntologyMetricsRecord, prepared.version_iri)
    created, changed = ingest.store_graph(store, prepared.version_iri, prepared.graph)
    if target is not None:
        bajas.set_resource_membership(store, uris, prepared.uri, target)

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
            "catalog": target,
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
        catalog_uri=target,
    )


# --- Esquemas SKOS --------------------------------------------------------------------


@dataclass
class PreparedScheme:
    slug: str
    corp: bool
    uri: str
    graph: Graph  # el esquema, sin el triple de pertenencia (va al grafo del catálogo)
    concepts: int
    catalog_uri: str | None = None
    catalogs: list[str] = field(default_factory=list)
    base_uri: str = ""


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
    catalog_uri: str | None = None


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
        # Decisión 50 (reglas 5 y 12): no se gestiona desde la aplicación (403).
        raise IngestError(
            "not_managed",
            f"'{slug}' es un esquema auxiliar: no se gestiona desde la aplicación; solo se "
            "carga con load-semantic desde data/vocab-minimo.ttl",
            [Issue("Esquema auxiliar", focus_node=uri)],
        )
    prefix = f"{uri}/"
    membership, catalogs, issues = _membership(graph, uris, node)
    for subject in sorted({s for s in graph.subjects() if isinstance(s, URIRef)}, key=str):
        value = str(subject)
        if value == uri or (value.startswith(prefix) and is_slug(value[len(prefix) :])):
            continue
        if _is_catalog_subject(uris, value):
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
    return PreparedScheme(
        slug=slug,
        corp=corp,
        uri=uri,
        graph=_without(graph, membership),
        concepts=concepts,
        catalog_uri=catalogs[0] if len(catalogs) == 1 else None,
        catalogs=catalogs,
        base_uri=uris.base,
    )


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
    # SHACL ve el esquema con su triple de pertenencia (itsh:ConceptSchemeCatalogShape).
    ingest.validate_shacl(graph, settings.semantic_dir, uris.base, support=False)
    return prepared


# --- Conceptos: retirada, sustitutos y contenido publicado (decisión 50) ---------------

TRUE = Literal(True)


def scheme_concepts(graph: Graph, scheme: str) -> set[URIRef]:
    """Conceptos del esquema: ``skos:Concept`` con ``skos:inScheme`` el esquema."""
    node = URIRef(scheme)
    return {
        c
        for c in graph.subjects(SKOS.inScheme, node)
        if isinstance(c, URIRef) and (c, RDF.type, SKOS.Concept) in graph
    }


def is_deprecated(graph: Graph, concept: URIRef) -> bool:
    return any(
        isinstance(v, Literal) and v.datatype == XSD.boolean and v.toPython() is True
        for v in graph.objects(concept, OWL.deprecated)
    )


def check_scheme_concepts(current: Graph, prepared: PreparedScheme) -> None:
    """Republicar un esquema (regla 9 de ``semantic/uris.md``).

    - Decidido (2026-11-22): el conjunto de conceptos nuevo contiene todos los publicados;
      si falta alguno, 409 ``concepts_removed`` (un concepto se retira con
      ``owl:deprecated true``, sin perder su URI).
    - Reactivar un concepto retirado (quitarle ``owl:deprecated true``) queda
      fuera del piloto: 409 ``concept_reactivated``.
    """
    if not len(current):
        return
    before = scheme_concepts(current, prepared.uri)
    after = scheme_concepts(prepared.graph, prepared.uri)
    missing = sorted(str(c) for c in before - after)
    if missing:
        raise IngestError(
            "concepts_removed",
            "Faltan conceptos ya publicados: un esquema no pierde conceptos al republicarse; "
            'para retirar uno, márcalo con owl:deprecated "true"^^xsd:boolean (y, si los '
            "tiene, sus sustitutos con dct:isReplacedBy)",
            [Issue("Concepto publicado ausente en la petición", focus_node=c) for c in missing],
        )
    reactivated = sorted(
        str(c) for c in before if is_deprecated(current, c) and not is_deprecated(prepared.graph, c)
    )
    if reactivated:
        raise IngestError(
            "concept_reactivated",
            "Hay conceptos retirados que dejan de estarlo: reactivar un concepto retirado no "
            "se contempla en el piloto",
            [
                Issue(
                    "Concepto retirado sin owl:deprecated true",
                    focus_node=c,
                    path=str(OWL.deprecated),
                )
                for c in reactivated
            ],
        )


_LIVE_CONCEPTS_QUERY = """CONSTRUCT { ?c a <http://www.w3.org/2004/02/skos/core#Concept> . }
WHERE {
  VALUES ?c { $values }
  GRAPH ?g { ?c a <http://www.w3.org/2004/02/skos/core#Concept> ;
               <http://www.w3.org/2004/02/skos/core#inScheme> ?g . }
  FILTER(STRSTARTS(STR(?g), $vocab_ns))
}"""


def live_concepts(store: TripleStore, uris: Uris, candidates: set[str]) -> set[str]:
    """De ``candidates``, los que son ``skos:Concept`` de un esquema publicado (vivo)."""
    values = sorted(c for c in candidates if c.startswith(uris.vocab_ns))
    if not values:
        return set()
    graph = store.construct(
        render(_LIVE_CONCEPTS_QUERY, values=iri_list(values), vocab_ns=literal(uris.vocab_ns))
    )
    return {str(c) for c in graph.subjects(RDF.type, SKOS.Concept)}


def check_replacements(
    store: TripleStore,
    uris: Uris,
    prepared: PreparedScheme,
    known: set[str] | frozenset[str] = frozenset(),
) -> None:
    """Decidido (2026-11-25, regla 9): cada sustituto (``dct:isReplacedBy``) de un concepto
    retirado es un ``skos:Concept`` vivo, de este esquema o de otro publicado (``known``:
    conceptos que se publican en la misma ejecución de ``load-semantic``). Si no, 422
    ``replacement``."""
    own = {str(c) for c in scheme_concepts(prepared.graph, prepared.uri)}
    pairs = [
        (str(concept), str(target))
        for concept, target in prepared.graph.subject_objects(DCT.isReplacedBy)
        if isinstance(concept, URIRef)
    ]
    pending = {t for _c, t in pairs if t not in own and t not in known}
    alive = live_concepts(store, uris, pending) if pending else set()
    dead = sorted((c, t) for c, t in pairs if t in pending and t not in alive)
    if dead:
        raise IngestError(
            "replacement",
            "Cada sustituto (dct:isReplacedBy) de un concepto retirado tiene que ser un "
            "skos:Concept vivo de este esquema o de otro publicado",
            [
                Issue(
                    "Sustituto que no es un concepto vivo",
                    focus_node=c,
                    path=str(DCT.isReplacedBy),
                    value=t,
                )
                for c, t in dead
            ],
        )


def _closure(graph: Graph, start: URIRef) -> list[tuple]:
    """Triples de ``start`` y de los nodos en blanco que cuelgan de él."""
    result: list[tuple] = []
    pending: list = [start]
    seen: set = set()
    while pending:
        subject = pending.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for triple in graph.triples((subject, None, None)):
            result.append(triple)
            if isinstance(triple[2], BNode):
                pending.append(triple[2])
    return result


def merge_published_concepts(current: Graph, loaded: Graph, scheme: str) -> Graph:
    """Esquema de ``vocabularios/`` para ``load-semantic`` (decidido 2026-11-25: manda la
    aplicación también en el contenido de los esquemas).

    - Los conceptos publicados que el fichero no trae (añadidos desde la aplicación) se
      conservan, con sus triples y los que los enlazan desde el esquema
      (``skos:hasTopConcept``): ``load-semantic`` no los quita.
    - [PROPUESTA] Un concepto retirado en lo publicado (``owl:deprecated true``) sigue
      retirado, con sus sustitutos, aunque el fichero no lo marque: reactivarlo queda fuera
      del piloto.

    El resto (metadatos del esquema y conceptos del fichero) sale del fichero."""
    if not len(current):
        return loaded
    node = URIRef(scheme)
    merged = Graph()
    for prefix, namespace in loaded.namespaces():
        merged.bind(prefix, namespace, override=True, replace=True)
    for triple in loaded:
        merged.add(triple)
    in_file = {s for s in loaded.subjects() if isinstance(s, URIRef)}
    for concept in scheme_concepts(current, scheme):
        if concept not in in_file:
            for triple in _closure(current, concept):
                merged.add(triple)
            for predicate in current.predicates(node, concept):
                merged.add((node, predicate, concept))
        elif is_deprecated(current, concept) and not is_deprecated(merged, concept):
            merged.remove((concept, OWL.deprecated, None))
            merged.add((concept, OWL.deprecated, TRUE))
            for target in current.objects(concept, DCT.isReplacedBy):
                merged.add((concept, DCT.isReplacedBy, target))
    return merged


def publish_scheme_and_audit(
    store: TripleStore,
    session: Session,
    prepared: PreparedScheme,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
    other: OtherCatalog = "conflict",
    check_concepts: bool = True,
    known_concepts: set[str] | frozenset[str] = frozenset(),
) -> SchemePublishResult:
    """Comprueba lo que SHACL no ve, escribe el esquema, lo deja en su catálogo y registra
    la auditoría, con el bloqueo de las escrituras del catálogo.

    ``check_concepts`` (la API): 409 si faltan conceptos publicados o se reactiva uno
    retirado. ``load-semantic`` no lo comprueba: conserva los conceptos publicados
    (``merge_published_concepts``)."""
    with catalog_write_lock(session):
        return _publish_scheme(
            store,
            session,
            prepared,
            actor,
            actor_username,
            via,
            other,
            check_concepts,
            known_concepts,
        )


def _publish_scheme(
    store: TripleStore,
    session: Session,
    prepared: PreparedScheme,
    actor: User | None,
    actor_username: str | None,
    via: str,
    other: OtherCatalog,
    check_concepts: bool,
    known_concepts: set[str] | frozenset[str],
) -> SchemePublishResult:
    uris = Uris(prepared.base_uri)
    store.ensure_writable()
    target = None
    if not uris.is_auxiliary_scheme(prepared.uri):
        target = check_resource_publication(
            store,
            session,
            uris,
            prepared.uri,
            resource_prefix(prepared.graph, prepared.uri),
            prepared.catalog_uri,
            other=other,
        )
    if check_concepts:
        check_scheme_concepts(store.get_graph(prepared.uri), prepared)
    check_replacements(store, uris, prepared, known_concepts)
    created, changed = ingest.store_graph(store, prepared.uri, prepared.graph)
    if target is not None:
        bajas.set_resource_membership(store, uris, prepared.uri, target)
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
            "catalog": target,
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
        catalog_uri=target,
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
