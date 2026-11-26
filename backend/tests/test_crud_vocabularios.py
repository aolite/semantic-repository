"""Decisión 50: esquemas SKOS y ontologías propias en los catálogos, con CRUD completo.

Contrato: ``semantic/uris.md``, «Vocabularios y ontologías en los catálogos» (reglas 1 a
12 y «Decisiones del 2026-11-25»). Cubre la pertenencia (``dcat:resource`` en el grafo del
catálogo), publicar con ``?catalog=``, editar y mover, dar de baja con lápida y 410 por
arrastre, los 409 (en uso, en otro catálogo, conceptos quitados, slug y prefijo dados de
baja, catálogo no vacío), los temas retirados (regla 11), los sustitutos vivos, los
recursos no gestionables (403), los permisos por rol y lo que hace ``load-semantic``.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli as cli_module
from app import ingest, owl_metrics, vocab_ingest
from app.config import get_settings
from app.models import AuditAction, AuditEvent, OntologyMetricsRecord, Role, User, WithdrawnPrefix
from app.storage import DiskStorage
from app.triplestore import MemoryStore, TriplestoreError
from app.uris import ADMS, DCAT, DCT, PROV, SKOS, Uris
from tests import fase4_data
from tests.conftest import BASE_URI, FIXTURE_DATA_DIR, FIXTURE_SEMANTIC_DIR, TEST_CATALOG_URI

VOCAB_CATALOG = f"{BASE_URI}catalogo/vocabularios-sinteticos"
BAJAS = f"{BASE_URI}bajas"
OT = f"{BASE_URI}vocab/ot"
TRL = f"{BASE_URI}vocab/corp/trl"
PQC = f"{BASE_URI}vocab/pqc"
DIDX = f"{BASE_URI}onto/didx"
ITOT = f"{BASE_URI}onto/itot"
WITHDRAWN = URIRef("http://purl.org/adms/status/Withdrawn")
TTL = {"Content-Type": "text/turtle"}
TURTLE = {"Accept": "text/turtle"}
SCHEME_OT = (FIXTURE_SEMANTIC_DIR / "vocabularios" / "ot.ttl").read_bytes()
SCHEME_TRL = (FIXTURE_SEMANTIC_DIR / "vocabularios" / "corp" / "trl.ttl").read_bytes()
SCHEME_PQC = (FIXTURE_SEMANTIC_DIR / "vocabularios" / "pqc.ttl").read_bytes()
STATUS = "<http://purl.org/adms/status/Completed>"


@pytest.fixture
def api(client: TestClient, vocab_store: MemoryStore) -> TestClient:
    return client


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("editora", Role.EDITOR)
    return login("editora")


@pytest.fixture
def admin(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("admina", Role.ADMIN)
    return login("admina")


@pytest.fixture
def member(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("miembro", Role.MIEMBRO)
    return login("miembro")


@pytest.fixture(autouse=True)
def fake_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Métricas sin Pellet: estas pruebas no comprueban la consistencia."""

    def fake(prepared: vocab_ingest.PreparedOntology, _settings: object):
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri)
        return metrics.to_dict(), owl_metrics.Consistency(detail="prueba").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake)


def _events(session_factory: sessionmaker[Session], action: AuditAction) -> list[AuditEvent]:
    with session_factory() as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.action == action.value)))


def _members(store: MemoryStore, catalog_uri: str) -> set[str]:
    graph = store.get_graph(catalog_uri)
    return {str(r) for r in graph.objects(URIRef(catalog_uri), DCAT.resource)}


def _scheme(
    uri: str = "vocab/nuevo", prefix: str = "nuevo", body: str = "", concepts: str = "a"
) -> bytes:
    """Esquema de dominio mínimo que cumple las formas (sin el triple de pertenencia)."""
    names = concepts.split()
    top = " , ".join(f"<{uri}/{name}>" for name in names)
    items = "".join(
        f"""<{uri}/{name}> a skos:Concept ; skos:inScheme <{uri}> ;
    skos:topConceptOf <{uri}> ; skos:prefLabel "Concepto {name}"@es .
"""
        for name in names
    )
    return f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<{uri}> a skos:ConceptScheme ; dct:title "Esquema nuevo"@es ;
    skos:prefLabel "Esquema nuevo"@es ; dct:description "Esquema de prueba"@es ;
    dct:subject <vocab/dominio/ot> ; owl:versionInfo "1.0" ; adms:status {STATUS} ;
    vann:preferredNamespacePrefix "{prefix}" ; vann:preferredNamespaceUri <{uri}/> ;
    skos:hasTopConcept {top} .
{items}{body}
""".encode()


def _onto(slug: str = "nueva", version: str = "1.0.0", prefix: str = "nueva", body: str = ""):
    return f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
@prefix : <onto/{slug}#> .
<onto/{slug}> a owl:Ontology ; owl:versionIRI <onto/{slug}/{version}> ;
    owl:versionInfo "{version}" ; adms:status {STATUS} ;
    dct:title "Ontología {slug}"@es ; dct:description "Ontología de prueba"@es ;
    vann:preferredNamespacePrefix "{prefix}" ; vann:preferredNamespaceUri <onto/{slug}#> .
:A a owl:Class .
{body}
""".encode()


def _with_deprecated(source: bytes, concept: str, replaced_by: list[str]) -> bytes:
    """El esquema con ``concept`` retirado (``owl:deprecated true``) y sus sustitutos."""
    graph = Graph().parse(data=source.decode(), format="turtle", publicID=BASE_URI)
    graph.add((URIRef(concept), OWL.deprecated, Literal(True)))
    for target in replaced_by:
        graph.add((URIRef(concept), DCT.isReplacedBy, URIRef(target)))
    return graph.serialize(format="turtle").encode()


def _without_concept(source: bytes, concept: str) -> bytes:
    graph = Graph().parse(data=source.decode(), format="turtle", publicID=BASE_URI)
    node = URIRef(concept)
    graph.remove((node, None, None))
    graph.remove((None, None, node))
    return graph.serialize(format="turtle").encode()


def _post(api: TestClient, path: str, body: bytes, headers: dict[str, str], catalog: str | None):
    url = path if catalog is None else f"{path}?catalog={catalog}"
    return api.post(url, content=body, headers=headers | TTL)


# --- Modelo: pertenencia y lectura -------------------------------------------------------


