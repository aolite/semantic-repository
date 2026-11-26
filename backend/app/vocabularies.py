"""Lectura de ontologías y esquemas SKOS (fase 3).

Misma estrategia que ``app.catalog``: cada operación trae del triplestore grafos pequeños
con plantillas ``CONSTRUCT`` fijas (los valores solo entran como términos escapados con
``app.sparql``) y el resto se resuelve en Python. El texto de búsqueda ``q`` no llega a
SPARQL.

Grafos que se leen (siempre nombrados en el patrón ``GRAPH``):

- **Versiones de ontología**: el grafo de cada versión es su ``owl:versionIRI``
  (``GRAPH ?g { ?o a owl:Ontology ; owl:versionIRI ?g }``), bajo ``{BASE_URI}onto/`` y con
  ``?g`` igual a ``{?o}/{versión}``.
- **Ontologías externas**: solo el grafo ``{BASE_URI}onto/externas``.
- **Esquemas SKOS**: el grafo de cada esquema es su URI
  (``GRAPH ?s { ?s a skos:ConceptScheme }``), bajo ``{BASE_URI}vocab/``. Un concepto solo
  expone etiquetas desde el grafo de su esquema (``?c skos:inScheme ?g`` dentro de ``?g``).
- **Series de dataset** (usos): como en ``app.catalog``.

Las métricas OWL salen de PostgreSQL (``OntologyMetricsRecord``), calculadas en la ingesta.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from rdflib.term import Node
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.catalog import (
    NotFoundError,
    normalize,
    pick_literal,
    resource_catalogs,
    resource_ref,
    sorted_nodes,
    uri_or_none,
)
from app.models import OntologyMetricsRecord
from app.sparql import iri, iri_list, literal, render
from app.triplestore import TripleStore
from app.uris import ADMS, DCAT, DCT, FOAF, SKOS, VANN, Uris, is_slug, version_key
from app.vocab_ingest import MAX_CONCEPT_DEPTH, is_deprecated

PREFIXES = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# Cabecera (triples de la owl:Ontology) de cada versión, reescrita sobre el versionIRI
# para no mezclar versiones: ``?g ?p ?v``. ``$prefix`` acota a una ontología
# (``{BASE_URI}onto/{slug}/``) o a todas (``{BASE_URI}onto/``).
ONTOLOGY_HEADERS_QUERY = (
    PREFIXES
    + """CONSTRUCT { ?g ?p ?v . } WHERE {
  GRAPH ?g { ?o a owl:Ontology ; owl:versionIRI ?g ; ?p ?v . }
  FILTER(STRSTARTS(STR(?g), $prefix))
  FILTER(STRSTARTS(STR(?g), CONCAT(STR(?o), "/")))
}"""
)

GRAPH_QUERY = "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH $graph { ?s ?p ?o } }"

# Esquemas: sus triples propios y sus conceptos (para contarlos).
SCHEMES_QUERY = (
    PREFIXES
    + """CONSTRUCT { ?s ?p ?v . ?c a skos:Concept ; skos:inScheme ?s . } WHERE {
  {
    GRAPH ?s { ?s a skos:ConceptScheme ; ?p ?v . }
    FILTER(STRSTARTS(STR(?s), $vocab_ns))
  } UNION {
    GRAPH ?s { ?s a skos:ConceptScheme . ?c a skos:Concept ; skos:inScheme ?s . }
    FILTER(STRSTARTS(STR(?s), $vocab_ns))
  }
}"""
)

# Etiquetas, tipo y esquema de una lista de IRIs (esquemas o conceptos), leídas solo del
# grafo del propio esquema o del esquema del concepto.
VOCAB_LABELS_QUERY = (
    PREFIXES
    + """CONSTRUCT { ?x a ?t ; skos:prefLabel ?l . ?y skos:inScheme ?cg ; skos:prefLabel ?cl . }
