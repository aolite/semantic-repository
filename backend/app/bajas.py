"""Catálogos, pertenencia de las series y bajas (decisión 49, ``semantic/uris.md``).

Funciones de bajo nivel sobre el triplestore, sin dependencias de la ingesta (la usan
``app.ingest``, ``app.catalogs`` y los routers):

- **Pertenencia.** Cada serie está en exactamente un catálogo ``{BASE_URI}catalogo/{slug}``:
  ``<catálogo> dcat:dataset <serie>`` vive en el grafo del catálogo, no en el de la serie.
  ``series_catalogs`` encuentra en qué catálogos está una serie y ``set_membership`` la
  deja en uno solo (alta o traslado).
- **Catálogo raíz.** ``{BASE_URI}catalogo`` agrupa los catálogos con ``dcat:catalog``; el
  backend añade o quita ese triple al crear o dar de baja un catálogo.
- **Pertenencia de esquemas y ontologías (decisión 50).** Igual que las series, con
  ``<catálogo> dcat:resource <recurso>`` en el grafo del catálogo (``resource_catalogs``,
  ``set_resource_membership``).
- **Lápidas.** Un catálogo, una serie, un esquema o una ontología dados de baja quedan
  solo como lápida en el grafo ``{BASE_URI}bajas`` (forma ``itsh:BajaShape``):
  ``rdf:type prov:Entity``, ``dct:title``, ``adms:status …/Withdrawn`` y
  ``prov:invalidatedAtTime``. Ese grafo no se publica.

Escrituras atómicas (QA-49-01): ninguna función lee un grafo entero para reescribirlo.
Añadir triples es un ``POST`` del Graph Store Protocol (``append_graph``, se añade al
grafo sin tocar lo demás) y quitarlos, un SPARQL Update ``DELETE DATA`` o
``DELETE … WHERE`` con solo IRIs validadas por ``app.sparql.iri``; mover una serie de
catálogo es **una** petición de Update con las dos operaciones, que Fuseki aplica en una
transacción. Así dos peticiones simultáneas no se pierden los cambios la una a la otra.
Las comprobaciones que tienen que ir juntas con su escritura (slug libre y crear, catálogo
vacío y dar de baja…) se serializan además con ``app.write_lock``.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from app.sparql import SparqlTerm, iri, literal, render
from app.triplestore import TripleStore
from app.uris import ADMS, DCAT, DCT, PROV, Uris

WITHDRAWN_STATUS = URIRef("http://purl.org/adms/status/Withdrawn")

_SUBJECT_QUERY = "CONSTRUCT { $s ?p ?o } WHERE { GRAPH $graph { $s ?p ?o } }"

# SPARQL Update solo con IRIs (``app.sparql.iri``): nunca literales ni texto del usuario.
_DELETE_DATA = "DELETE DATA { GRAPH $graph { $s $p $o } }"
_SET_MEMBERSHIP = """DELETE { GRAPH ?c { ?c $prop $member } }
WHERE { GRAPH ?c { ?c $prop $member }
  FILTER(STRSTARTS(STR(?c), $catalog_ns) && ?c != $target) } ;