def test_synthetic_schemes_and_ontologies_belong_to_their_catalog(
    api: TestClient, vocab_store: MemoryStore
) -> None:
    members = _members(vocab_store, VOCAB_CATALOG)
    assert len(members) == 12 and {OT, TRL, ITOT, DIDX} <= members
    # La pertenencia vive solo en el grafo del catálogo.
    assert not list(vocab_store.get_graph(OT).triples((None, DCAT.resource, None)))
    page = {c["slug"]: c for c in api.get("/catalogs").json()["items"]}
    assert page["vocabularios-sinteticos"]["scheme_count"] == 9
    assert page["vocabularios-sinteticos"]["ontology_count"] == 3
    assert page["vocabularios-sinteticos"]["dataset_count"] == 0
    assert page["sintetico"]["scheme_count"] == 0
    detail = api.get("/catalogs/vocabularios-sinteticos").json()
    assert {s["uri"] for s in detail["schemes"]} == {m for m in members if "/vocab/" in m}
    trl = next(s for s in detail["schemes"] if s["uri"] == TRL)
    assert trl == {
        "slug": "trl",
        "corp": True,
        "uri": TRL,
        "title": "Niveles de madurez tecnológica (TRL)",
    }
    itot = next(o for o in detail["ontologies"] if o["uri"] == ITOT)
    assert itot["title"] == "Ontología de activos y amenazas IT/OT"  # la de la versión actual
    ref = {
        "slug": "vocabularios-sinteticos",
        "uri": VOCAB_CATALOG,
        "title": "Vocabularios y ontologías sintéticos de demostración",
    }
    assert api.get("/schemes/corp/trl").json()["catalog"] == ref
    assert api.get("/ontologies/itot").json()["catalog"] == ref
    assert api.get("/schemes/dominio").json()["catalog"] is None  # auxiliar: en ninguno
    only = api.get("/vocabularies", params={"catalog": "vocabularios-sinteticos"}).json()
    assert {c["kind"] for c in only["items"]} == {"own", "skos_corp", "skos_domain"}
    assert only["total"] == 12
    assert api.get("/vocabularies", params={"catalog": "sintetico"}).json()["total"] == 0


def test_semantico_valid_examples_pass_the_backend_ingest(settings) -> None:
    """Los ejemplos válidos de semantico con su triple de pertenencia (decisión 50)."""
    uris = Uris(BASE_URI)
    examples = Path(__file__).resolve().parents[2] / "semantic" / "examples" / "valid"
    if not examples.is_dir():
        pytest.skip("sin semantic/ en este entorno")
    for name in ("esquema-en-catalogo", "esquema-corporativo-en-catalogo"):
        graph = ingest.parse_file(examples / f"{name}.ttl", BASE_URI)
        prepared = vocab_ingest.prepare_scheme(graph, uris, settings)
        assert prepared.catalog_uri == f"{BASE_URI}catalogo/prueba", name
        assert not list(prepared.graph.triples((None, DCAT.resource, None)))
    graph = ingest.parse_file(examples / "ontologia-en-catalogo.ttl", BASE_URI)
    prepared_onto = vocab_ingest.prepare_ontology(graph, uris, settings)
    assert prepared_onto.catalog_uri == f"{BASE_URI}catalogo/prueba"
    assert not list(prepared_onto.graph.triples((None, DCAT.resource, None)))


# --- Publicar ---------------------------------------------------------------------------


def test_publish_scheme_in_a_catalog(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = _post(api, "/schemes", _scheme(), editor, "pruebas")
    assert response.status_code == 201, response.text
    uri = f"{BASE_URI}vocab/nuevo"
    assert response.json()["catalog"] == TEST_CATALOG_URI
    assert uri in _members(vocab_store, TEST_CATALOG_URI)
    assert not list(vocab_store.get_graph(uri).triples((None, DCAT.resource, None)))
    assert api.get("/schemes/nuevo").json()["catalog"]["slug"] == "pruebas"
    [event] = _events(session_factory, AuditAction.SCHEME_PUBLISHED)
    assert event.details["catalog"] == TEST_CATALOG_URI
    # Republicar en el mismo catálogo (con el triple en el RDF, sin parámetro).
    body = _scheme(body=f"<catalogo/pruebas> <{DCAT.resource}> <vocab/nuevo> .")
    again = _post(api, "/schemes", body, editor, None)
    assert again.status_code == 200, again.text
    assert again.json()["changed"] is False


def test_publish_ontology_version_in_a_catalog(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = _post(api, "/ontologies", _onto(), editor, "pruebas")
    assert response.status_code == 201, response.text
    uri = f"{BASE_URI}onto/nueva"
    assert response.json()["catalog"] == TEST_CATALOG_URI
    assert uri in _members(vocab_store, TEST_CATALOG_URI)
    # El triple no va en la versión (inmutable): va en el grafo del catálogo.
    version = vocab_store.get_graph(f"{uri}/1.0.0")
    assert not list(version.triples((None, DCAT.resource, None)))
    [event] = _events(session_factory, AuditAction.ONTOLOGY_PUBLISHED)
    assert event.details["catalog"] == TEST_CATALOG_URI
    # Versión nueva en el mismo catálogo.
    newer = _onto(version="1.1.0", body="<onto/nueva> owl:priorVersion <onto/nueva/1.0.0> .")
    assert _post(api, "/ontologies", newer, editor, "pruebas").status_code == 201


@pytest.mark.parametrize(
    ("path", "body"),
    [("/schemes", _scheme()), ("/ontologies", _onto())],
)
def test_publish_without_catalog_is_rejected_by_shacl(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str], path: str, body: bytes
) -> None:
    response = _post(api, path, body, editor, None)
    assert response.status_code == 422
    assert response.json()["kind"] == "shacl"
    assert any("dcat:Catalog" in i["message"] for i in response.json()["issues"])


@pytest.mark.parametrize(
    ("path", "body"),
    [("/schemes", SCHEME_TRL), ("/ontologies", _onto("didx", version="2.0.0", prefix="didx"))],
)
def test_publish_in_another_catalog_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str], path: str, body: bytes
) -> None:
    """Regla 3: mover es explícito (PATCH)."""
    response = _post(api, path, body, editor, "pruebas")
    assert response.status_code == 409, response.text
    assert response.json()["kind"] == "catalog_conflict"
    assert response.json()["issues"][0]["focus_node"] == VOCAB_CATALOG