WHERE {
  {
    VALUES ?x { $values }
    GRAPH ?x { ?x a skos:ConceptScheme , ?t . OPTIONAL { ?x skos:prefLabel ?l . } }
    FILTER(STRSTARTS(STR(?x), $vocab_ns))
  } UNION {
    VALUES ?y { $values }
    GRAPH ?cg { ?y skos:inScheme ?cg . OPTIONAL { ?y skos:prefLabel ?cl . } }
    FILTER(STRSTARTS(STR(?cg), $vocab_ns))
    FILTER(STRSTARTS(STR(?y), CONCAT(STR(?cg), "/")))
  }
}"""
)

# Series cuyas versiones tienen dct:conformsTo hacia la ontología ($onto) o una de sus
# versiones ($onto_prefix = "{ontología}/").
CONFORMS_TO_QUERY = (
    PREFIXES
    + """CONSTRUCT {
  ?v dct:conformsTo ?t ; dcat:inSeries ?s ; dcat:version ?ver . ?s dct:title ?st .
} WHERE {
  GRAPH ?s {
    ?s a dcat:DatasetSeries . ?v dcat:inSeries ?s ; dct:conformsTo ?t .
    OPTIONAL { ?v dcat:version ?ver . }
    OPTIONAL { ?s dct:title ?st . }
  }
  FILTER(STRSTARTS(STR(?s), $dataset_ns))
  FILTER(?t = $onto || STRSTARTS(STR(?t), $onto_prefix))
}"""
)

# Series cuyas versiones tienen dcat:theme $concept.
THEME_USAGE_QUERY = (
    PREFIXES
    + """CONSTRUCT {
  ?v dcat:theme $concept ; dcat:inSeries ?s ; dcat:version ?ver . ?s dct:title ?st .
} WHERE {
  GRAPH ?s {
    ?s a dcat:DatasetSeries . ?v dcat:inSeries ?s ; dcat:theme $concept .
    OPTIONAL { ?v dcat:version ?ver . }
    OPTIONAL { ?s dct:title ?st . }
  }
  FILTER(STRSTARTS(STR(?s), $dataset_ns))
}"""
)

# Versiones de ontologías propias con dct:subject $concept.
SUBJECT_USAGE_QUERY = (
    PREFIXES
    + """CONSTRUCT { ?g dct:subject $concept ; dct:title ?t . } WHERE {
  GRAPH ?g {
    ?o a owl:Ontology ; owl:versionIRI ?g ; dct:subject $concept .
    OPTIONAL { ?o dct:title ?t . }
  }
  FILTER(STRSTARTS(STR(?g), $onto_ns))
  FILTER(STRSTARTS(STR(?g), CONCAT(STR(?o), "/")))
}"""
)

ALIGNMENT_RELATIONS = (
    RDFS.subClassOf,
    OWL.equivalentClass,
    RDFS.subPropertyOf,
    OWL.equivalentProperty,
    OWL.sameAs,
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.broadMatch,
    SKOS.narrowMatch,
    SKOS.relatedMatch,
)
BIBO_STATUS = URIRef("http://purl.org/ontology/bibo/status")
# Últimos segmentos (en minúsculas) de los valores de adms:status / bibo:status que se
# leen como «borrador». Cualquier otro valor, o ninguno, es «publicada».
DRAFT_STATUS_TOKENS = frozenset(
    {"underdevelopment", "develop", "development", "draft", "borrador", "unstable"}
)
KIND_ORDER = {"own": 0, "external": 1, "skos_corp": 2, "skos_domain": 3}


# --- Utilidades ---------------------------------------------------------------------------


def _first_literal(graph: Graph, node: Node, *props: URIRef) -> str | None:
    for prop in props:
        value = pick_literal(graph.objects(node, prop))
        if value is not None:
            return value
    return None


def _date(graph: Graph, node: Node, prop: URIRef) -> str | None:
    value = graph.value(node, prop)
    return str(value) if isinstance(value, Literal) else None


def _lang_literals(values: Iterable[Node]) -> list[schemas.LangLiteral]:
    literals = sorted(
        (v for v in values if isinstance(v, Literal)), key=lambda v: (v.language or "", str(v))
    )
    return [schemas.LangLiteral(value=str(v), lang=v.language or None) for v in literals]


def _refs(graph: Graph, nodes: Iterable[Node]) -> list[schemas.ResourceRef]:
    return [ref for n in sorted_nodes(nodes) if (ref := resource_ref(graph, n)) is not None]


def _namespace(graph: Graph, node: Node) -> str | None:
    value = graph.value(node, VANN.preferredNamespaceUri)
    return str(value) if value is not None and not isinstance(value, BNode) else None


def _status(graph: Graph, node: Node) -> schemas.VocabularyStatus:
    for prop in (ADMS.status, BIBO_STATUS):
        for value in graph.objects(node, prop):
            token = str(value).rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1].casefold()
            if token in DRAFT_STATUS_TOKENS:
                return "draft"
    return "published"


def _synthetic(graph: Graph, node: Node, uris: Uris) -> bool:
    return (node, DCT.type, URIRef(uris.synthetic_type)) in graph


def _title(graph: Graph, node: Node) -> str | None:
    return _first_literal(graph, node, DCT.title, RDFS.label, SKOS.prefLabel)


def _description(graph: Graph, node: Node) -> str | None:
    return _first_literal(graph, node, DCT.description, RDFS.comment, SKOS.definition)


def _matches(query: str | None, *texts: str | None) -> bool:
    if not query or not query.strip():
        return True
    needle = normalize(query.strip())
    return any(needle in normalize(text) for text in texts if text)


# --- Ontologías: versiones y métricas ---------------------------------------------------


@dataclass
class OntologyVersions:
    """Cabeceras de todas las versiones de una ontología (sujeto: el versionIRI)."""

    slug: str
    uri: str
    headers: Graph
    uris: Uris

    def nodes(self) -> list[URIRef]:
        nodes = {
            n
            for n in self.headers.subjects(RDF.type, OWL.Ontology)
            if isinstance(n, URIRef) and self._parts(n) is not None
        }
        return sorted(nodes, key=lambda n: version_key(self.version_of(n)), reverse=True)

    def _parts(self, node: Node) -> tuple[str, str] | None:
        parts = self.uris.ontology_version_parts(str(node))
        return parts if parts is not None and parts[0] == self.slug else None

    def version_of(self, node: Node) -> str | None:
        parts = self._parts(node)
        return parts[1] if parts else None

    def current(self) -> URIRef | None:
        nodes = self.nodes()
        return nodes[0] if nodes else None

    def find(self, version: str) -> URIRef | None:
        target = URIRef(self.uris.ontology_version(self.slug, version))
        return target if target in self.nodes() else None


def _ontology_headers(store: TripleStore, prefix: str) -> Graph:
    return store.construct(render(ONTOLOGY_HEADERS_QUERY, prefix=literal(prefix)))


def load_versions(store: TripleStore, uris: Uris, slug: str) -> OntologyVersions:
    uri = uris.ontology(slug)
    versions = OntologyVersions(slug, uri, _ontology_headers(store, f"{uri}/"), uris)
    if not versions.nodes():
        raise NotFoundError(slug)
    return versions


def metrics_records(session: Session, version_iris: list[str]) -> dict[str, Any]:
    if not version_iris:
        return {}
    rows = session.scalars(
        select(OntologyMetricsRecord).where(OntologyMetricsRecord.version_iri.in_(version_iris))
    )
    return {row.version_iri: row for row in rows}


# --- GET /vocabularies --------------------------------------------------------------------


def _external_graph(store: TripleStore, uris: Uris) -> Graph:
    return store.construct(render(GRAPH_QUERY, graph=iri(uris.external_ontologies_graph)))


def list_vocabularies(
    store: TripleStore,
    session: Session,
    uris: Uris,
    *,
    q: str | None = None,
    kind: str | None = None,
    domain: str | None = None,
    catalog: str | None = None,
) -> schemas.VocabularyPage:
    cards: list[schemas.VocabularyCard] = []

    # Ontologías propias: una tarjeta por ontología, con su versión actual.
    headers = _ontology_headers(store, uris.onto_ns)
    by_slug: dict[str, list[URIRef]] = {}
    for node in headers.subjects(RDF.type, OWL.Ontology):
        parts = uris.ontology_version_parts(str(node))
        if isinstance(node, URIRef) and parts is not None:
            by_slug.setdefault(parts[0], []).append(node)
    current_nodes = {
        slug: max(nodes, key=lambda n: version_key(str(n).rsplit("/", 1)[-1]))
        for slug, nodes in by_slug.items()
    }
    records = metrics_records(session, [str(n) for n in current_nodes.values()])
    for slug, node in current_nodes.items():
        record = records.get(str(node))
        summary = None
        if record is not None:
            m = record.metrics
            summary = schemas.MetricsSummary(
                classes=m["classes"], properties=m["object_properties"] + m["data_properties"]
            )
        cards.append(
            schemas.VocabularyCard(
                kind="own",
                slug=slug,
                uri=uris.ontology(slug),
                rdf_type="owl:Ontology",
                title=_title(headers, node),
                prefix=pick_literal(headers.objects(node, VANN.preferredNamespacePrefix)),
                namespace=_namespace(headers, node) or f"{uris.ontology(slug)}#",
                description=_description(headers, node),
                status=_status(headers, node),
                version=str(node).rsplit("/", 1)[-1],
                metrics=summary,
                concepts=None,
                domain=None,
                synthetic=_synthetic(headers, node, uris),
            )
        )

    # Ontologías externas: la referencia y, si ya se han sustituido (decisión 51), el slug
    # de sus versiones y las métricas de la actual.
    from app import external_versions  # evita la importación circular

    external = _external_graph(store, uris)
    infos = {info.uri: info for info in external_versions.externals(external, uris)}
    current_records = metrics_records(
        session, [i.current for i in infos.values() if i.current is not None]
    )
    for node in sorted_nodes(external.subjects(RDF.type, OWL.Ontology)):
        if not isinstance(node, URIRef):
            continue
        info = infos[str(node)]
        record = current_records.get(info.current) if info.current else None
        external_summary = None
        if record is not None:
            m = record.metrics
            external_summary = schemas.MetricsSummary(
                classes=m["classes"], properties=m["object_properties"] + m["data_properties"]
            )
        cards.append(
            schemas.VocabularyCard(
                kind="external",
                slug=info.slug,
                uri=str(node),
                rdf_type="owl:Ontology",
                title=_title(external, node),
                prefix=pick_literal(external.objects(node, VANN.preferredNamespacePrefix)),
                namespace=_namespace(external, node),
                description=_description(external, node),
                status="referenced",
                version=pick_literal(external.objects(node, OWL.versionInfo)),
                metrics=external_summary,
                concepts=None,
                domain=None,
                synthetic=_synthetic(external, node, uris),
            )
        )

    scheme_cards: list[tuple[Node, bool]] = []
    # Esquemas SKOS: corporativos (bajo vocab/corp/) y de dominio (con dct:subject hacia
    # un concepto de vocab/dominio).
    schemes = store.construct(render(SCHEMES_QUERY, vocab_ns=literal(uris.vocab_ns)))
    for node in sorted_nodes(schemes.subjects(RDF.type, SKOS.ConceptScheme)):
        parts = uris.scheme_parts(str(node)) if isinstance(node, URIRef) else None
        if parts is None:
            continue
        slug, corp = parts
        if not corp and not _domain_subjects(schemes, node, uris):
            # Esquemas auxiliares (vocab/dominio, vocab/tipo-dataset): sin dct:subject hacia
            # un dominio, no son SKOS de dominio y no tienen tarjeta.
            continue
        concepts = {
            c
            for c in schemes.subjects(SKOS.inScheme, node)
            if isinstance(c, URIRef) and (c, RDF.type, SKOS.Concept) in schemes
        }
        scheme_cards.append((node, corp))
        cards.append(
            schemas.VocabularyCard(
                kind="skos_corp" if corp else "skos_domain",
                slug=slug,
                uri=str(node),
                rdf_type="skos:ConceptScheme",
                title=_title(schemes, node),
                prefix=pick_literal(schemes.objects(node, VANN.preferredNamespacePrefix)),
                namespace=_namespace(schemes, node) or f"{node}/",
                description=_description(schemes, node),
                status=_status(schemes, node),
                version=_first_literal(schemes, node, OWL.versionInfo, DCAT.version),
                metrics=None,
                concepts=len(concepts),
                domain=None,
                synthetic=_synthetic(schemes, node, uris),
            )
        )

    # Dominio de los esquemas de dominio: su dct:subject, con la etiqueta del concepto de
    # vocab/dominio (una sola consulta, plantilla fija). Ontologías y corporativos: null.
    domain_iris = [
        d for node, corp in scheme_cards if not corp for d in _domain_subjects(schemes, node, uris)
    ]
    labels = vocab_labels(store, uris, domain_iris)
    for card in cards:
        if card.kind == "skos_domain":
            card.domain = _domain_ref(uris, labels, schemes, URIRef(card.uri))

    # Catálogo de cada ontología propia y esquema (decisión 50), en una sola consulta.
    memberships = resource_catalogs(store, uris, [c.uri for c in cards if c.kind != "external"])
    for card in cards:
        if card.kind != "external":
            card.catalog = memberships.get(card.uri)

    counts = schemas.VocabularyCounts(
        own=sum(c.kind == "own" for c in cards),
        external=sum(c.kind == "external" for c in cards),
        skos_corp=sum(c.kind == "skos_corp" for c in cards),
        skos_domain=sum(c.kind == "skos_domain" for c in cards),
    )
    items = [
        c
        for c in cards
        if (kind is None or c.kind == kind)
        and (domain is None or (c.domain is not None and c.domain.slug == domain))
        and (catalog is None or (c.catalog is not None and c.catalog.slug == catalog))
        # Decisión 30: título, descripción, prefijo y URI del recurso (sin BASE_URI, que
        # comparten todos los recursos propios), pero ya no el espacio de nombres.
        and _matches(q, c.title, c.description, c.prefix, uris.searchable_uri(c.uri))
    ]
    items.sort(key=lambda c: (KIND_ORDER[c.kind], normalize(c.title or ""), c.uri))
    return schemas.VocabularyPage(items=items, total=len(items), counts=counts)


# --- Referencias a vocabulario ----------------------------------------------------------


def vocab_labels(store: TripleStore, uris: Uris, values: Iterable[str]) -> Graph:
    """Etiquetas y esquema de IRIs de esquemas o conceptos, desde sus grafos de esquema.

    Las IRIs que no cuelgan de ``{BASE_URI}vocab/`` no se consultan."""
    candidates = sorted({v for v in values if v.startswith(uris.vocab_ns)})
    if not candidates:
        return Graph()
    return store.construct(
        render(VOCAB_LABELS_QUERY, values=iri_list(candidates), vocab_ns=literal(uris.vocab_ns))
    )


def _scheme_ref(labels: Graph, uris: Uris, scheme: Node | None) -> schemas.SchemeRef | None:
    if not isinstance(scheme, URIRef):
        return None
    parts = uris.scheme_parts(str(scheme))
    if parts is None:
        return None
    return schemas.SchemeRef(
        uri=str(scheme),
        slug=parts[0],
        corp=parts[1],
        label=pick_literal(labels.objects(scheme, SKOS.prefLabel)),
    )


def _domain_subjects(graph: Graph, scheme: Node, uris: Uris) -> list[str]:
    return [
        str(s)
        for s in graph.objects(scheme, DCT.subject)
        if uris.domain_of_domain_concept(str(s)) is not None
    ]


def _domain_ref(uris: Uris, labels: Graph, graph: Graph, scheme: Node) -> schemas.DomainRef | None:
    for subject in sorted_nodes(graph.objects(scheme, DCT.subject)):
        slug = uris.domain_of_domain_concept(str(subject))
        if slug:
            return schemas.DomainRef(
                slug=slug,  # type: ignore[arg-type]
                uri=str(subject),
                label=pick_literal(labels.objects(subject, SKOS.prefLabel)),
            )
    return None


def _concept_ref(graph: Graph, labels: Graph, node: Node) -> schemas.ConceptRef | None:
    if not isinstance(node, URIRef):
        return None
    label = pick_literal(graph.objects(node, SKOS.prefLabel)) or pick_literal(
        labels.objects(node, SKOS.prefLabel)
    )
    scheme = graph.value(node, SKOS.inScheme) or labels.value(node, SKOS.inScheme)
    return schemas.ConceptRef(uri=str(node), label=label, scheme=uri_or_none(scheme))


# --- Usos -------------------------------------------------------------------------------


def _dataset_uses(graph: Graph, uris: Uris, link: URIRef) -> list[schemas.DatasetUse]:
    by_series: dict[str, schemas.DatasetUse] = {}
    for version, target in graph.subject_objects(link):
        series = graph.value(version, DCAT.inSeries)
        if not isinstance(series, URIRef) or not isinstance(version, URIRef):
            continue
        slug = uris.series_slug(str(series))
        if slug is None:
            continue
        use = by_series.setdefault(
            str(series),
            schemas.DatasetUse(
                slug=slug,
                uri=str(series),
                title=pick_literal(graph.objects(series, DCT.title)),
                versions=[],
            ),
        )
        number = graph.value(version, DCAT.version)
        use.versions.append(
            schemas.DatasetVersionUse(
                version=str(number) if isinstance(number, Literal) else None,
                uri=str(version),
                conforms_to=str(target) if link == DCT.conformsTo else None,
            )
        )
    for use in by_series.values():
        use.versions.sort(key=lambda v: version_key(v.version), reverse=True)
    return sorted(by_series.values(), key=lambda u: u.slug)


def _ontology_uses(graph: Graph, uris: Uris) -> list[schemas.OntologyUse]:
    by_slug: dict[str, schemas.OntologyUse] = {}
    for version_node in sorted_nodes(graph.subjects(DCT.subject, None)):
        parts = uris.ontology_version_parts(str(version_node))
        if parts is None:
            continue
        slug, version = parts
        use = by_slug.setdefault(
            slug,
            schemas.OntologyUse(
                slug=slug,
                uri=uris.ontology(slug),
                title=pick_literal(graph.objects(version_node, DCT.title)),
                versions=[],
            ),
        )
        use.versions.append(version)
    for use in by_slug.values():
        use.versions.sort(key=version_key, reverse=True)
    return sorted(by_slug.values(), key=lambda u: u.slug)


# --- GET /ontologies/{slug} -------------------------------------------------------------


def _version_ref(versions: OntologyVersions, node: Node) -> schemas.OntologyVersionRef:
    parts = versions.uris.ontology_version_parts(str(node))
    return schemas.OntologyVersionRef(version_iri=str(node), version=parts[1] if parts else None)


def _history(versions: OntologyVersions) -> list[schemas.OntologyVersionSummary]:
    headers = versions.headers
    current = versions.current()
    entries = {
        str(node): schemas.OntologyVersionSummary(
            version=versions.version_of(node),
            version_iri=str(node),
            notes=_first_literal(headers, node, ADMS.versionNotes, SKOS.changeNote),
            issued=_date(headers, node, DCT.issued),
            current=node == current,
            described=True,
        )
        for node in versions.nodes()
    }
    for node in versions.nodes():
        for prior in headers.objects(node, OWL.priorVersion):
            if isinstance(prior, URIRef) and str(prior) not in entries:
                ref = _version_ref(versions, prior)
                entries[str(prior)] = schemas.OntologyVersionSummary(
                    version=ref.version,
                    version_iri=str(prior),
                    notes=None,
                    issued=None,
                    current=False,
                    described=False,
                )
    return sorted(entries.values(), key=lambda e: version_key(e.version), reverse=True)


def _external_info(external: Graph) -> list[tuple[str, URIRef]]:
    """(espacio de nombres, ontología) de las externas, del más largo al más corto."""
    pairs = []
    for node in external.subjects(RDF.type, OWL.Ontology):
        if not isinstance(node, URIRef):
            continue
        namespace = _namespace(external, node)
        for candidate in {namespace, f"{node}#", f"{node}/"}:
            if candidate:
                pairs.append((candidate, node))
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def _owner(target: str, namespaces: list[tuple[str, URIRef]]) -> URIRef | None:
    for namespace, node in namespaces:
        if target.startswith(namespace):
            return node
    return None


def _axiom_scope(graph: Graph, source: Node, relation: URIRef, target: Node) -> str | None:
    for axiom in graph.subjects(OWL.annotatedSource, source):
        if (axiom, OWL.annotatedProperty, relation) in graph and (
            axiom,
            OWL.annotatedTarget,
            target,
        ) in graph:
            value = _first_literal(graph, axiom, RDFS.comment, DCT.description)
            if value:
                return value
    return None


def _alignments(
    graph: Graph, uris: Uris, onto_uri: str, external: Graph, imports: list[str]
) -> list[schemas.Alignment]:
    namespaces = _external_info(external)
    namespaces += sorted(
        ((f"{i}{sep}", URIRef(i)) for i in imports for sep in ("#", "/")),
        key=lambda p: len(p[0]),
        reverse=True,
    )
    term_prefix = f"{onto_uri}#"
    groups: dict[tuple[str | None, str], dict[str, Any]] = {}
    for relation in ALIGNMENT_RELATIONS:
        for source, target in graph.subject_objects(relation):
            if not (isinstance(source, URIRef) and isinstance(target, URIRef)):
                continue
            if not str(source).startswith(term_prefix) or str(target).startswith(uris.base):
                continue
            if str(target).startswith((str(OWL), str(RDFS), str(RDF))):
                continue
            owner = _owner(str(target), namespaces)
            key = (str(owner) if owner else None, str(relation))
            group = groups.setdefault(key, {"owner": owner, "pairs": [], "scopes": []})
            group["pairs"].append(schemas.AlignmentMapping(source=str(source), target=str(target)))
            scope = _axiom_scope(graph, source, relation, target)
            if scope:
                group["scopes"].append(scope)
    result = []
    for (owner_uri, relation), group in groups.items():
        owner = group["owner"]
        described = owner is not None and (owner, RDF.type, OWL.Ontology) in external
        pairs = sorted(group["pairs"], key=lambda p: (p.source, p.target))
        result.append(
            schemas.Alignment(
                target_ontology=owner_uri,
                title=_title(external, owner) if described else None,
                prefix=pick_literal(external.objects(owner, VANN.preferredNamespacePrefix))
                if described
                else None,
                relation=relation,
                scope=sorted(group["scopes"])[0] if group["scopes"] else None,
                version=pick_literal(external.objects(owner, OWL.versionInfo))
                if described
                else None,
                count=len(pairs),
                mappings=pairs,
            )
        )
    return sorted(result, key=lambda a: (a.target_ontology or "~", a.relation))


def _imports(external: Graph, imports: list[str]) -> list[schemas.ImportRef]:
    result = []
    for value in imports:
        node = URIRef(value)
        known = (node, RDF.type, OWL.Ontology) in external
        result.append(
            schemas.ImportRef(
                uri=value,
                title=_title(external, node) if known else None,
                prefix=pick_literal(external.objects(node, VANN.preferredNamespacePrefix)),
                version=pick_literal(external.objects(node, OWL.versionInfo)),
                known=known,
            )
        )
    return result


def _subjects(store: TripleStore, uris: Uris, graph: Graph, node: Node) -> list[schemas.SubjectRef]:
    values = [str(s) for s in graph.objects(node, DCT.subject) if isinstance(s, URIRef)]
    labels = vocab_labels(store, uris, values)
    result = []
    for value in sorted(set(values)):
        subject = URIRef(value)
        if (subject, RDF.type, SKOS.ConceptScheme) in labels:
            result.append(
                schemas.SubjectRef(
                    uri=value,
                    type="scheme",
                    label=pick_literal(labels.objects(subject, SKOS.prefLabel)),
                    scheme=_scheme_ref(labels, uris, subject),
                )
            )
        elif (subject, SKOS.inScheme, None) in labels:
            scheme = labels.value(subject, SKOS.inScheme)
            scheme_labels = vocab_labels(store, uris, [str(scheme)])
            result.append(
                schemas.SubjectRef(
                    uri=value,
                    type="concept",
                    label=pick_literal(labels.objects(subject, SKOS.prefLabel)),
                    scheme=_scheme_ref(scheme_labels, uris, scheme),
                )
            )
        else:
            result.append(schemas.SubjectRef(uri=value, type="unknown", label=None, scheme=None))
    return result


def version_graph(store: TripleStore, version_iri: str) -> Graph:
    return store.construct(render(GRAPH_QUERY, graph=iri(version_iri)))


def get_ontology(
    store: TripleStore, session: Session, uris: Uris, slug: str, version: str | None = None
) -> schemas.OntologyDetail:
    versions = load_versions(store, uris, slug)
    current = versions.current()
    selected = versions.find(version) if version else current
    if selected is None or current is None:
        raise NotFoundError(f"{slug}/{version}")
    graph = version_graph(store, str(selected))
    node = URIRef(versions.uri)
    external = _external_graph(store, uris)
    imports = sorted({str(o) for o in graph.objects(node, OWL.imports) if isinstance(o, URIRef)})
    usage = store.construct(
        render(
            CONFORMS_TO_QUERY,
            dataset_ns=literal(uris.dataset_ns),
            onto=iri(versions.uri),
            onto_prefix=literal(f"{versions.uri}/"),
        )
    )
    record = metrics_records(session, [str(selected)]).get(str(selected))
    metrics = profile = consistency = documentation = None
    if record is not None:
        m = record.metrics
        metrics = schemas.OntologyMetricsRead(
            classes=m["classes"],
            object_properties=m["object_properties"],
            data_properties=m["data_properties"],
            annotation_properties=m["annotation_properties"],
            individuals=m["individuals"],
            logical_axioms=m["logical_axioms"],
            imports=m["imports"],
        )
        profile = schemas.OwlProfile(name=m["profile"], compatible=m["compatible_profiles"])
        documentation = schemas.DocumentationCoverageRead(**m["documentation"])
        c = record.consistency
        consistency = schemas.ConsistencyRead(
            reasoner=c["reasoner"],
            consistent=c["consistent"],
            unsatisfiable_classes=c["unsatisfiable_classes"],
            unsatisfiable=c.get("unsatisfiable", []),
            detail=c.get("detail"),
        )
    prior = graph.value(node, OWL.priorVersion)
    return schemas.OntologyDetail(
        slug=slug,
        uri=versions.uri,
        kind="own",
        status=_status(graph, node),
        synthetic=_synthetic(graph, node, uris),
        title=_title(graph, node),
        description=_description(graph, node),
        metadata=schemas.OntologyMetadata(
            prefix=pick_literal(graph.objects(node, VANN.preferredNamespacePrefix)),
            namespace=_namespace(graph, node) or f"{versions.uri}#",
            title=_title(graph, node),
            description=_description(graph, node),
            creators=_refs(graph, graph.objects(node, DCT.creator)),
            contributors=_refs(graph, graph.objects(node, DCT.contributor)),
            publisher=resource_ref(graph, graph.value(node, DCT.publisher)),
            license=resource_ref(graph, graph.value(node, DCT.license)),
            rights=_first_literal(graph, node, DCT.rights),
            issued=_date(graph, node, DCT.issued),
            modified=_date(graph, node, DCT.modified),
            created=_date(graph, node, DCT.created),
        ),
        versioning=schemas.OntologyVersioning(
            version=versions.version_of(selected),
            version_iri=str(selected),
            current_version=versions.version_of(current),
            prior_version=_version_ref(versions, prior) if isinstance(prior, URIRef) else None,
            backward_compatible_with=[
                _version_ref(versions, n)
                for n in sorted_nodes(graph.objects(node, OWL.backwardCompatibleWith))
                if isinstance(n, URIRef)
            ],
            history=_history(versions),
        ),
        metrics=metrics,
        profile=profile,
        consistency=consistency,
        documentation=documentation,
        metrics_computed_at=record.computed_at if record else None,
        metrics_tool=record.tool if record else None,
        imports=_imports(external, imports),
        alignments=_alignments(graph, uris, versions.uri, external, imports),
        used_by_datasets=_dataset_uses(usage, uris, DCT.conformsTo),
        subjects=_subjects(store, uris, graph, node),
        catalog=resource_catalogs(store, uris, [versions.uri]).get(versions.uri),
    )


def ontology_rdf(store: TripleStore, uris: Uris, slug: str, version: str | None) -> Graph:
    versions = load_versions(store, uris, slug)
    selected = versions.find(version) if version else versions.current()
    if selected is None:
        raise NotFoundError(f"{slug}/{version}")
    return version_graph(store, str(selected))


# --- Esquemas SKOS ----------------------------------------------------------------------


def scheme_graph(store: TripleStore, uris: Uris, slug: str, corp: bool) -> tuple[Graph, URIRef]:
    uri = uris.scheme(slug, corp=corp)
    if uris.scheme_parts(uri) != (slug, corp):
        raise NotFoundError(slug)
    graph = store.construct(render(GRAPH_QUERY, graph=iri(uri)))
    node = URIRef(uri)
    if (node, RDF.type, SKOS.ConceptScheme) not in graph:
        raise NotFoundError(slug)
    return graph, node


def _concepts(graph: Graph, scheme: URIRef) -> set[URIRef]:
    return {
        c
        for c in graph.subjects(SKOS.inScheme, scheme)
        if isinstance(c, URIRef) and (c, RDF.type, SKOS.Concept) in graph
    }


def _is_top(graph: Graph, scheme: URIRef, concept: Node) -> bool:
    return (concept, SKOS.topConceptOf, scheme) in graph or (
        scheme,
        SKOS.hasTopConcept,
        concept,
    ) in graph


def _children(graph: Graph, concepts: set[URIRef], concept: URIRef) -> list[URIRef]:
    found = {n for n in graph.objects(concept, SKOS.narrower) if n in concepts}
    found |= {n for n in graph.subjects(SKOS.broader, concept) if n in concepts}
    return sorted(found, key=lambda n: _label_key(graph, n))


def _label_key(graph: Graph, node: Node) -> tuple[str, str]:
    return (normalize(pick_literal(graph.objects(node, SKOS.prefLabel)) or ""), str(node))


def _slug_in(scheme: URIRef, concept: Node) -> str | None:
    prefix = f"{scheme}/"
    value = str(concept)
    rest = value[len(prefix) :] if value.startswith(prefix) else None
    return rest if rest and is_slug(rest) else None


def _tree(graph: Graph, scheme: URIRef) -> list[schemas.ConceptNode]:
    concepts = _concepts(graph, scheme)
    has_parent = {
        c
        for c in concepts
        if any(p in concepts for p in graph.objects(c, SKOS.broader))
        or any(p in concepts for p in graph.subjects(SKOS.narrower, c))
    }
    roots = [c for c in concepts if _is_top(graph, scheme, c) or c not in has_parent]

    def node_for(concept: URIRef) -> schemas.ConceptNode:
        return schemas.ConceptNode(
            uri=str(concept),
            slug=_slug_in(scheme, concept),
            label=pick_literal(graph.objects(concept, SKOS.prefLabel)),
            top_concept=_is_top(graph, scheme, concept),
            alt_labels=_lang_literals(graph.objects(concept, SKOS.altLabel)),
            deprecated=is_deprecated(graph, concept),
            children=[],
        )

    # Sin recursión (QA-G3-04): pila explícita. Un ciclo no se recorre dos veces (no se
    # baja a un antepasado) y el árbol se corta a MAX_CONCEPT_DEPTH niveles, el máximo que
    # admite la ingesta: lo que hubiera por debajo (solo posible en datos cargados antes del
    # límite) sigue accesible en /schemes/{slug}/concepts/{concepto}.
    roots.sort(key=lambda n: _label_key(graph, n))
    result = [node_for(root) for root in roots]
    stack = [(root, node, frozenset({root}), 0) for root, node in zip(roots, result, strict=True)]
    while stack:
        concept, node, ancestors, depth = stack.pop()
        if depth >= MAX_CONCEPT_DEPTH:
            continue
        for child in _children(graph, concepts, concept):
            if child in ancestors:
                continue
            child_node = node_for(child)
            node.children.append(child_node)
            stack.append((child, child_node, ancestors | {child}, depth + 1))
    return result


def _scheme_kind(uris: Uris, graph: Graph, node: URIRef, corp: bool) -> schemas.SchemeKind:
    """``skos_corp`` bajo ``vocab/corp/``; ``skos_domain`` con ``dct:subject`` hacia un
    dominio; ``auxiliary`` el resto (``vocab/dominio`` y ``vocab/tipo-dataset``)."""
    if corp:
        return "skos_corp"
    return "skos_domain" if _domain_subjects(graph, node, uris) else "auxiliary"


def get_scheme(store: TripleStore, uris: Uris, slug: str, corp: bool) -> schemas.SchemeDetail:
    graph, node = scheme_graph(store, uris, slug, corp)
    subjects = [str(s) for s in graph.objects(node, DCT.subject) if isinstance(s, URIRef)]
    labels = vocab_labels(store, uris, subjects)
    return schemas.SchemeDetail(
        slug=slug,
        corp=corp,
        kind=_scheme_kind(uris, graph, node, corp),
        uri=str(node),
        title=_title(graph, node),
        description=_description(graph, node),
        prefix=pick_literal(graph.objects(node, VANN.preferredNamespacePrefix)),
        namespace=_namespace(graph, node) or f"{node}/",
        version=_first_literal(graph, node, OWL.versionInfo, DCAT.version),
        status=_status(graph, node),
        synthetic=_synthetic(graph, node, uris),
        domain=_domain_ref(uris, labels, graph, node),
        metadata=schemas.SchemeMetadata(
            creators=_refs(graph, graph.objects(node, DCT.creator)),
            publisher=resource_ref(graph, graph.value(node, DCT.publisher)),
            license=resource_ref(graph, graph.value(node, DCT.license)),
            issued=_date(graph, node, DCT.issued),
            modified=_date(graph, node, DCT.modified),
        ),
        concept_count=len(_concepts(graph, node)),
        tree=_tree(graph, node),
        catalog=resource_catalogs(store, uris, [str(node)]).get(str(node)),
    )


def get_concept(
    store: TripleStore, uris: Uris, slug: str, corp: bool, concept_slug: str
) -> schemas.ConceptDetail:
    graph, scheme = scheme_graph(store, uris, slug, corp)
    concept = URIRef(f"{scheme}/{concept_slug}")
    if concept not in _concepts(graph, scheme):
        raise NotFoundError(concept_slug)
    concepts = _concepts(graph, scheme)
    broader = set(graph.objects(concept, SKOS.broader)) | set(
        graph.subjects(SKOS.narrower, concept)
    )
    narrower = set(_children(graph, concepts, concept)) | set(graph.objects(concept, SKOS.narrower))
    related = set(graph.objects(concept, SKOS.related)) | set(graph.subjects(SKOS.related, concept))
    replaced_by = set(graph.objects(concept, DCT.isReplacedBy))
    outside = [str(n) for n in broader | narrower | related | replaced_by if n not in concepts]
    labels = vocab_labels(store, uris, [*outside, str(scheme)])
    term = iri(str(concept))
    datasets = store.construct(
        render(THEME_USAGE_QUERY, concept=term, dataset_ns=literal(uris.dataset_ns))
    )
    ontologies = store.construct(
        render(SUBJECT_USAGE_QUERY, concept=term, onto_ns=literal(uris.onto_ns))
    )

    def refs(nodes: set[Node]) -> list[schemas.ConceptRef]:
        return [
            ref
            for n in sorted_nodes(nodes)
            if n != concept and (ref := _concept_ref(graph, labels, n)) is not None
        ]

    scheme_ref = _scheme_ref(graph, uris, scheme)
    if scheme_ref is None:  # pragma: no cover - scheme_graph ya lo garantiza
        raise NotFoundError(slug)
    return schemas.ConceptDetail(
        uri=str(concept),
        slug=concept_slug,
        scheme=scheme_ref,
        pref_label=pick_literal(graph.objects(concept, SKOS.prefLabel)),
        pref_labels=_lang_literals(graph.objects(concept, SKOS.prefLabel)),
        alt_labels=_lang_literals(graph.objects(concept, SKOS.altLabel)),
        definition=pick_literal(graph.objects(concept, SKOS.definition)),
        definitions=_lang_literals(graph.objects(concept, SKOS.definition)),
        top_concept=_is_top(graph, scheme, concept),
        broader=refs(broader),
        narrower=refs(narrower),
        related=refs(related),
        exact_match=sorted(str(n) for n in graph.objects(concept, SKOS.exactMatch)),
        close_match=sorted(str(n) for n in graph.objects(concept, SKOS.closeMatch)),
        used_by=schemas.ConceptUsage(
            datasets=_dataset_uses(datasets, uris, DCAT.theme),
            ontologies=_ontology_uses(ontologies, uris),
        ),
        deprecated=is_deprecated(graph, concept),
        replaced_by=refs(replaced_by),
    )


def scheme_rdf(store: TripleStore, uris: Uris, slug: str, corp: bool) -> Graph:
    graph, _node = scheme_graph(store, uris, slug, corp)
    return graph


def concept_rdf(store: TripleStore, uris: Uris, slug: str, corp: bool, concept_slug: str) -> Graph:
    """Triples del concepto (y de sus nodos en blanco) dentro del grafo de su esquema."""
    graph, scheme = scheme_graph(store, uris, slug, corp)
    concept = URIRef(f"{scheme}/{concept_slug}")
    if concept not in _concepts(graph, scheme):
        raise NotFoundError(concept_slug)
    result = Graph()
    pending: list[Node] = [concept]
    seen: set[Node] = set()
    while pending:
        subject = pending.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for _s, predicate, obj in graph.triples((subject, None, None)):
            result.add((subject, predicate, obj))
            if isinstance(obj, BNode):
                pending.append(obj)
    return result


# --- Serialización ----------------------------------------------------------------------


def bind_prefixes(graph: Graph, uris: Uris) -> None:
    for prefix, namespace in (
        ("owl", OWL),
        ("rdfs", RDFS),
        ("skos", SKOS),
        ("dct", DCT),
        ("dcat", DCAT),
        ("adms", ADMS),
        ("vann", VANN),
        ("foaf", FOAF),
    ):
        graph.bind(prefix, namespace, override=True, replace=True)


def jsonld_context() -> dict[str, str]:
    return {
        "owl": str(OWL),
        "rdfs": str(RDFS),
        "skos": str(SKOS),
        "dct": str(DCT),
        "dcat": str(DCAT),
        "adms": str(ADMS),
        "vann": str(VANN),
        "foaf": str(FOAF),
    }


class NotSerializableError(ValueError):
    """El grafo no se puede escribir en ese formato (QA-G3-05: RDF/XML no admite
    predicados cuyo nombre local no es un nombre XML, como ``<http://x.example/p/1>``)."""


def serialize(graph: Graph, uris: Uris, rdf_format: str) -> str:
    """``turtle``, ``json-ld`` o ``xml`` (RDF/XML). ``NotSerializableError`` si el RDF/XML
    no puede representar algún predicado."""
    out = Graph()
    for prefix, namespace in graph.namespaces():
        out.bind(prefix, namespace)
    bind_prefixes(out, uris)
    for triple in graph:
        out.add(triple)
    if rdf_format == "json-ld":
        return out.serialize(format="json-ld", context=jsonld_context(), auto_compact=True)
    if rdf_format == "xml":
        try:
            return out.serialize(format="xml")
        except Exception as exc:  # noqa: BLE001 - rdflib lanza tipos variados
            raise NotSerializableError(str(exc)) from None
    return out.serialize(format=rdf_format)