INSERT DATA { GRAPH $target { $target $prop $member } }"""

_MEMBERSHIP_QUERY = """CONSTRUCT { ?c $prop $member } WHERE {
  GRAPH ?c { ?c $prop $member }
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
    """Añade la lápida al grafo de bajas sin reescribirlo (``append_graph``, atómico)."""
    store.append_graph(uris.withdrawn_graph, tombstone)


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


def _triple(subject: str, predicate: URIRef, obj: str) -> Graph:
    graph = Graph()
    graph.add((URIRef(subject), predicate, URIRef(obj)))
    return graph


def _delete_data(graph_uri: str, subject: str, predicate: URIRef, obj: str) -> str:
    """``DELETE DATA`` de un triple de IRIs (validadas: nunca texto del usuario)."""
    return render(
        _DELETE_DATA, graph=iri(graph_uri), s=iri(subject), p=iri(str(predicate)), o=iri(obj)
    )


def add_to_root(store: TripleStore, uris: Uris, catalog_uri: str) -> None:
    """``<raíz> dcat:catalog <catálogo>``, añadido sin reescribir el raíz."""
    store.append_graph(uris.root_catalog, _triple(uris.root_catalog, DCAT.catalog, catalog_uri))


def remove_from_root(store: TripleStore, uris: Uris, catalog_uri: str) -> None:
    store.update(_delete_data(uris.root_catalog, uris.root_catalog, DCAT.catalog, catalog_uri))


# --- Pertenencia de las series ---------------------------------------------------------


def _member_catalogs(store: TripleStore, uris: Uris, prop: URIRef, member: str) -> set[str]:
    graph = store.construct(
        render(
            _MEMBERSHIP_QUERY,
            prop=iri(str(prop)),
            member=iri(member),
            catalog_ns=literal(uris.catalog_ns),
        )
    )
    return {str(c) for c in graph.subjects(prop, URIRef(member))}


def _set_member(
    store: TripleStore, uris: Uris, prop: URIRef, member: str, catalog_uri: str
) -> set[str]:
    previous = _member_catalogs(store, uris, prop, member) - {catalog_uri}
    store.update(
        render(
            _SET_MEMBERSHIP,
            prop=iri(str(prop)),
            member=iri(member),
            target=iri(catalog_uri),
            catalog_ns=literal(uris.catalog_ns),
        )
    )
    return previous


def series_catalogs(store: TripleStore, uris: Uris, series_uri: str) -> set[str]:
    """Catálogos ``{BASE_URI}catalogo/{slug}`` cuyo grafo lista la serie."""
    return _member_catalogs(store, uris, DCAT.dataset, series_uri)


def remove_membership(store: TripleStore, catalog_uri: str, series_uri: str) -> None:
    store.update(_delete_data(catalog_uri, catalog_uri, DCAT.dataset, series_uri))


def add_membership(store: TripleStore, catalog_uri: str, series_uri: str) -> None:
    """``<catálogo> dcat:dataset <serie>``, añadido sin reescribir el catálogo."""
    store.append_graph(catalog_uri, _triple(catalog_uri, DCAT.dataset, series_uri))


def set_membership(store: TripleStore, uris: Uris, series_uri: str, catalog_uri: str) -> set[str]:
    """Deja la serie solo en ``catalog_uri``, en **una** petición de Update (quita la
    pertenencia a cualquier otro catálogo y la añade al destino, atómicamente). Devuelve
    los catálogos de los que se quitó."""
    return _set_member(store, uris, DCAT.dataset, series_uri, catalog_uri)


# --- Pertenencia de esquemas SKOS y ontologías propias (decisión 50) -------------------
#
# «<{BASE_URI}catalogo/{slug}> dcat:resource <recurso>», en el grafo del catálogo (no en el
# del esquema ni en el de la versión de ontología). Mismas escrituras atómicas que las
# series.


_WITHDRAW_RESOURCE = """INSERT { GRAPH $bajas { $tombstone } } WHERE { $binds } ;
DELETE { GRAPH ?c { ?c <http://www.w3.org/ns/dcat#resource> $member } }
WHERE { GRAPH ?c { ?c <http://www.w3.org/ns/dcat#resource> $member }
  FILTER(STRSTARTS(STR(?c), $catalog_ns)) }"""
_DROP_GRAPH = "DROP SILENT GRAPH $graph"
_LANG_TAG = re.compile(r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$")
_XSD_STRING = str(XSD.string)


def _string_expression(value: str) -> str:
    """Expresión SPARQL que vale ``value`` sin poner nunca ``\\u`` en el texto de la
    petición: cada barra invertida va en su propio literal (``"\\\\"``) y el resto en
    trozos escapados con ``app.sparql.literal``, unidos con ``CONCAT``."""
    parts = value.split("\\")
    pieces: list[str] = []
    for index, part in enumerate(parts):
        if index:
            pieces.append(literal("\\").text)
        if part:
            pieces.append(literal(part).text)
    if not pieces:
        pieces.append(literal("").text)
    return f"CONCAT({', '.join(pieces)})"


def _literal_expression(value: Literal) -> str:
    text = _string_expression(str(value))
    if value.language:
        if not _LANG_TAG.match(value.language):
            raise ValueError("Etiqueta de idioma no válida")
        return f"STRLANG({text}, {literal(value.language).text})"
    if value.datatype is not None and str(value.datatype) != _XSD_STRING:
        return f"STRDT({text}, {iri(str(value.datatype)).text})"
    return text


def withdraw_resource_update(
    uris: Uris, resource_uri: str, tombstone: Graph, graphs: list[str]
) -> str:
    """Baja de un esquema o de una ontología propia (decisión 50) en **una** petición de
    SPARQL Update, que Fuseki aplica en una transacción (QA-50-04): añade la lápida al
    grafo de bajas, quita la pertenencia a cualquier catálogo y borra ``graphs`` (el del
    esquema o los de todas las versiones). Así nunca queda una lápida con el grafo vivo
    ni un recurso borrado sin lápida.

    Los literales de la lápida (títulos que vienen del recurso) no se escriben con
    ``INSERT DATA`` sino con ``BIND`` de expresiones seguras (``_literal_expression``):
    ``app.sparql.literal`` no admite ``\\u`` en el valor y un título puede tenerlo."""
    patterns: list[str] = []
    binds: list[str] = []
    for index, (subject, predicate, obj) in enumerate(sorted(tombstone)):
        if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
            raise ValueError("La lápida solo lleva IRIs como sujeto y predicado")
        if isinstance(obj, URIRef):
            value = iri(str(obj)).text
        elif isinstance(obj, Literal):
            value = f"?o{index}"
            binds.append(f"BIND({_literal_expression(obj)} AS {value})")
        else:
            raise ValueError("La lápida no lleva nodos en blanco")
        patterns.append(f"{iri(str(subject)).text} {iri(str(predicate)).text} {value} .")
    # Los patrones y los BIND se han construido solo con ``iri`` y ``literal``; van como
    # SparqlTerm para que ``render`` no vuelva a interpretar un «$» de un título.
    request = render(
        _WITHDRAW_RESOURCE,
        tombstone=SparqlTerm(" ".join(patterns)),
        binds=SparqlTerm(" ".join(binds)),
        bajas=iri(uris.withdrawn_graph),
        member=iri(resource_uri),
        catalog_ns=literal(uris.catalog_ns),
    )
    drops = [render(_DROP_GRAPH, graph=iri(g)) for g in sorted(set(graphs))]
    return " ;\n".join([request, *drops])


def resource_catalogs(store: TripleStore, uris: Uris, resource_uri: str) -> set[str]:
    """Catálogos ``{BASE_URI}catalogo/{slug}`` que listan el esquema o la ontología."""
    return _member_catalogs(store, uris, DCAT.resource, resource_uri)


def remove_resource_membership(store: TripleStore, catalog_uri: str, resource_uri: str) -> None:
    store.update(_delete_data(catalog_uri, catalog_uri, DCAT.resource, resource_uri))


def set_resource_membership(
    store: TripleStore, uris: Uris, resource_uri: str, catalog_uri: str
) -> set[str]:
    """Deja el esquema o la ontología solo en ``catalog_uri`` (una petición de Update).
    Devuelve los catálogos de los que se quitó."""
    return _set_member(store, uris, DCAT.resource, resource_uri, catalog_uri)


# --- Reescribir un sujeto de un grafo compartido (decisión 51) ------------------------

_DELETE_SUBJECT = """DELETE { GRAPH $graph { ?b ?bp ?bo } }
WHERE { GRAPH $graph { $s ?p ?b . FILTER(isBlank(?b)) ?b ?bp ?bo } } ;
DELETE WHERE { GRAPH $graph { $s ?p ?o } }"""
_INSERT_SUBJECT = "INSERT { GRAPH $graph { $patterns } } WHERE { $binds }"


def subject_description(graph: Graph, subject: URIRef) -> Graph:
    """Los triples de ``subject`` y de los nodos en blanco que cuelgan de él."""
    result = Graph()
    pending: list = [subject]
    seen: set = set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        for triple in graph.triples((node, None, None)):
            result.add(triple)
            if isinstance(triple[2], BNode):
                pending.append(triple[2])
    return result


def replace_subject_update(graph_uri: str, subject: str, description: Graph) -> str:
    """**Una** petición de SPARQL Update que sustituye, dentro de ``graph_uri``, lo que se
    dice de ``subject`` (y de los nodos en blanco que cuelgan directamente de él, como el
    publicador) por ``description``, sin tocar el resto del grafo. Fuseki la aplica en una
    transacción: nunca queda el sujeto a medias.

    Los literales van con ``BIND`` de expresiones seguras (``_literal_expression``), como
    en ``withdraw_resource_update``; los nodos en blanco, como ``_:bN`` de la plantilla
    (uno nuevo en cada petición)."""
    labels: dict[BNode, str] = {}
    patterns: list[str] = []
    binds: list[str] = []

    def term(node: object, index: int, position: str) -> str:
        if isinstance(node, URIRef):
            return iri(str(node)).text
        if isinstance(node, BNode) and position != "p":
            return labels.setdefault(node, f"_:b{len(labels)}")
        if isinstance(node, Literal) and position == "o":
            name = f"?o{index}"
            binds.append(f"BIND({_literal_expression(node)} AS {name})")
            return name
        raise ValueError("Término no admitido en la descripción del sujeto")

    for index, (s, p, o) in enumerate(sorted(description)):
        patterns.append(f"{term(s, index, 's')} {term(p, index, 'p')} {term(o, index, 'o')} .")
    delete = render(_DELETE_SUBJECT, graph=iri(graph_uri), s=iri(subject))
    if not patterns:
        return delete
    insert = render(
        _INSERT_SUBJECT,
        graph=iri(graph_uri),
        patterns=SparqlTerm(" ".join(patterns)),
        binds=SparqlTerm(" ".join(binds)),
    )
    return f"{delete} ;\n{insert}"
