"""Lectura del catálogo desde el triplestore.

Estrategia: cada operación trae del triplestore un grafo pequeño con ``CONSTRUCT`` (los
valores del usuario solo entran como términos escapados con ``app.sparql``) y el resto se
resuelve en Python con rdflib. Así la misma lógica funciona con Fuseki y con el doble en
memoria, y el texto de búsqueda (``q``) **no llega nunca a SPARQL**: se filtra en Python.

- Catálogo: un ``CONSTRUCT`` con las propiedades de las series, de sus versiones, de las
  distribuciones y de los conceptos SKOS de sus temas.
- Ficha: el grafo con nombre completo de la serie más las etiquetas de sus temas.
"""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS
from rdflib.term import Node

from app import schemas
from app.sparql import iri, literal, render
from app.triplestore import TripleStore
from app.uris import (
    ADMS,
    DCAT,
    DCT,
    EU_ACCESS_RIGHT,
    FOAF,
    IANA_MEDIA_TYPES,
    PROV,
    SKOS,
    VCARD,
    Uris,
    version_key,
)

PREFIXES = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX adms: <http://www.w3.org/ns/adms#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# Proyección para las tarjetas. Cada rama de la UNION trae un tipo de triple, sin
# productos cartesianos entre propiedades multivaluadas.
#
# Solo se leen grafos publicados a propósito (QA-G2-04):
# - Grafos de serie: el grafo con nombre de una serie es su propia URI
#   (``GRAPH ?s { ?s a dcat:DatasetSeries }``), bajo ``{BASE_URI}dataset/``. Una serie
#   guardada en cualquier otro grafo no aparece.
# - Grafo del vocabulario (``$vocab``): de ahí, y solo de ahí, salen las etiquetas de
#   temas y dominios.
CATALOG_QUERY = (
    PREFIXES
    + """CONSTRUCT {
  ?s a dcat:DatasetSeries . ?s ?sp ?so .
  ?v ?vp ?vo .
  ?d ?dp ?do .
  ?c ?cp ?co .
  ?sch skos:prefLabel ?schl .
} WHERE {
  {
    GRAPH ?s { ?s a dcat:DatasetSeries ; ?sp ?so . }
    VALUES ?sp { dct:title dct:description dcat:last dct:type }
    FILTER(STRSTARTS(STR(?s), $dataset_ns))
  } UNION {
    GRAPH ?vs { ?vs a dcat:DatasetSeries . ?v a dcat:Dataset ; dcat:inSeries ?vs ; ?vp ?vo . }
    VALUES ?vp { rdf:type dcat:inSeries dcat:version dct:title dct:description
                 dct:accessRights dcat:theme dct:type dcat:distribution }
    FILTER(STRSTARTS(STR(?vs), $dataset_ns))
  } UNION {
    GRAPH ?ds { ?ds a dcat:DatasetSeries . ?dv dcat:inSeries ?ds ; dcat:distribution ?d .
                ?d ?dp ?do . }
    VALUES ?dp { dcat:mediaType dct:title }
    FILTER(STRSTARTS(STR(?ds), $dataset_ns))
  } UNION {
    GRAPH ?ts { ?ts a dcat:DatasetSeries . ?tv dcat:inSeries ?ts ; dcat:theme ?c . }
    GRAPH $vocab { ?c ?cp ?co . }
    VALUES ?cp { skos:prefLabel skos:altLabel skos:inScheme }
    FILTER(STRSTARTS(STR(?ts), $dataset_ns))
  } UNION {
    GRAPH ?ls { ?ls a dcat:DatasetSeries . ?lv dcat:inSeries ?ls ; dcat:theme ?lc . }
    GRAPH $vocab { ?lc skos:inScheme ?sch . ?sch skos:prefLabel ?schl . }
    FILTER(STRSTARTS(STR(?ls), $dataset_ns))
  }
}"""
)

