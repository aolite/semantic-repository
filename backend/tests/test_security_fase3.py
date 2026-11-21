"""Seguridad de la fase 3: inyección SPARQL en vocabularios y ontologías.

- El texto libre ``q`` de ``/vocabularies`` no llega a SPARQL.
- Slugs, versiones y conceptos se validan con su patrón: una carga hostil da 422 (o 404)
  y nunca aparece en una consulta.
- Toda consulta que llega al triplestore es una de las plantillas fijas, con sus
  marcadores rellenos solo con términos escapados (IRI, literal o lista de IRIs).
- Los literales hostiles de una ingesta se guardan como datos.
"""

import re
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app import bajas, catalog, vocabularies
from app.models import Role, User
from app.triplestore import MemoryStore
from tests.conftest import user_graphs
from tests.test_security_fase2 import INJECTIONS

_IRI = r'<[^<>"{}|^`\\\x00-\x20]+>'
_LITERAL = r'"(?:[^"\\]|\\.)*"'
_IRI_LIST = rf"{_IRI}(?: {_IRI})*"

TEMPLATES = [
    catalog.CATALOG_QUERY,
    catalog.SERIES_GRAPH_QUERY,
    catalog.THEME_LABELS_QUERY,
    # Decisión 49: catálogo de una serie, catálogos y lápidas.
    catalog.SERIES_CATALOG_QUERY,
    catalog.CATALOGS_QUERY,
    bajas._SUBJECT_QUERY,
    bajas._MEMBERSHIP_QUERY,
    vocabularies.ONTOLOGY_HEADERS_QUERY,
    vocabularies.GRAPH_QUERY,
    vocabularies.SCHEMES_QUERY,
    vocabularies.VOCAB_LABELS_QUERY,
    vocabularies.CONFORMS_TO_QUERY,
    vocabularies.THEME_USAGE_QUERY,
    vocabularies.SUBJECT_USAGE_QUERY,
    "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH $graph { ?s ?p ?o } }",  # triplestore.py
]


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\$[a-z][a-z0-9_]*)", template)
    out = []
    for part in parts:
        if part.startswith("$"):
            out.append(
                f"(?:{_IRI_LIST}|{_LITERAL})" if part == "$values" else f"(?:{_IRI}|{_LITERAL})"
            )
        else:
            out.append(re.escape(part))
    return re.compile("".join(out))


PATTERNS = [_pattern(t) for t in TEMPLATES]


def _assert_only_fixed_queries(store: MemoryStore) -> None:
    assert store.queries, "no se ha consultado nada"
    for query in store.queries:
        assert any(p.fullmatch(query) for p in PATTERNS), f"consulta inesperada:\n{query}"


@pytest.fixture
def api(client: TestClient, vocab_store: MemoryStore, vocab_metrics: None) -> TestClient:
    return client


PUBLIC_READS = [
    "/vocabularies",
    "/vocabularies?kind=own&q=itot",
    "/vocabularies?domain=pqc",
    "/vocabularies?domain=ot&kind=skos_domain",
    "/ontologies/itot/rdf?download=1",
    "/schemes/corp/trl/rdf?download=1",
    "/datasets/modbus-tcp-testbed/rdf?download=1",
    "/ontologies/itot",
    "/ontologies/itot?version=1.0.0",
    "/ontologies/itot/rdf?format=rdfxml",
    "/ontologies/pqcm",
    "/schemes/ot",
    "/schemes/corp/trl",
    "/schemes/ot/concepts/modbus-tcp",
    "/schemes/corp/trl/concepts/trl-1",
    "/schemes/ot/rdf",
    "/onto/itot",
    "/onto/itot/1.1.0",
    "/vocab/ot",
    "/vocab/ot/modbus-tcp",
    "/vocab/corp/trl/trl-1",
    "/datasets",
    "/datasets/modbus-tcp-testbed",
]


def test_every_public_read_uses_only_fixed_queries(
    api: TestClient, vocab_store: MemoryStore
) -> None:
    for path in PUBLIC_READS:
        assert api.get(path, headers={"Accept": "text/turtle"}).status_code == 200, path
    _assert_only_fixed_queries(vocab_store)


@pytest.mark.parametrize("payload", INJECTIONS)
def test_q_never_reaches_sparql(api: TestClient, vocab_store: MemoryStore, payload: str) -> None:
    response = api.get("/vocabularies", params={"q": payload})
    assert response.status_code in (200, 422)
    for query in vocab_store.queries:
        assert payload not in query
    _assert_only_fixed_queries(vocab_store)


@pytest.mark.parametrize("payload", INJECTIONS)
@pytest.mark.parametrize(
    "template",
    [
        "/ontologies/{p}",
        "/ontologies/itot?version={p}",
        "/ontologies/{p}/rdf",
        "/schemes/{p}",
        "/schemes/corp/{p}",
        "/schemes/ot/concepts/{p}",
        "/schemes/corp/trl/concepts/{p}",
        "/onto/{p}",
        "/onto/itot/{p}",
        "/vocab/{p}",
        "/vocab/ot/{p}",
        "/vocab/corp/{p}",
    ],
)
def test_path_payloads_are_rejected(
    api: TestClient, vocab_store: MemoryStore, payload: str, template: str
) -> None:
    before = {name: len(vocab_store.get_graph(name)) for name in vocab_store.graph_names()}
    vocab_store.queries.clear()
    from urllib.parse import quote

    response = api.get(template.replace("{p}", quote(payload, safe="")))
    assert response.status_code in (404, 422)
    for query in vocab_store.queries:
        assert payload not in query
    after = {name: len(vocab_store.get_graph(name)) for name in vocab_store.graph_names()}
    assert after == before


HOSTILE = [
    'Título" } UNION { GRAPH ?g { ?s ?p ?o } } # fin',
    "Línea 1\nLínea 2\r\n} ; DROP ALL ; #",
    'Barra \\ y comillas \\" y llaves {} $graph ${vocab_ns}',
]


@pytest.mark.parametrize("payload", HOSTILE)
def test_hostile_literals_in_scheme_are_stored_as_data(
    client: TestClient,
    store: MemoryStore,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    payload: str,
) -> None:
    make_user("editora", Role.EDITOR)
    escaped = payload.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    escaped = escaped.replace("\r", "\\r")
    body = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
<vocab/corp/hostil> a skos:ConceptScheme ; dct:title "{escaped}"@es ;
    skos:prefLabel "{escaped}"@es ; dct:description "{escaped}"@es ;
    owl:versionInfo "1.0" ; adms:status <http://purl.org/adms/status/Completed> ;
    vann:preferredNamespacePrefix "hostil" ; vann:preferredNamespaceUri <vocab/corp/hostil/> ;
    skos:hasTopConcept <vocab/corp/hostil/c> .
<vocab/corp/hostil/c> a skos:Concept ; skos:inScheme <vocab/corp/hostil> ;
    skos:topConceptOf <vocab/corp/hostil> ; skos:prefLabel "{escaped}"@es .
"""
    response = client.post(
        "/schemes",
        content=body.encode(),
        headers=login("editora") | {"Content-Type": "text/turtle"},
    )
    assert response.status_code == 201, response.text
    assert user_graphs(store) == {response.json()["graph"]}
    store.queries.clear()
    detail = client.get("/schemes/corp/hostil").json()
    assert detail["title"] == payload
    concept = client.get("/schemes/corp/hostil/concepts/c").json()
    assert concept["pref_label"] == payload
    card = client.get("/vocabularies", params={"kind": "skos_corp"}).json()["items"][0]
    assert card["title"] == payload
    _assert_only_fixed_queries(store)
