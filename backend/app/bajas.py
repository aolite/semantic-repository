"""Catálogos, pertenencia de las series y bajas (decisión 49, ``semantic/uris.md``).

Funciones de bajo nivel sobre el triplestore, sin dependencias de la ingesta (la usan
``app.ingest``, ``app.catalogs`` y los routers):

- **Pertenencia.** Cada serie está en exactamente un catálogo ``{BASE_URI}catalogo/{slug}``:
  ``<catálogo> dcat:dataset <serie>`` vive en el grafo del catálogo, no en el de la serie.
  ``series_catalogs`` encuentra en qué catálogos está una serie y ``set_membership`` la
  deja en uno solo (alta o traslado).
- **Catálogo raíz.** ``{BASE_URI}catalogo`` agrupa los catálogos con ``dcat:catalog``; el
  backend añade o quita ese triple al crear o dar de baja un catálogo.
- **Lápidas.** Un catálogo o una serie dados de baja quedan solo como lápida en el grafo
  ``{BASE_URI}bajas`` (forma ``itsh:BajaShape``): ``rdf:type prov:Entity``, ``dct:title``,
  ``adms:status …/Withdrawn`` y ``prov:invalidatedAtTime``. Ese grafo no se publica.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from app.sparql import iri, literal, render
from app.triplestore import TripleStore
from app.uris import ADMS, DCAT, DCT, PROV, Uris

WITHDRAWN_STATUS = URIRef("http://purl.org/adms/status/Withdrawn")

_SUBJECT_QUERY = "CONSTRUCT { $s ?p ?o } WHERE { GRAPH $graph { $s ?p ?o } }"

_MEMBERSHIP_QUERY = """PREFIX dcat: <http://www.w3.org/ns/dcat#>
CONSTRUCT { ?c dcat:dataset $series } WHERE {
  GRAPH ?c { ?c dcat:dataset $series }
  FILTER(STRSTARTS(STR(?c), $catalog_ns))
}"""


@dataclass(frozen=True)
class Tombstone:
    """Ficha mínima de un recurso dado de baja."""

    uri: str
    titles: list[Literal]
    withdrawn_at: str | None

    @property
    def title(self) -> str | None:
        from app.catalog import pick_literal  # evita la importación circular

        return pick_literal(self.titles)

    def graph(self) -> Graph:
        result = Graph()
        node = URIRef(self.uri)
        result.add((node, RDF.type, PROV.Entity))
        for title in self.titles:
            result.add((node, DCT.title, title))
        result.add((node, ADMS.status, WITHDRAWN_STATUS))
        if self.withdrawn_at is not None:
            result.add(
                (node, PROV.invalidatedAtTime, Literal(self.withdrawn_at, datatype=XSD.dateTime))
            )
        return result


def get_tombstone(store: TripleStore, uris: Uris, uri: str) -> Tombstone | None:
    """La lápida de ``uri`` en el grafo de bajas, o ``None`` si no se ha dado de baja."""
    graph = store.construct(render(_SUBJECT_QUERY, s=iri(uri), graph=iri(uris.withdrawn_graph)))
    node = URIRef(uri)
    if (node, PROV.invalidatedAtTime, None) not in graph:
        return None
    when = graph.value(node, PROV.invalidatedAtTime)
    titles = sorted((t for t in graph.objects(node, DCT.title) if isinstance(t, Literal)), key=str)
    return Tombstone(uri=uri, titles=titles, withdrawn_at=str(when) if when is not None else None)


def tombstone_graph(uri: str, titles: list[Literal], when: datetime | None = None) -> Graph:
    moment = (when or datetime.now(UTC)).replace(microsecond=0)
    return Tombstone(uri=uri, titles=titles, withdrawn_at=moment.isoformat()).graph()


def add_tombstone(store: TripleStore, uris: Uris, tombstone: Graph) -> None:
    """Añade la lápida al grafo de bajas (lectura y escritura del grafo completo)."""
    graph = store.get_graph(uris.withdrawn_graph)
    for triple in tombstone:
        graph.add(triple)
    store.put_graph(uris.withdrawn_graph, graph)


def withdrawn_uris(store: TripleStore, uris: Uris) -> set[str]:
    """URIs con lápida (para ``load-semantic``, que omite los recursos dados de baja)."""
    graph = store.get_graph(uris.withdrawn_graph)
    return {str(s) for s in graph.subjects(PROV.invalidatedAtTime, None)}


# --- Catálogos ------------------------------------------------------------------------


def catalog_graph(store: TripleStore, uris: Uris, slug: str) -> Graph:
    return store.get_graph(uris.catalog(slug))


def catalog_exists(store: TripleStore, catalog_uri: str) -> bool:
    graph = store.get_graph(catalog_uri)
    return (URIRef(catalog_uri), RDF.type, DCAT.Catalog) in graph


def add_to_root(store: TripleStore, uris: Uris, catalog_uri: str) -> None:
    graph = store.get_graph(uris.root_catalog)
    triple = (URIRef(uris.root_catalog), DCAT.catalog, URIRef(catalog_uri))
    if triple not in graph:
        graph.add(triple)
        store.put_graph(uris.root_catalog, graph)


def remove_from_root(store: TripleStore, uris: Uris, catalog_uri: str) -> None:
    graph = store.get_graph(uris.root_catalog)
    triple = (URIRef(uris.root_catalog), DCAT.catalog, URIRef(catalog_uri))
    if triple in graph:
        graph.remove(triple)
        store.put_graph(uris.root_catalog, graph)


# --- Pertenencia de las series ---------------------------------------------------------


def series_catalogs(store: TripleStore, uris: Uris, series_uri: str) -> set[str]:
    """Catálogos ``{BASE_URI}catalogo/{slug}`` cuyo grafo lista la serie."""
    graph = store.construct(
        render(_MEMBERSHIP_QUERY, series=iri(series_uri), catalog_ns=literal(uris.catalog_ns))
    )
    return {str(c) for c in graph.subjects(DCAT.dataset, URIRef(series_uri))}


def remove_membership(store: TripleStore, catalog_uri: str, series_uri: str) -> None:
    graph = store.get_graph(catalog_uri)
    triple = (URIRef(catalog_uri), DCAT.dataset, URIRef(series_uri))
    if triple in graph:
        graph.remove(triple)
        store.put_graph(catalog_uri, graph)


def add_membership(store: TripleStore, catalog_uri: str, series_uri: str) -> bool:
    graph = store.get_graph(catalog_uri)
    triple = (URIRef(catalog_uri), DCAT.dataset, URIRef(series_uri))
    if triple in graph:
        return False
    graph.add(triple)
    store.put_graph(catalog_uri, graph)
    return True


def set_membership(store: TripleStore, uris: Uris, series_uri: str, catalog_uri: str) -> set[str]:
    """Deja la serie solo en ``catalog_uri``. Devuelve los catálogos de los que se quitó."""
    previous = series_catalogs(store, uris, series_uri) - {catalog_uri}
    add_membership(store, catalog_uri, series_uri)
    for other in previous:
        remove_membership(store, other, series_uri)
    return previous