SERIES_GRAPH_QUERY = "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH $graph { ?s ?p ?o } }"

THEME_LABELS_QUERY = (
    PREFIXES
    + """CONSTRUCT {
  ?c ?cp ?co .
  ?sch skos:prefLabel ?schl .
} WHERE {
  {
    GRAPH $graph { ?v dcat:theme ?c . }
    GRAPH $vocab { ?c ?cp ?co . }
    VALUES ?cp { skos:prefLabel skos:altLabel skos:inScheme }
  } UNION {
    GRAPH $graph { ?v dcat:theme ?c . }
    GRAPH $vocab { ?c skos:inScheme ?sch . ?sch skos:prefLabel ?schl . }
  }
}"""
)

LANG_PREFERENCE = ("es", "", "en")
LABEL_PROPERTIES = (SKOS.prefLabel, RDFS.label, FOAF.name, DCT.title, VCARD.fn)


class NotFoundError(LookupError):
    pass


# --- Utilidades RDF ------------------------------------------------------------------


def pick_literal(values: Iterable[Node]) -> str | None:
    """El literal en el idioma preferido (es, sin idioma, en, cualquiera)."""
    literals = sorted((v for v in values if isinstance(v, Literal)), key=str)
    if not literals:
        return None
    for lang in LANG_PREFERENCE:
        for value in literals:
            if (value.language or "") == lang:
                return str(value)
    return str(literals[0])


def literals_in_language(values: Iterable[Node]) -> list[str]:
    literals = [v for v in values if isinstance(v, Literal)]
    for lang in LANG_PREFERENCE:
        chosen = sorted({str(v) for v in literals if (v.language or "") == lang})
        if chosen:
            return chosen
    return sorted({str(v) for v in literals})


def label_of(graph: Graph, node: Node) -> str | None:
    for prop in LABEL_PROPERTIES:
        label = pick_literal(graph.objects(node, prop))
        if label is not None:
            return label
    return None


def uri_or_none(node: Node | None) -> str | None:
    return str(node) if isinstance(node, URIRef) else None


def resource_ref(graph: Graph, node: Node | None) -> schemas.ResourceRef | None:
    if node is None:
        return None
    if isinstance(node, Literal):
        return schemas.ResourceRef(uri=None, label=str(node))
    return schemas.ResourceRef(uri=uri_or_none(node), label=label_of(graph, node))


def sorted_nodes(nodes: Iterable[Node]) -> list[Node]:
    return sorted(set(nodes), key=lambda n: (isinstance(n, BNode), str(n)))


def access_rights(node: Node | None) -> schemas.AccessRights | None:
    if not isinstance(node, URIRef):
        return None
    value = str(node)
    code = value[len(EU_ACCESS_RIGHT) :] if value.startswith(EU_ACCESS_RIGHT) else None
    return schemas.AccessRights(uri=value, code=code or None)


def media_type(node: Node | None) -> str | None:
    if node is None:
        return None
    value = str(node)
    if isinstance(node, URIRef) and value.startswith(IANA_MEDIA_TYPES):
        return value[len(IANA_MEDIA_TYPES) :]
    return value if isinstance(node, Literal) else None


def date_text(node: Node | None) -> str | None:
    return str(node) if isinstance(node, Literal) else None


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, para buscar «deteccion» y encontrar «detección»."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# --- Modelo intermedio -----------------------------------------------------------------