def test_publish_with_unknown_or_conflicting_catalog(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    missing = _post(api, "/schemes", _scheme(), editor, "no-existe")
    assert missing.status_code == 422
    assert missing.json()["kind"] == "catalog"
    body = _scheme(body=f"<catalogo/sintetico> <{DCAT.resource}> <vocab/nuevo> .")
    other = _post(api, "/schemes", body, editor, "pruebas")
    assert other.status_code == 422
    assert other.json()["kind"] == "catalog"
    root = _scheme(body=f"<catalogo> <{DCAT.resource}> <vocab/nuevo> .")
    assert _post(api, "/schemes", root, editor, None).json()["kind"] == "uri"  # raíz: no
    assert f"{BASE_URI}vocab/nuevo" not in vocab_store.graph_names()


# --- Republicar un esquema: conceptos, retirada y sustitutos (regla 9) ------------------


def test_republish_scheme_without_a_concept_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    concept = f"{OT}/modbus-tcp"
    body = _without_concept(SCHEME_OT, concept)
    response = _post(api, "/schemes", body, editor, "vocabularios-sinteticos")
    assert response.status_code == 409, response.text
    assert response.json()["kind"] == "concepts_removed"
    assert [i["focus_node"] for i in response.json()["issues"]] == [concept]
    assert (URIRef(concept), RDF.type, SKOS.Concept) in vocab_store.get_graph(OT)


def test_retire_a_concept_with_replacements_and_no_reactivation(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    concept, dnp3 = f"{OT}/modbus-tcp", f"{OT}/dnp3"
    retired = _with_deprecated(SCHEME_OT, concept, [dnp3, f"{BASE_URI}vocab/it/cwe"])
    response = _post(api, "/schemes", retired, editor, "vocabularios-sinteticos")
    assert response.status_code == 200, response.text
    detail = api.get("/schemes/ot/concepts/modbus-tcp").json()
    assert detail["deprecated"] is True
    assert {r["uri"] for r in detail["replaced_by"]} == {dnp3, f"{BASE_URI}vocab/it/cwe"}
    tree = api.get("/schemes/ot").json()["tree"]
    flat = []
    stack = list(tree)
    while stack:
        node = stack.pop()
        flat.append(node)
        stack.extend(node["children"])
    assert next(n for n in flat if n["uri"] == concept)["deprecated"] is True
    # Reactivarlo queda fuera del piloto: 409 (validado el 2026-11-26).
    again = _post(api, "/schemes", SCHEME_OT, editor, "vocabularios-sinteticos")
    assert again.status_code == 409
    assert again.json()["kind"] == "concept_reactivated"


def test_replacement_must_be_a_live_concept(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    concept = f"{OT}/modbus-tcp"
    for target in (f"{OT}/no-existe", f"{BASE_URI}vocab/otro/x", "https://otro.example/c"):
        body = _with_deprecated(SCHEME_OT, concept, [target])
        response = _post(api, "/schemes", body, editor, "vocabularios-sinteticos")
        assert response.status_code == 422, (target, response.text)
        assert response.json()["kind"] == "replacement"
        assert response.json()["issues"][0]["value"] == target
    # Un concepto de un esquema dado de baja ya no está vivo.
    assert api.delete("/schemes/pqc", headers=editor).status_code == 204
    pqc_concept = next(
        str(c)
        for c in Graph()
        .parse(data=SCHEME_PQC.decode(), format="turtle", publicID=BASE_URI)
        .subjects(SKOS.inScheme, URIRef(PQC))
    )
    body = _with_deprecated(SCHEME_OT, concept, [pqc_concept])
    assert _post(api, "/schemes", body, editor, "vocabularios-sinteticos").status_code == 422


# --- Temas retirados en versiones nuevas de dataset (regla 11) ---------------------------


def test_new_dataset_version_with_a_retired_theme_is_rejected(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
) -> None:
    concept, dnp3 = f"{OT}/modbus-tcp", f"{OT}/dnp3"
    retired = _with_deprecated(SCHEME_OT, concept, [dnp3])
    assert _post(api, "/schemes", retired, editor, "vocabularios-sinteticos").status_code == 200
    version = fase4_data.V1.replace(
        'dcat:version "1.0.0" ;', f'dcat:version "1.0.0" ; dcat:theme <{concept}> ;'
    )
    response = fase4_data.publish(api, editor, fase4_data.series(version))
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["kind"] == "deprecated_theme"
    [issue] = body["issues"]
    assert issue["value"] == concept
    assert issue["focus_node"] == f"{BASE_URI}dataset/prueba/1.0.0"
    assert issue["replaced_by"] == [dnp3]
    assert f"{BASE_URI}dataset/prueba" not in vocab_store.graph_names()
    # Las versiones ya publicadas no cambian: la serie Modbus (que usa el tema) se puede
    # volver a publicar tal cual.
    modbus = (FIXTURE_DATA_DIR / "sintetico" / "modbus-tcp-testbed.ttl").read_bytes()
    again = api.post("/datasets", content=modbus, headers=editor | TTL)
    assert again.status_code == 200, again.text
    # Con el sustituto, sí.
    fixed = version.replace(concept, dnp3)
    assert fase4_data.publish(api, editor, fase4_data.series(fixed)).status_code == 201


# --- Editar y mover ---------------------------------------------------------------------


def test_update_scheme_metadata_and_move_it(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = api.patch(
        "/schemes/corp/trl",
        json={"title": "TRL editado", "description": "Nueva", "catalog": "pruebas"},
        headers=editor,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "TRL editado"
    assert body["description"] == "Nueva"
    assert body["catalog"]["slug"] == "pruebas"
    graph = vocab_store.get_graph(TRL)
    assert set(graph.objects(URIRef(TRL), SKOS.prefLabel)) == {Literal("TRL editado", lang="es")}
    assert body["concept_count"] == 9  # los conceptos no cambian
    assert TRL in _members(vocab_store, TEST_CATALOG_URI)
    assert TRL not in _members(vocab_store, VOCAB_CATALOG)
    [event] = _events(session_factory, AuditAction.SCHEME_UPDATED)
    assert event.details["moved_from"] == [VOCAB_CATALOG]
    assert event.actor_username == "editora"
    # Solo un campo: el catálogo se conserva.
    only = api.patch("/schemes/corp/trl", json={"description": "Otra"}, headers=editor)
    assert only.status_code == 200 and only.json()["catalog"]["slug"] == "pruebas"
    bad = api.patch("/schemes/corp/trl", json={"catalog": "no-existe"}, headers=editor)
    assert bad.status_code == 422 and bad.json()["kind"] == "catalog"
    extra = api.patch("/schemes/corp/trl", json={"slug": "otro"}, headers=editor)
    assert extra.status_code == 422
    assert api.patch("/schemes/no-existe", json={"title": "x"}, headers=editor).status_code == 404


def test_move_ontology_between_catalogs(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    before = {
        v: len(vocab_store.get_graph(v))
        for v in vocab_store.graph_names()
        if v.startswith(f"{ITOT}/")
    }
    response = api.patch("/ontologies/itot", json={"catalog": "pruebas"}, headers=editor)
    assert response.status_code == 200, response.text
    assert response.json()["catalog"]["slug"] == "pruebas"
    assert ITOT in _members(vocab_store, TEST_CATALOG_URI)
    assert ITOT not in _members(vocab_store, VOCAB_CATALOG)
    # Ninguna versión cambia (decisión 28).
    assert {v: len(vocab_store.get_graph(v)) for v in before} == before
    [event] = _events(session_factory, AuditAction.ONTOLOGY_UPDATED)
    assert event.details["moved_from"] == [VOCAB_CATALOG]
    # Solo se edita el catálogo: los metadatos están en las versiones.
    assert api.patch("/ontologies/itot", json={"title": "x"}, headers=editor).status_code == 422
    assert api.patch("/ontologies/itot", json={}, headers=editor).status_code == 422
    assert (
        api.patch("/ontologies/no-existe", json={"catalog": "pruebas"}, headers=editor).status_code
        == 404
    )


# --- Bajas ------------------------------------------------------------------------------


def test_withdraw_scheme_tombstone_410_and_no_reuse(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    assert api.delete("/schemes/corp/trl", headers=editor).status_code == 204
    tomb = vocab_store.get_graph(BAJAS)
    node = URIRef(TRL)
    assert set(tomb.objects(node, RDF.type)) == {PROV.Entity}
    assert (node, ADMS.status, WITHDRAWN) in tomb
    assert str(tomb.value(node, DCT.title)) == "Niveles de madurez tecnológica (TRL)"
    assert TRL not in vocab_store.graph_names()
    assert TRL not in _members(vocab_store, VOCAB_CATALOG)
    # 410 en la API y en la URI persistente, también para sus conceptos (por el prefijo).
    gone = api.get("/schemes/corp/trl")
    assert gone.status_code == 410
    assert gone.json() == {
        "detail": "Recurso dado de baja",
        "uri": TRL,
        "resource": "scheme",
        "title": "Niveles de madurez tecnológica (TRL)",
        "withdrawn_at": gone.json()["withdrawn_at"],
    }
    assert api.get("/schemes/corp/trl/concepts/trl-1").status_code == 410
    assert api.get("/schemes/corp/trl/rdf").status_code == 410
    html = api.get("/vocab/corp/trl/trl-1", follow_redirects=False)
    assert html.status_code == 410 and "Esquema SKOS" in html.text
    rdf = api.get("/vocab/corp/trl", headers=TURTLE, follow_redirects=False)
    assert rdf.status_code == 410
    assert (node, ADMS.status, WITHDRAWN) in Graph().parse(data=rdf.text, format="turtle")
    # Sale de los listados, de la ficha del catálogo y de SPARQL.
    assert TRL not in {c["uri"] for c in api.get("/vocabularies").json()["items"]}
    assert TRL not in {
        s["uri"] for s in api.get("/catalogs/vocabularios-sinteticos").json()["schemes"]
    }
    query = f"SELECT ?s WHERE {{ GRAPH ?g {{ ?s ?p ?o }} FILTER(STRSTARTS(STR(?s), '{TRL}')) }}"
    assert api.get("/sparql", params={"query": query}).json()["results"]["bindings"] == []
    # Auditoría y prefijo conservado aparte (la lápida no lo guarda).
    [event] = _events(session_factory, AuditAction.SCHEME_WITHDRAWN)
    assert event.actor_username == "editora"
    assert event.details["catalogs"] == [VOCAB_CATALOG]
    assert event.details["prefix"] == "ectrl"
    with session_factory() as session:
        assert session.get(WithdrawnPrefix, "ectrl").resource_uri == TRL
    # El slug y el prefijo no se reutilizan (regla 7).
    reuse = _post(api, "/schemes", SCHEME_TRL, editor, "pruebas")
    assert reuse.status_code == 409 and reuse.json()["kind"] == "withdrawn"
    prefix = _post(api, "/schemes", _scheme(prefix="ectrl"), editor, "pruebas")
    assert prefix.status_code == 409 and prefix.json()["kind"] == "prefix_withdrawn"
    onto_prefix = _post(api, "/ontologies", _onto(prefix="ectrl"), editor, "pruebas")
    assert onto_prefix.status_code == 409 and onto_prefix.json()["kind"] == "prefix_withdrawn"
    # vocab/corp/trl y vocab/trl son URIs distintas.
    assert (
        _post(api, "/schemes", _scheme("vocab/trl", "trl2"), editor, "pruebas").status_code == 201
    )
    # Volver a darlo de baja: 410.
    assert api.delete("/schemes/corp/trl", headers=editor).status_code == 410
    assert api.patch("/schemes/corp/trl", json={"title": "x"}, headers=editor).status_code == 410


def test_withdraw_ontology_removes_every_version_and_410_by_prefix(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(
            OntologyMetricsRecord(
                version_iri=f"{DIDX}/1.0.0",
                ontology_iri=DIDX,
                content_hash="0" * 64,
                metrics={},
                consistency={},
                tool="pruebas",
            )
        )
        session.commit()
    assert api.delete("/ontologies/didx", headers=editor).status_code == 204
    assert not [g for g in vocab_store.graph_names() if g.startswith(f"{DIDX}/")]
    assert DIDX not in _members(vocab_store, VOCAB_CATALOG)
    assert (URIRef(DIDX), PROV.invalidatedAtTime, None) in vocab_store.get_graph(BAJAS)
    for path in ("/ontologies/didx", "/ontologies/didx?version=1.0.0", "/ontologies/didx/rdf"):
        response = api.get(path)
        assert response.status_code == 410, path
        assert response.json()["resource"] == "ontology"
    assert api.get("/onto/didx/1.0.0", headers=TURTLE).status_code == 410
    assert api.get("/onto/didx", follow_redirects=False).status_code == 410
    assert "didx" not in {c["slug"] for c in api.get("/vocabularies").json()["items"]}
    with session_factory() as session:
        assert session.get(OntologyMetricsRecord, f"{DIDX}/1.0.0") is None
        assert session.get(WithdrawnPrefix, "didx").resource_uri == DIDX
    [event] = _events(session_factory, AuditAction.ONTOLOGY_WITHDRAWN)
    assert event.details["versions"] == ["1.0.0"]
    reuse = _post(api, "/ontologies", _onto("didx", prefix="otro"), editor, "pruebas")
    assert reuse.status_code == 409 and reuse.json()["kind"] == "withdrawn"


def test_withdraw_scheme_in_use_is_409_with_its_uses(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """Regla 8: vocab/ot es tema de la serie Modbus y dct:subject de itot."""
    response = api.delete("/schemes/ot", headers=editor)
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["kind"] == "in_use"
    uses = {(u["resource"], u["uri"], u["via"], u["target"]) for u in body["used_by"]}
    assert (
        "dataset",
        f"{BASE_URI}dataset/modbus-tcp-testbed/2.1.0",
        str(DCAT.theme),
        f"{OT}/modbus-tcp",
    ) in uses
    assert ("ontology", f"{ITOT}/1.2.0", str(DCT.subject), f"{OT}/modbus-tcp") in uses
    assert OT in vocab_store.graph_names()
    assert (URIRef(OT), PROV.invalidatedAtTime, None) not in vocab_store.get_graph(BAJAS)


def test_withdraw_scheme_used_by_a_mapping_from_another_scheme(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    mapping = f"<vocab/nuevo/a> <{SKOS.exactMatch}> <vocab/corp/trl/trl-1> ."
    assert _post(api, "/schemes", _scheme(body=mapping), editor, "pruebas").status_code == 201
    response = api.delete("/schemes/corp/trl", headers=editor)
    assert response.status_code == 409
    assert response.json()["used_by"] == [
        {
            "uri": f"{BASE_URI}vocab/nuevo/a",
            "resource": "scheme",
            "via": str(SKOS.exactMatch),
            "target": f"{TRL}/trl-1",
        }
    ]
    # Al dar de baja el que lo usa, ya se puede.
    assert api.delete("/schemes/nuevo", headers=editor).status_code == 204
    assert api.delete("/schemes/corp/trl", headers=editor).status_code == 204


def test_withdraw_ontology_in_use_by_imports_or_terms(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    imports = _onto("importa", prefix="importa", body="<onto/importa> owl:imports <onto/didx> .")
    assert _post(api, "/ontologies", imports, editor, "pruebas").status_code == 201
    response = api.delete("/ontologies/didx", headers=editor)
    assert response.status_code == 409
    assert response.json()["used_by"] == [
        {
            "uri": f"{BASE_URI}onto/importa/1.0.0",
            "resource": "ontology",
            "via": str(OWL.imports),
            "target": DIDX,
        }
    ]
    assert api.delete("/ontologies/importa", headers=editor).status_code == 204
    terms = _onto("usa", prefix="usa", body="<onto/usa#B> rdfs:subClassOf <onto/didx#Algo> .")
    terms = terms.replace(
        b"@prefix owl:", b"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n@prefix owl:"
    )
    assert _post(api, "/ontologies", terms, editor, "pruebas").status_code == 201
    used = api.delete("/ontologies/didx", headers=editor)
    assert used.status_code == 409
    assert used.json()["used_by"][0]["via"] is None
    assert used.json()["used_by"][0]["target"] == f"{DIDX}#Algo"


def test_withdraw_catalog_with_schemes_or_ontologies_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """Regla 10."""
    response = api.delete("/catalogs/vocabularios-sinteticos", headers=editor)
    assert response.status_code == 409
    body = response.json()
    assert body["kind"] == "catalog_not_empty"
    assert body["datasets"] == []
    assert len(body["resources"]) == 12 and ITOT in body["resources"]
    assert _post(api, "/schemes", _scheme(), editor, "pruebas").status_code == 201
    response = api.delete("/catalogs/pruebas", headers=editor)
    assert response.json()["resources"] == [f"{BASE_URI}vocab/nuevo"]


# --- No gestionables (reglas 5 y 12): 403 not_managed -------------------------------------


def test_auxiliary_schemes_and_external_ontologies_are_not_managed(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str], admin: dict[str, str]
) -> None:
    aux = _scheme("vocab/dominio", "dom")
    external = b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://saref.etsi.org/core/> a owl:Ontology ; owl:versionIRI <https://saref.etsi.org/core/v9> ."""
    for headers in (editor, admin):
        calls = [
            _post(api, "/schemes", aux, headers, "pruebas"),
            _post(api, "/ontologies", external, headers, "pruebas"),
            api.patch("/schemes/dominio", json={"catalog": "pruebas"}, headers=headers),
            api.patch("/schemes/tipo-dataset", json={"title": "x"}, headers=headers),
            api.delete("/schemes/dominio", headers=headers),
            api.delete("/schemes/tipo-dataset", headers=headers),
            api.patch("/ontologies/externas", json={"catalog": "pruebas"}, headers=headers),
            api.delete("/ontologies/externas", headers=headers),
        ]
        for response in calls:
            assert response.status_code == 403, response.request.url
            assert response.json()["kind"] == "not_managed"
    assert f"{BASE_URI}vocab/dominio" not in _members(vocab_store, TEST_CATALOG_URI)
    assert (URIRef(f"{BASE_URI}vocab/dominio"), PROV.invalidatedAtTime, None) not in (
        vocab_store.get_graph(BAJAS)
    )


# --- Permisos por rol --------------------------------------------------------------------


WRITES = [
    ("patch", "/schemes/corp/trl", {"title": "x"}),
    ("delete", "/schemes/corp/trl", None),
    ("patch", "/schemes/pqc", {"title": "x"}),
    ("delete", "/schemes/pqc", None),
    ("patch", "/ontologies/didx", {"catalog": "pruebas"}),
    ("delete", "/ontologies/didx", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_roles_for_scheme_and_ontology_writes(
    api: TestClient,
    vocab_store: MemoryStore,
    member: dict[str, str],
    admin: dict[str, str],
    method: str,
    path: str,
    body: dict | None,
) -> None:
    kwargs = {"json": body} if body is not None else {}
    anonymous = getattr(api, method)(path, **kwargs)
    assert anonymous.status_code == 401
    forbidden = getattr(api, method)(path, headers=member, **kwargs)
    assert forbidden.status_code == 403
    assert forbidden.json().get("kind") is None  # rol insuficiente, no «no gestionable»
    allowed = getattr(api, method)(path, headers=admin, **kwargs)  # admin hereda de editor
    assert allowed.status_code in (200, 204), allowed.text


def test_member_cannot_publish_in_a_catalog(
    api: TestClient, vocab_store: MemoryStore, member: dict[str, str]
) -> None:
    assert _post(api, "/schemes", _scheme(), member, "pruebas").status_code == 403
    assert _post(api, "/ontologies", _onto(), member, "pruebas").status_code == 403
    assert f"{BASE_URI}vocab/nuevo" not in _members(vocab_store, TEST_CATALOG_URI)


# --- load-semantic -----------------------------------------------------------------------


@pytest.fixture
def cli_doubles(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    vocab_store: MemoryStore,
    file_storage: DiskStorage,
) -> CliRunner:
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: vocab_store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)
    get_settings.cache_clear()
    ingest.clear_caches()
    return CliRunner()


def test_load_semantic_keeps_what_the_application_did(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    cli_doubles: CliRunner,
) -> None:
    """La aplicación manda: bajas, traslados y conceptos añadidos (decisión 50)."""
    assert api.delete("/schemes/corp/trl", headers=editor).status_code == 204
    assert api.delete("/ontologies/didx", headers=editor).status_code == 204
    assert api.patch("/schemes/pqc", json={"catalog": "pruebas"}, headers=editor).status_code == 200
    assert (
        api.patch("/ontologies/pqcm", json={"catalog": "pruebas"}, headers=editor).status_code
        == 200
    )
    # Concepto nuevo en vocab/ot desde la aplicación, y otro retirado.
    graph = Graph().parse(data=SCHEME_OT.decode(), format="turtle", publicID=BASE_URI)
    added = URIRef(f"{OT}/nuevo-desde-app")
    graph.add((added, RDF.type, SKOS.Concept))
    graph.add((added, SKOS.inScheme, URIRef(OT)))
    graph.add((added, SKOS.topConceptOf, URIRef(OT)))
    graph.add((URIRef(OT), SKOS.hasTopConcept, added))
    graph.add((added, SKOS.prefLabel, Literal("Desde la aplicación", lang="es")))
    graph.add((URIRef(f"{OT}/dnp3"), OWL.deprecated, Literal(True)))
    body = graph.serialize(format="turtle").encode()
    assert _post(api, "/schemes", body, editor, "vocabularios-sinteticos").status_code == 200

    result = cli_doubles.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert "vocabularios/corp/trl.ttl: se omite (esquema dado de baja)" in result.output
    assert "ontologias/didx/1.0.0.ttl: se omite (ontología dada de baja)" in result.output
    assert TRL not in vocab_store.graph_names()
    assert not [g for g in vocab_store.graph_names() if g.startswith(f"{DIDX}/")]
    # Los traslados no se deshacen.
    assert {PQC, f"{BASE_URI}onto/pqcm"} <= _members(vocab_store, TEST_CATALOG_URI)
    assert not {PQC, f"{BASE_URI}onto/pqcm", TRL, DIDX} & _members(vocab_store, VOCAB_CATALOG)
    # El concepto añadido sigue, y el retirado sigue retirado ([PROPUESTA]).
    ot = vocab_store.get_graph(OT)
    assert (added, SKOS.prefLabel, Literal("Desde la aplicación", lang="es")) in ot
    assert (URIRef(OT), SKOS.hasTopConcept, added) in ot
    assert vocab_ingest.is_deprecated(ot, URIRef(f"{OT}/dnp3"))
    assert not list(ot.triples((None, DCAT.resource, None)))


def test_load_semantic_puts_a_new_resource_in_its_file_catalog(
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    file_storage: DiskStorage,
) -> None:
    """Un triplestore vacío: cada recurso va al catálogo que le da data/catalogos/."""
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)
    get_settings.cache_clear()
    ingest.clear_caches()
    result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert len(_members(store, VOCAB_CATALOG)) == 12


def test_load_semantic_rejects_a_withdrawn_prefix(
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    file_storage: DiskStorage,
) -> None:
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)
    get_settings.cache_clear()
    ingest.clear_caches()
    with session_factory() as session:
        session.add(WithdrawnPrefix(prefix="ectrl", resource_uri=f"{BASE_URI}vocab/corp/viejo"))
        session.commit()
    result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 1
    assert "ectrl" in result.output
    assert TRL not in store.graph_names()  # no se carga nada


@pytest.mark.parametrize(
    ("relative", "append", "message"),
    [
        (
            "data/catalogo.ttl",
            f"\n<catalogo> <{DCAT.resource}> <vocab/ot> .\n",
            "El catálogo raíz no lista esquemas ni ontologías",
        ),
        (
            "vocabularios/zz-sin-catalogo.ttl",
            _scheme("vocab/zz-sin-catalogo", "zz").decode(),
            "no está en ningún catálogo de data/catalogos/",
        ),
    ],
)
def test_load_semantic_rejects_resources_outside_a_catalog(
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    file_storage: DiskStorage,
    semantic_dir: Path,
    tmp_path: Path,
    relative: str,
    append: str,
    message: str,
) -> None:
    import shutil

    copy = tmp_path / "semantic"
    shutil.copytree(semantic_dir, copy)
    target = copy / relative
    target.write_text(
        (target.read_text(encoding="utf-8") if target.exists() else "") + append, encoding="utf-8"
    )
    monkeypatch.setenv("SEMANTIC_DIR", str(copy))
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)
    get_settings.cache_clear()
    ingest.clear_caches()
    try:
        result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        ingest.clear_caches()
    assert result.exit_code == 1, result.output
    assert message in result.output
    assert OT not in store.graph_names()


# --- Segunda ronda de la PR #46 (validado el 2026-11-26) ---------------------------------


def test_withdraw_scheme_used_as_subject_of_an_ontology_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """dct:subject de una ontología viva hacia el esquema mismo (no a un concepto)."""
    onto = _onto("tema", prefix="tema", body=f"<onto/tema> dct:subject <{TRL}> .")
    assert _post(api, "/ontologies", onto, editor, "pruebas").status_code == 201
    response = api.delete("/schemes/corp/trl", headers=editor)
    assert response.status_code == 409, response.text
    assert response.json()["used_by"] == [
        {
            "uri": f"{BASE_URI}onto/tema/1.0.0",
            "resource": "ontology",
            "via": str(DCT.subject),
            "target": TRL,
        }
    ]
    assert api.delete("/ontologies/tema", headers=editor).status_code == 204
    assert api.delete("/schemes/corp/trl", headers=editor).status_code == 204


def test_withdraw_scheme_used_as_replacement_from_another_scheme_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """QA-50-02: un concepto de otro esquema vivo retirado con dct:isReplacedBy hacia él."""
    concept, target = f"{OT}/modbus-tcp", f"{TRL}/trl-1"
    retired = _with_deprecated(SCHEME_OT, concept, [target])
    assert _post(api, "/schemes", retired, editor, "vocabularios-sinteticos").status_code == 200
    response = api.delete("/schemes/corp/trl", headers=editor)
    assert response.status_code == 409, response.text
    assert {
        "uri": concept,
        "resource": "scheme",
        "via": str(DCT.isReplacedBy),
        "target": target,
    } in response.json()["used_by"]
    assert TRL in vocab_store.graph_names()
    # El esquema que lo usa se puede seguir republicando igual.
    assert _post(api, "/schemes", retired, editor, "vocabularios-sinteticos").status_code == 200


def test_withdraw_ontology_conformed_to_by_a_dataset_version_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """dct:conformsTo de una versión de dataset viva hacia la ontología o una versión."""
    response = api.delete("/ontologies/itot", headers=editor)
    assert response.status_code == 409, response.text
    assert {
        "uri": f"{BASE_URI}dataset/modbus-tcp-testbed/2.1.0",
        "resource": "dataset",
        "via": str(DCT.conformsTo),
        "target": f"{ITOT}/1.2.0",
    } in response.json()["used_by"]
    version = fase4_data.V1.replace(
        'dcat:version "1.0.0" ;', f'dcat:version "1.0.0" ; dct:conformsTo <{DIDX}> ;'
    )
    assert fase4_data.publish(api, editor, fase4_data.series(version)).status_code == 201
    used = api.delete("/ontologies/didx", headers=editor)
    assert used.status_code == 409
    assert used.json()["used_by"] == [
        {
            "uri": f"{BASE_URI}dataset/prueba/1.0.0",
            "resource": "dataset",
            "via": str(DCT.conformsTo),
            "target": DIDX,
        }
    ]
    assert api.delete("/datasets/prueba", headers=editor).status_code == 204
    assert api.delete("/ontologies/didx", headers=editor).status_code == 204


def _with_theme(theme: str) -> str:
    return fase4_data.series(
        fase4_data.V1.replace(
            'dcat:version "1.0.0" ;', f'dcat:version "1.0.0" ; dcat:theme <{theme}> ;'
        )
    )


def test_new_dataset_version_with_an_unknown_theme_is_422(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """QA-50-03: tema de {BASE_URI}vocab/ que no existe o cuyo esquema se dio de baja."""
    for theme in (f"{OT}/no-existe", f"{BASE_URI}vocab/no-existe/x", OT):
        response = fase4_data.publish(api, editor, _with_theme(theme))
        assert response.status_code == 422, (theme, response.text)
        body = response.json()
        assert body["kind"] == "unknown_theme"
        [issue] = body["issues"]
        assert issue["value"] == theme
        assert issue["focus_node"] == f"{BASE_URI}dataset/prueba/1.0.0"
        assert issue["message"] == "El tema no es un concepto de ningún esquema publicado"
    assert f"{BASE_URI}dataset/prueba" not in vocab_store.graph_names()
    # Un concepto de un esquema dado de baja.
    assert api.delete("/schemes/pqc", headers=editor).status_code == 204
    gone = fase4_data.publish(api, editor, _with_theme(f"{PQC}/ml-kem"))
    assert gone.status_code == 422
    assert gone.json()["kind"] == "unknown_theme"
    assert gone.json()["issues"][0]["message"] == (
        "El tema es un concepto de un esquema dado de baja"
    )
    # Los temas externos no se comprueban.
    assert fase4_data.publish(api, editor, _with_theme("https://otro.example/c")).status_code == 201
    # La serie Modbus (versiones ya publicadas) se republica tal cual.
    modbus = (FIXTURE_DATA_DIR / "sintetico" / "modbus-tcp-testbed.ttl").read_bytes()
    assert api.post("/datasets", content=modbus, headers=editor | TTL).status_code == 200


def test_a_vann_prefix_used_by_another_live_resource_is_409(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """QA-50-01: dos recursos vivos no comparten prefijo VANN."""
    for path, body in (
        ("/schemes", _scheme(prefix="ot")),  # el de vocab/ot
        ("/schemes", _scheme(prefix="itot")),  # el de onto/itot
        ("/ontologies", _onto(prefix="ectrl")),  # el de vocab/corp/trl
        ("/ontologies", _onto(prefix="dominio")),  # el de un esquema auxiliar
    ):
        response = _post(api, path, body, editor, "pruebas")
        assert response.status_code == 409, (path, response.text)
        assert response.json()["kind"] == "prefix_in_use"
    assert f"{BASE_URI}vocab/nuevo" not in vocab_store.graph_names()
    # El escenario de qa: el segundo con el mismo prefijo ya no se publica, así que al dar
    # de baja el primero no queda ningún recurso vivo bloqueado.
    first = _post(api, "/schemes", _scheme(prefix="compartido"), editor, "pruebas")
    assert first.status_code == 201
    second = _post(api, "/ontologies", _onto(prefix="compartido"), editor, "pruebas")
    assert second.status_code == 409 and second.json()["kind"] == "prefix_in_use"
    assert second.json()["issues"][0]["value"] == f"{BASE_URI}vocab/nuevo"
    # Los prefijos de las ontologías externas no cuentan.
    assert _post(api, "/ontologies", _onto(prefix="sosa"), editor, "pruebas").status_code == 201
    # El recurso que lo usa sigue publicando (sus versiones nuevas y su republicación).
    newer = _onto(prefix="sosa", version="1.1.0")
    assert _post(api, "/ontologies", newer, editor, "pruebas").status_code == 201
    assert _post(api, "/schemes", SCHEME_OT, editor, "vocabularios-sinteticos").status_code == 200


def _fail_on(store: MemoryStore, monkeypatch: pytest.MonkeyPatch, marker: str) -> None:
    original = store.update

    def update(request: str) -> None:
        if marker in request:
            raise TriplestoreError("Fuseki no responde (simulado)")
        original(request)

    monkeypatch.setattr(store, "update", update)


def test_withdraw_scheme_survives_a_triplestore_failure_and_can_be_retried(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA-50-04: la baja en Fuseki es una sola petición; si falla, nada a medias."""
    _fail_on(vocab_store, monkeypatch, "DROP SILENT GRAPH")
    response = api.delete("/schemes/corp/trl", headers=editor)
    assert response.status_code == 503
    # Ni lápida, ni grafo borrado, ni pertenencia quitada, ni auditoría.
    assert (URIRef(TRL), PROV.invalidatedAtTime, None) not in vocab_store.get_graph(BAJAS)
    assert TRL in vocab_store.graph_names()
    assert TRL in _members(vocab_store, VOCAB_CATALOG)
    assert api.get("/schemes/corp/trl").status_code == 200
    assert _events(session_factory, AuditAction.SCHEME_WITHDRAWN) == []
    # El prefijo ya está reservado, a su nombre: el esquema sigue publicando y nadie más
    # puede usarlo.
    with session_factory() as session:
        assert session.get(WithdrawnPrefix, "ectrl").resource_uri == TRL
    assert _post(api, "/schemes", SCHEME_TRL, editor, "vocabularios-sinteticos").status_code == 200
    # El reintento completa la baja.
    monkeypatch.undo()
    assert api.delete("/schemes/corp/trl", headers=editor).status_code == 204
    assert TRL not in vocab_store.graph_names()
    assert TRL not in _members(vocab_store, VOCAB_CATALOG)
    assert (URIRef(TRL), PROV.invalidatedAtTime, None) in vocab_store.get_graph(BAJAS)
    assert len(_events(session_factory, AuditAction.SCHEME_WITHDRAWN)) == 1
    with session_factory() as session:
        assert session.get(WithdrawnPrefix, "ectrl").resource_uri == TRL


def test_withdraw_ontology_survives_a_triplestore_failure_and_keeps_its_metrics(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_factory() as session:
        session.add(
            OntologyMetricsRecord(
                version_iri=f"{DIDX}/1.0.0",
                ontology_iri=DIDX,
                content_hash="0" * 64,
                metrics={},
                consistency={},
                tool="pruebas",
            )
        )
        session.commit()
    _fail_on(vocab_store, monkeypatch, "DROP SILENT GRAPH")
    assert api.delete("/ontologies/didx", headers=editor).status_code == 503
    assert f"{DIDX}/1.0.0" in vocab_store.graph_names()
    assert (URIRef(DIDX), PROV.invalidatedAtTime, None) not in vocab_store.get_graph(BAJAS)
    assert DIDX in _members(vocab_store, VOCAB_CATALOG)
    with session_factory() as session:
        assert session.get(OntologyMetricsRecord, f"{DIDX}/1.0.0") is not None
    monkeypatch.undo()
    assert api.delete("/ontologies/didx", headers=editor).status_code == 204
    assert f"{DIDX}/1.0.0" not in vocab_store.graph_names()
    with session_factory() as session:
        assert session.get(OntologyMetricsRecord, f"{DIDX}/1.0.0") is None


def test_withdraw_after_fuseki_is_consistent_even_if_the_audit_fails(
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si falla lo último (auditoría), la baja ya es coherente: lápida y grafo borrado."""
    from app import audit, vocab_crud

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("PostgreSQL no responde (simulado)")

    monkeypatch.setattr(audit, "record", boom)
    with session_factory() as session:
        actor = session.scalars(select(User).where(User.username == "editora")).one()
        with pytest.raises(RuntimeError):
            vocab_crud.withdraw_scheme(
                vocab_store, session, Uris(BASE_URI), settings, "trl", True, actor
            )
    assert TRL not in vocab_store.graph_names()
    assert (URIRef(TRL), PROV.invalidatedAtTime, None) in vocab_store.get_graph(BAJAS)
    assert TRL not in _members(vocab_store, VOCAB_CATALOG)
    with session_factory() as session:
        assert session.get(WithdrawnPrefix, "ectrl").resource_uri == TRL


def test_withdraw_update_keeps_hostile_titles_exactly(settings) -> None:
    """La lápida va en la misma petición de Update con BIND: ni «\\u», ni «$», ni comillas
    cambian el título ni inyectan nada."""
    from app import bajas, catalogs

    uris = Uris(BASE_URI)
    store = MemoryStore()
    scheme = f"{BASE_URI}vocab/hostil"
    other = f"{BASE_URI}vocab/otro"
    for uri in (scheme, other):
        store.put_graph(uri, Graph().add((URIRef(uri), RDF.type, SKOS.ConceptScheme)))
    store.append_graph(
        TEST_CATALOG_URI, Graph().add((URIRef(TEST_CATALOG_URI), DCAT.resource, URIRef(scheme)))
    )
    titles = [
        Literal('Título \\u0041 "x" $bajas } ; DROP ALL #', lang="es"),
        Literal("Back\\slash\\\\ final\\", lang="en"),
        Literal("Sin idioma \n con salto"),
    ]
    tombstone = catalogs.build_tombstone(uris, scheme, titles, settings)
    store.update(bajas.withdraw_resource_update(uris, scheme, tombstone, [scheme]))
    stored = store.get_graph(BAJAS)
    assert set(stored.objects(URIRef(scheme), DCT.title)) == set(titles)
    assert set(stored.subjects()) == {URIRef(scheme)}
    assert scheme not in store.graph_names()
    assert other in store.graph_names()  # nada más se ha tocado
    assert not list(store.get_graph(TEST_CATALOG_URI).triples((None, DCAT.resource, None)))


def _cli_on_copy(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    store: MemoryStore,
    file_storage: DiskStorage,
    copy: Path,
) -> None:
    monkeypatch.setenv("SEMANTIC_DIR", str(copy))
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)
    get_settings.cache_clear()
    ingest.clear_caches()


def test_load_semantic_rejects_duplicated_or_taken_prefixes(
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    file_storage: DiskStorage,
    semantic_dir: Path,
    tmp_path: Path,
) -> None:
    """QA-50-01 en load-semantic: entre ficheros y contra lo publicado desde la aplicación."""
    import shutil

    copy = tmp_path / "semantic"
    shutil.copytree(semantic_dir, copy)
    pqc = copy / "vocabularios" / "pqc.ttl"
    original = pqc.read_text(encoding="utf-8")
    pqc.write_text(
        original.replace('preferredNamespacePrefix "pqc"', 'preferredNamespacePrefix "ot"'),
        encoding="utf-8",
    )
    _cli_on_copy(monkeypatch, session_factory, store, file_storage, copy)
    try:
        result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
        assert result.exit_code == 1, result.output
        assert "«ot» ya lo usa" in result.output
        assert OT not in store.graph_names()
        # Contra lo publicado: un esquema creado desde la aplicación con el prefijo «pqc».
        pqc.write_text(original, encoding="utf-8")
        taken = Graph().parse(
            data=_scheme(prefix="pqc").decode(), format="turtle", publicID=BASE_URI
        )
        store.put_graph(f"{BASE_URI}vocab/nuevo", taken)
        result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
        assert result.exit_code == 1, result.output
        assert "«pqc» ya lo usa" in result.output
        assert f"{BASE_URI}vocab/nuevo" in result.output
        assert OT not in store.graph_names()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        ingest.clear_caches()


def test_load_semantic_rejects_an_unknown_theme_before_writing(
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    file_storage: DiskStorage,
    semantic_dir: Path,
    tmp_path: Path,
) -> None:
    """QA-50-03 en load-semantic: se comprueba al validar, antes de escribir nada."""
    import shutil

    copy = tmp_path / "semantic"
    shutil.copytree(semantic_dir, copy)
    series = copy / "data" / "sintetico" / "modbus-tcp-testbed.ttl"
    text = series.read_text(encoding="utf-8")
    assert "ot:modbus-tcp ," in text
    series.write_text(text.replace("ot:modbus-tcp ,", "ot:no-existe ,"), encoding="utf-8")
    _cli_on_copy(monkeypatch, session_factory, store, file_storage, copy)
    try:
        result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        ingest.clear_caches()
    assert result.exit_code == 1, result.output
    assert "El tema no es un concepto de ningún esquema publicado" in result.output
    assert OT not in store.graph_names()  # no se escribe nada