@dataclass
class SeriesView:
    """Una serie leída de un grafo: resuelve versiones, dominio, temas…"""

    graph: Graph
    node: URIRef
    uris: Uris

    @property
    def uri(self) -> str:
        return str(self.node)

    def versions(self) -> list[URIRef]:
        nodes = [
            v
            for v in self.graph.subjects(DCAT.inSeries, self.node)
            if isinstance(v, URIRef) and (v, RDF.type, DCAT.Dataset) in self.graph
        ]
        return sorted(set(nodes), key=lambda v: version_key(self.version_number(v)), reverse=True)

    def version_number(self, node: URIRef) -> str | None:
        declared = self.graph.value(node, DCAT.version)
        if isinstance(declared, Literal):
            return str(declared)
        return self.uris.version_from_uri(self.uri, str(node))

    def current(self) -> URIRef | None:
        versions = self.versions()
        last = self.graph.value(self.node, DCAT.last)
        if isinstance(last, URIRef) and last in versions:
            return last
        return versions[0] if versions else None

    def find_version(self, number: str) -> URIRef | None:
        for node in self.versions():
            if self.version_number(node) == number:
                return node
        return None

    def title(self) -> str | None:
        current = self.current()
        return pick_literal(self.graph.objects(self.node, DCT.title)) or (
            pick_literal(self.graph.objects(current, DCT.title)) if current else None
        )

    def description(self) -> str | None:
        current = self.current()
        return pick_literal(self.graph.objects(self.node, DCT.description)) or (
            pick_literal(self.graph.objects(current, DCT.description)) if current else None
        )

    def is_synthetic(self, version: URIRef | None = None) -> bool:
        marker = URIRef(self.uris.synthetic_type)
        if (self.node, DCT.type, marker) in self.graph:
            return True
        return version is not None and (version, DCT.type, marker) in self.graph

    def themes(self, version: URIRef | None) -> list[schemas.ThemeRef]:
        if version is None:
            return []
        result = []
        for concept in sorted_nodes(self.graph.objects(version, DCAT.theme)):
            if not isinstance(concept, URIRef):
                continue
            scheme = self.graph.value(concept, SKOS.inScheme)
            result.append(
                schemas.ThemeRef(
                    uri=str(concept),
                    label=pick_literal(self.graph.objects(concept, SKOS.prefLabel)),
                    scheme=uri_or_none(scheme),
                )
            )
        return result

    def theme_search_text(self, version: URIRef | None) -> list[str]:
        if version is None:
            return []
        texts = []
        for concept in self.graph.objects(version, DCAT.theme):
            texts.extend(str(v) for v in self.graph.objects(concept, SKOS.prefLabel))
            texts.extend(str(v) for v in self.graph.objects(concept, SKOS.altLabel))
        return texts

    def domains(self) -> list[schemas.DomainRef]:
        """Dominios del dataset: esquemas de dominio de los temas de la versión actual."""
        current = self.current()
        if current is None:
            return []
        found: dict[str, schemas.DomainRef] = {}
        for concept in sorted_nodes(self.graph.objects(current, DCAT.theme)):
            if not isinstance(concept, URIRef):
                continue
            slugs = [
                (slug, scheme)
                for scheme in self.graph.objects(concept, SKOS.inScheme)
                if (slug := self.uris.domain_of_scheme(str(scheme)))
            ]
            if not slugs:
                # Respaldo si el vocabulario no está cargado: patrón vocab/{esquema}/{slug}.
                slug = self.uris.domain_of_concept_uri(str(concept))
                if slug:
                    slugs = [(slug, URIRef(self.uris.domain_scheme(slug)))]
            for slug, scheme in slugs:
                if slug not in found:
                    found[slug] = schemas.DomainRef(
                        slug=slug,  # type: ignore[arg-type]
                        uri=str(scheme),
                        label=pick_literal(self.graph.objects(scheme, SKOS.prefLabel)),
                    )
        return list(found.values())

    def formats(self, version: URIRef | None) -> list[str]:
        if version is None:
            return []
        result: list[str] = []
        for dist in sorted_nodes(self.graph.objects(version, DCAT.distribution)):
            value = media_type(self.graph.value(dist, DCAT.mediaType)) or pick_literal(
                self.graph.objects(dist, DCT.title)
            )
            if value and value not in result:
                result.append(value)
        return result

    def access_rights(self, version: URIRef | None) -> schemas.AccessRights | None:
        if version is None:
            return None
        return access_rights(self.graph.value(version, DCT.accessRights))


# --- Catálogo --------------------------------------------------------------------------


def _card(view: SeriesView, slug: str) -> schemas.DatasetCard:
    current = view.current()
    domains = view.domains()
    return schemas.DatasetCard(
        slug=slug,
        uri=view.uri,
        title=view.title(),
        description=view.description(),
        domain=domains[0] if domains else None,
        domains=domains,
        themes=view.themes(current),
        access_rights=view.access_rights(current),
        formats=view.formats(current),
        current_version=view.version_number(current) if current else None,
        synthetic=view.is_synthetic(current),
    )


def _matches(view: SeriesView, query: str) -> bool:
    needle = normalize(query)
    current = view.current()
    texts = [view.title() or "", view.description() or "", *view.theme_search_text(current)]
    if current is not None:
        texts.extend(str(v) for v in view.graph.objects(current, DCT.title))
        texts.extend(str(v) for v in view.graph.objects(current, DCT.description))
    return any(needle in normalize(text) for text in texts)


def list_datasets(
    store: TripleStore,
    uris: Uris,
    *,
    q: str | None = None,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> schemas.DatasetPage:
    graph = store.construct(
        render(CATALOG_QUERY, dataset_ns=literal(uris.dataset_ns), vocab=iri(uris.vocab_graph))
    )
    cards: list[schemas.DatasetCard] = []
    for node in sorted_nodes(graph.subjects(RDF.type, DCAT.DatasetSeries)):
        if not isinstance(node, URIRef):
            continue
        slug = uris.series_slug(str(node))
        if slug is None:
            continue
        view = SeriesView(graph, node, uris)
        if q and q.strip() and not _matches(view, q.strip()):
            continue
        card = _card(view, slug)
        if domain and domain not in {d.slug for d in card.domains}:
            continue
        cards.append(card)
    cards.sort(key=lambda c: (normalize(c.title or ""), c.slug))
    start = (page - 1) * page_size
    return schemas.DatasetPage(
        items=cards[start : start + page_size], total=len(cards), page=page, page_size=page_size
    )


# --- Ficha -----------------------------------------------------------------------------


def series_graph(store: TripleStore, uris: Uris, slug: str) -> Graph:
    """Grafo con nombre de la serie (sin etiquetas de vocabulario). Vacío = no existe."""
    return store.construct(render(SERIES_GRAPH_QUERY, graph=iri(uris.series(slug))))


def load_series(store: TripleStore, uris: Uris, slug: str) -> SeriesView:
    graph = series_graph(store, uris, slug)
    node = URIRef(uris.series(slug))
    if (node, RDF.type, DCAT.DatasetSeries) not in graph:
        raise NotFoundError(slug)
    labels = store.construct(
        render(THEME_LABELS_QUERY, graph=iri(uris.series(slug)), vocab=iri(uris.vocab_graph))
    )
    for triple in labels:
        graph.add(triple)
    return SeriesView(graph, node, uris)


def _provenance(graph: Graph, version: URIRef) -> list[schemas.ProvenanceStep]:
    """Cadena lineal: actividad <- entidad usada <- actividad que la generó <- …"""
    steps: list[schemas.ProvenanceStep] = []
    visited: set[Node] = set()
    activity = graph.value(version, PROV.wasGeneratedBy)
    while activity is not None and activity not in visited:
        visited.add(activity)
        agents = [
            ref
            for agent in sorted_nodes(graph.objects(activity, PROV.wasAssociatedWith))
            if (ref := resource_ref(graph, agent)) is not None
        ]
        steps.append(
            schemas.ProvenanceStep(
                kind="activity",
                uri=uri_or_none(activity),
                label=label_of(graph, activity),
                agents=agents,
            )
        )
        used = sorted_nodes(graph.objects(activity, PROV.used))
        if not used or used[0] in visited:
            break
        entity = used[0]
        visited.add(entity)
        steps.append(
            schemas.ProvenanceStep(
                kind="entity", uri=uri_or_none(entity), label=label_of(graph, entity), agents=[]
            )
        )
        activity = graph.value(entity, PROV.wasGeneratedBy)
    steps.reverse()
    return steps


def _first(graph: Graph, subjects: Iterable[Node | None], prop: URIRef) -> Node | None:
    for subject in subjects:
        if subject is None:
            continue
        value = graph.value(subject, prop)
        if value is not None:
            return value
    return None


def _version_detail(view: SeriesView, version: URIRef) -> schemas.VersionDetail:
    graph = view.graph
    access = view.access_rights(version)
    distributions = [
        schemas.DistributionRead(
            uri=str(dist),
            title=pick_literal(graph.objects(dist, DCT.title)),
            media_type=media_type(graph.value(dist, DCAT.mediaType)),
            media_type_uri=uri_or_none(graph.value(dist, DCAT.mediaType)),
            access_url=uri_or_none(graph.value(dist, DCAT.accessURL)),
            access_rights=access_rights(graph.value(dist, DCT.accessRights)) or access,
        )
        for dist in sorted_nodes(graph.objects(version, DCAT.distribution))
        if isinstance(dist, URIRef)
    ]
    previous = graph.value(version, DCAT.previousVersion)
    previous_ref = None
    if isinstance(previous, URIRef):
        previous_ref = schemas.VersionRef(uri=str(previous), version=view.version_number(previous))
    # Metadatos de la versión; publisher, contacto y licencia se heredan de la serie.
    owners = (version, view.node)
    metadata = schemas.DcatMetadata(
        publisher=resource_ref(graph, _first(graph, owners, DCT.publisher)),
        contact_point=resource_ref(graph, _first(graph, owners, DCAT.contactPoint)),
        license=resource_ref(graph, _first(graph, owners, DCT.license)),
        access_rights=access,
        issued=date_text(graph.value(version, DCT.issued)),
        modified=date_text(graph.value(version, DCT.modified)),
        is_referenced_by=[
            ref
            for node in sorted_nodes(graph.objects(version, DCT.isReferencedBy))
            if (ref := resource_ref(graph, node)) is not None
        ],
        themes=view.themes(version),
        conforms_to=[
            ref
            for node in sorted_nodes(graph.objects(version, DCT.conformsTo))
            if (ref := resource_ref(graph, node)) is not None
        ],
    )
    return schemas.VersionDetail(
        uri=str(version),
        version=view.version_number(version),
        title=pick_literal(graph.objects(version, DCT.title)),
        description=pick_literal(graph.objects(version, DCT.description)),
        keywords=literals_in_language(graph.objects(version, DCAT.keyword)),
        version_notes=pick_literal(graph.objects(version, ADMS.versionNotes)),
        previous_version=previous_ref,
        in_series=view.uri,
        synthetic=view.is_synthetic(version),
        distributions=distributions,
        provenance=_provenance(graph, version),
        metadata=metadata,
    )


def _history(view: SeriesView) -> list[schemas.VersionSummary]:
    graph = view.graph
    current = view.current()
    described = view.versions()
    entries = {
        str(node): schemas.VersionSummary(
            version=view.version_number(node),
            uri=str(node),
            notes=pick_literal(graph.objects(node, ADMS.versionNotes)),
            issued=date_text(graph.value(node, DCT.issued)),
            modified=date_text(graph.value(node, DCT.modified)),
            current=node == current,
            described=True,
        )
        for node in described
    }
    # Versiones anteriores solo referenciadas (dcat:previousVersion sin descripción).
    for node in described:
        previous = graph.value(node, DCAT.previousVersion)
        if isinstance(previous, URIRef) and str(previous) not in entries:
            entries[str(previous)] = schemas.VersionSummary(
                version=view.version_number(previous),
                uri=str(previous),
                notes=None,
                issued=None,
                modified=None,
                current=False,
                described=False,
            )
    return sorted(entries.values(), key=lambda e: version_key(e.version), reverse=True)


def get_dataset(
    store: TripleStore, uris: Uris, slug: str, version: str | None = None
) -> schemas.DatasetDetail:
    view = load_series(store, uris, slug)
    current = view.current()
    selected = current
    if version is not None:
        selected = view.find_version(version)
        if selected is None:
            raise NotFoundError(f"{slug}/{version}")
    domains = view.domains()
    return schemas.DatasetDetail(
        slug=slug,
        uri=view.uri,
        title=view.title(),
        description=view.description(),
        synthetic=view.is_synthetic(current),
        domain=domains[0] if domains else None,
        domains=domains,
        current_version=view.version_number(current) if current else None,
        version=_version_detail(view, selected) if selected is not None else None,
        versions=_history(view),
    )


# --- RDF ------------------------------------------------------------------------------


def version_rdf(store: TripleStore, uris: Uris, slug: str, version: str | None) -> Graph:
    """RDF de una versión: sus triples y los de lo que cuelga de ella dentro del grafo de
    la serie (distribuciones, actividades PROV, nodos en blanco, agentes), sin la serie
    ni las otras versiones."""
    graph = series_graph(store, uris, slug)
    view = SeriesView(graph, URIRef(uris.series(slug)), uris)
    if (view.node, RDF.type, DCAT.DatasetSeries) not in graph:
        raise NotFoundError(slug)
    target = view.find_version(version) if version else view.current()
    if target is None:
        raise NotFoundError(f"{slug}/{version}")
    excluded = {view.node, *(v for v in view.versions() if v != target)}
    result = _new_graph(graph, uris)
    pending: list[Node] = [target]
    seen: set[Node] = set()
    while pending:
        subject = pending.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for _, predicate, obj in graph.triples((subject, None, None)):
            result.add((subject, predicate, obj))
            if obj not in excluded and obj not in seen and (obj, None, None) in graph:
                pending.append(obj)
    return result


def series_rdf(store: TripleStore, uris: Uris, slug: str) -> Graph:
    """RDF completo de la serie (su grafo con nombre)."""
    graph = series_graph(store, uris, slug)
    if (URIRef(uris.series(slug)), RDF.type, DCAT.DatasetSeries) not in graph:
        raise NotFoundError(slug)
    result = _new_graph(graph, uris)
    for triple in graph:
        result.add(triple)
    return result


def _new_graph(_source: Graph, uris: Uris) -> Graph:
    graph = Graph()
    bind_prefixes(graph, uris)
    return graph


def bind_prefixes(graph: Graph, uris: Uris) -> None:
    for prefix, namespace in (
        ("dcat", DCAT),
        ("dct", DCT),
        ("adms", ADMS),
        ("prov", PROV),
        ("foaf", FOAF),
        ("skos", SKOS),
        ("rdfs", RDFS),
        ("itotd", uris.dataset_ns),
        ("itota", uris.activity_ns),
    ):
        graph.bind(prefix, namespace, override=True, replace=True)


def jsonld_context(uris: Uris) -> dict[str, str]:
    return {
        "dcat": str(DCAT),
        "dct": str(DCT),
        "adms": str(ADMS),
        "prov": str(PROV),
        "foaf": str(FOAF),
        "skos": str(SKOS),
        "rdfs": str(RDFS),
        "itotd": uris.dataset_ns,
        "itota": uris.activity_ns,
    }


def serialize(graph: Graph, uris: Uris, rdf_format: str) -> str:
    if rdf_format == "json-ld":
        return graph.serialize(format="json-ld", context=jsonld_context(uris), auto_compact=True)
    return graph.serialize(format="turtle")
