"""Ingesta de ontologías (``POST /ontologies``) y esquemas SKOS (``POST /schemes``)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib.namespace import RDF
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import ingest, owl_metrics, vocab_ingest
from app.config import Settings
from app.models import AuditAction, AuditEvent, OntologyMetricsRecord, Role, User
from app.triplestore import MemoryStore
from app.uris import SKOS, Uris
from tests.conftest import BASE_URI, FIXTURE_SEMANTIC_DIR, user_graphs

ONTO_DIR = FIXTURE_SEMANTIC_DIR / "ontologias" / "itot"
VOCAB_DIR = FIXTURE_SEMANTIC_DIR / "vocabularios"
ONTO_120 = (ONTO_DIR / "1.2.0.ttl").read_bytes()
SCHEME_OT = (VOCAB_DIR / "ot.ttl").read_bytes()
SCHEME_CORP = (VOCAB_DIR / "corp" / "trl.ttl").read_bytes()
TTL = {"Content-Type": "text/turtle"}


requires_java = pytest.mark.skipif(
    not owl_metrics.java_available(), reason="Pellet necesita Java y no está en el PATH"
)


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]) -> dict[str, str]:
    make_user("editora", Role.EDITOR)
    return login("editora")


STATUS = "<http://purl.org/adms/status/Completed>"


def _onto(body: str, version: str = "1.0.0", slug: str = "prueba", *, status: bool = True) -> bytes:
    """Versión mínima que cumple las formas de semantico (título, descripción, VANN y
    estado)."""
    state = f"adms:status {STATUS} ;" if status else ""
    return f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
@prefix : <onto/{slug}#> .
<onto/{slug}> a owl:Ontology ; owl:versionIRI <onto/{slug}/{version}> ;
    owl:versionInfo "{version}" ; {state}
    dct:title "Ontología de prueba"@es ; dct:description "Ontología de prueba"@es ;
    vann:preferredNamespacePrefix "prueba" ; vann:preferredNamespaceUri <onto/{slug}#> .
{body}
""".encode()


def _events(session_factory: sessionmaker[Session], action: AuditAction) -> list[AuditEvent]:
    with session_factory() as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.action == action)))


# --- POST /ontologies: válida -----------------------------------------------------------


@requires_java
def test_ingest_ontology_computes_and_stores_metrics(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post("/ontologies", content=ONTO_120, headers=editor | TTL)
    assert response.status_code == 201, response.text
    body = response.json()
    version_iri = f"{BASE_URI}onto/itot/1.2.0"
    assert body["slug"] == "itot"
    assert body["version"] == "1.2.0"
    assert body["version_iri"] == body["graph"] == version_iri
    assert body["created"] is True and body["changed"] is True
    assert body["metrics_recomputed"] is True
    # Las cifras no se fijan aquí (semantico puede cambiar la ontología de demostración):
    # se comparan con el cálculo directo sobre el mismo fichero.
    expected = owl_metrics.compute_metrics(
        ingest.parse_rdf(ONTO_120, "turtle", BASE_URI), f"{BASE_URI}onto/itot"
    ).to_dict()
    assert body["metrics"] == {
        key: expected[key]
        for key in (
            "classes",
            "object_properties",
            "data_properties",
            "annotation_properties",
            "individuals",
            "logical_axioms",
            "imports",
        )
    } | {"dl_expressivity": None}
    assert body["metrics"]["classes"] > 0
    assert body["profile"]["name"] == "OWL 2 DL"
    assert body["consistency"]["reasoner"] == "Pellet"
    assert body["consistency"]["consistent"] is True
    assert body["consistency"]["unsatisfiable_classes"] == 0
    assert body["consistency"]["includes_imports"] is False
    assert body["documentation"]["percent"] == expected["documentation"]["percent"]

    # Solo escribe en el grafo de su versionIRI.
    assert user_graphs(store) == {version_iri}
    with session_factory() as session:
        record = session.get(OntologyMetricsRecord, version_iri)
        assert record is not None
        assert record.ontology_iri == f"{BASE_URI}onto/itot"
        assert record.metrics["classes"] == body["metrics"]["classes"]
        assert record.consistency["consistent"] is True
        assert "owlready2" in record.tool and "Pellet" in record.tool
    [event] = _events(session_factory, AuditAction.ONTOLOGY_PUBLISHED)
    assert event.actor_username == "editora"
    assert event.details["version_iri"] == version_iri
    assert event.details["via"] == "api"
    assert event.details["metrics_recomputed"] is True


@requires_java
def test_reingest_identical_does_not_recompute(
    client: TestClient,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post("/ontologies", content=ONTO_120, headers=editor | TTL).status_code == 201

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no debería recalcular las métricas")

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fail)
    response = client.post("/ontologies", content=ONTO_120, headers=editor | TTL)
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False and body["changed"] is False
    assert body["metrics_recomputed"] is False
    assert body["metrics"]["classes"] > 0
    assert len(_events(session_factory, AuditAction.ONTOLOGY_PUBLISHED)) == 2


def test_changed_content_recomputes(
    client: TestClient,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake(prepared: vocab_ingest.PreparedOntology, settings: Settings) -> tuple[dict, dict]:
        calls.append(prepared.version_iri)
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri).to_dict()
        return metrics, owl_metrics.Consistency(detail="sin razonador en esta prueba").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake)
    first = client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=editor | TTL)
    assert first.status_code == 201
    assert first.json()["metrics"]["classes"] == 1
    assert first.json()["consistency"]["consistent"] is None
    # Fase 4 (decisión 28): la versión publicada es inmutable. Otro contenido con la misma
    # versionIRI es 409 sin recalcular nada; las métricas se recalculan si el contenido
    # guardado cambia (aquí, el registro de métricas no coincide con el grafo).
    second = client.post(
        "/ontologies", content=_onto(":A a owl:Class . :B a owl:Class ."), headers=editor | TTL
    )
    assert second.status_code == 409
    assert second.json()["kind"] == "version_immutable"
    assert len(calls) == 1
    with session_factory() as session:
        record = session.get(OntologyMetricsRecord, f"{BASE_URI}onto/prueba/1.0.0")
        assert record is not None
        record.content_hash = "0" * 64  # métricas de otro contenido
        session.commit()
    third = client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=editor | TTL)
    assert third.status_code == 200
    assert third.json()["changed"] is False
    assert third.json()["metrics_recomputed"] is True
    assert len(calls) == 2


@requires_java
def test_ingest_inconsistent_ontology_is_accepted_and_reported(
    client: TestClient, editor: dict[str, str]
) -> None:
    body = _onto(
        ":A a owl:Class . :B a owl:Class . :A owl:disjointWith :B . "
        ":x a owl:NamedIndividual , :A , :B ."
    )
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 201, response.text
    assert response.json()["consistency"]["consistent"] is False


def test_ingest_ontology_jsonld(
    client: TestClient, editor: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        vocab_ingest,
        "compute_ontology_metrics",
        lambda p, _s: (
            owl_metrics.compute_metrics(p.graph, p.uri).to_dict(),
            owl_metrics.Consistency().to_dict(),
        ),
    )
    document = {
        "@context": {
            "owl": "http://www.w3.org/2002/07/owl#",
            "dct": "http://purl.org/dc/terms/",
            "adms": "http://www.w3.org/ns/adms#",
            "vann": "http://purl.org/vocab/vann/",
        },
        "@id": "onto/jsonld",
        "@type": "owl:Ontology",
        "owl:versionIRI": {"@id": "onto/jsonld/0.1.0"},
        "owl:versionInfo": "0.1.0",
        "dct:title": {"@value": "Prueba JSON-LD", "@language": "es"},
        "dct:description": {"@value": "Prueba JSON-LD", "@language": "es"},
        "adms:status": {"@id": "http://purl.org/adms/status/UnderDevelopment"},
        "vann:preferredNamespacePrefix": "jsonld",
        "vann:preferredNamespaceUri": {"@id": "onto/jsonld#"},
    }
    response = client.post(
        "/ontologies",
        content=json.dumps(document),
        headers=editor | {"Content-Type": "application/ld+json"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["version_iri"] == f"{BASE_URI}onto/jsonld/0.1.0"


# --- POST /ontologies: permisos ---------------------------------------------------------


@pytest.fixture
def fake_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        vocab_ingest,
        "compute_ontology_metrics",
        lambda p, _s: (
            owl_metrics.compute_metrics(p.graph, p.uri).to_dict(),
            owl_metrics.Consistency().to_dict(),
        ),
    )


@pytest.mark.usefixtures("fake_metrics")
@pytest.mark.parametrize(("path", "content"), [("/ontologies", ONTO_120), ("/schemes", SCHEME_OT)])
def test_admin_inherits_editor_permissions(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    path: str,
    content: bytes,
) -> None:
    make_user("admin1", Role.ADMIN)
    response = client.post(path, content=content, headers=login("admin1") | TTL)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("path", ["/ontologies", "/schemes"])
def test_member_is_forbidden(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    store: MemoryStore,
    path: str,
) -> None:
    make_user("miembro1", Role.MIEMBRO)
    response = client.post(path, content=SCHEME_OT, headers=login("miembro1") | TTL)
    assert response.status_code == 403
    assert user_graphs(store) == set()


@pytest.mark.parametrize("path", ["/ontologies", "/schemes"])
@pytest.mark.parametrize(
    "headers",
    [
        TTL,
        {"Content-Type": "application/x-no-soportado"},
        {"Content-Type": "text/turtle", "Content-Length": str(10**12)},
    ],
)
def test_anonymous_gets_401_before_body_checks(
    client: TestClient, store: MemoryStore, path: str, headers: dict[str, str]
) -> None:
    response = client.post(path, content=b"x", headers=headers)
    assert response.status_code == 401
    assert user_graphs(store) == set()


def test_unsupported_media_and_too_large(
    client: TestClient, editor: dict[str, str], settings: Settings
) -> None:
    bad = client.post("/ontologies", content=b"x", headers=editor | {"Content-Type": "text/xml"})
    assert bad.status_code == 415
    big = b"#" * (settings.ingest_max_bytes + 1)
    assert client.post("/schemes", content=big, headers=editor | TTL).status_code == 413


# --- POST /ontologies: inválida ---------------------------------------------------------


INVALID_ONTOLOGIES = [
    (b"", "syntax"),
    (b"esto no es turtle <<<", "syntax"),
    (
        _onto("<onto/otra> a <http://www.w3.org/2002/07/owl#Ontology> ."),
        "structure",
    ),
    (
        b"@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        b"[] a owl:Ontology ; owl:versionIRI <onto/x/1.0.0> .",
        "uri",
    ),
    (
        b"@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        b"<https://otro.example/onto/x> a owl:Ontology ; "
        b"owl:versionIRI <https://otro.example/onto/x/1.0.0> .",
        "uri",
    ),
    (
        b"@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        b"<onto/externas> a owl:Ontology ; owl:versionIRI <onto/externas/1.0.0> .",
        "uri",
    ),
    (b"@prefix owl: <http://www.w3.org/2002/07/owl#> . <onto/x> a owl:Ontology .", "structure"),
    (
        b"@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        b"<onto/x> a owl:Ontology ; owl:versionIRI <onto/y/1.0.0> .",
        "uri",
    ),
    (
        b"@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        b"<onto/x> a owl:Ontology ; owl:versionIRI <onto/x/v1> .",
        "uri",
    ),
    (_onto('<onto/prueba> owl:versionInfo "2.0.0" .'), "uri"),
    (_onto("<onto/prueba> owl:priorVersion <onto/prueba/1.0.0> ."), "uri"),
    (_onto("<onto/prueba> owl:priorVersion <onto/otra/0.9.0> ."), "uri"),
    (_onto("<onto/prueba> owl:backwardCompatibleWith <onto/prueba/2.0.0> ."), "uri"),
    # Sujetos bajo BASE_URI que no son de la ontología.
    (_onto('<dataset/modbus-tcp-testbed> rdfs:label "pisado" .'), "uri"),
    (_onto('<vocab/ot/modbus-tcp> rdfs:label "pisado" .'), "uri"),
    (_onto('<onto/otra#A> rdfs:label "pisado" .'), "uri"),
    (_onto('<onto/prueba/A> rdfs:label "sin almohadilla" .'), "uri"),
    # IRIs no válidas.
    (_onto("<onto/prueba#A> rdfs:seeAlso <http://x.example/a b> ."), "uri"),
]


@pytest.mark.usefixtures("fake_metrics")
@pytest.mark.parametrize(("content", "kind"), INVALID_ONTOLOGIES)
def test_invalid_ontology_is_rejected(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    content: bytes,
    kind: str,
) -> None:
    response = client.post("/ontologies", content=content, headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == kind
    assert user_graphs(store) == set()
    assert _events(session_factory, AuditAction.ONTOLOGY_PUBLISHED) == []
    with session_factory() as session:
        assert session.scalars(select(OntologyMetricsRecord)).first() is None


@pytest.mark.usefixtures("fake_metrics")
def test_external_subjects_are_allowed_in_ontology(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    body = _onto(
        ":A a owl:Class ; rdfs:subClassOf <https://example.org/externa/sensores#Plataforma> . "
        "<https://example.org/externa/sensores#Plataforma> a owl:Class ."
    )
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 201, response.text
    assert user_graphs(store) == {f"{BASE_URI}onto/prueba/1.0.0"}


def test_deep_nesting_is_rejected(client: TestClient, editor: dict[str, str]) -> None:
    nested = "[ rdfs:seeAlso " * 80 + "<urn:x:fin>" + " ]" * 80
    body = _onto(f":A rdfs:seeAlso {nested} .")
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 422
    assert response.json()["kind"] == "syntax"


def test_remote_jsonld_context_is_rejected(client: TestClient, editor: dict[str, str]) -> None:
    document = {"@context": "https://example.org/contexto.jsonld", "@id": "onto/x"}
    response = client.post(
        "/schemes",
        content=json.dumps(document),
        headers=editor | {"Content-Type": "application/ld+json"},
    )
    assert response.status_code == 422
    assert response.json()["kind"] == "syntax"


# --- POST /schemes ----------------------------------------------------------------------


def test_ingest_domain_scheme(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post("/schemes", content=SCHEME_OT, headers=editor | TTL)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {
        "slug": "ot",
        "corp": False,
        "uri": f"{BASE_URI}vocab/ot",
        "graph": f"{BASE_URI}vocab/ot",
        "concepts": 16,
        "triples": body["triples"],
        "created": True,
        "changed": True,
    }
    assert user_graphs(store) == {f"{BASE_URI}vocab/ot"}
    again = client.post("/schemes", content=SCHEME_OT, headers=editor | TTL)
    assert again.status_code == 200
    assert again.json()["changed"] is False
    events = _events(session_factory, AuditAction.SCHEME_PUBLISHED)
    assert [e.details["changed"] for e in events] == [True, False]
    assert events[0].details["scheme"] == f"{BASE_URI}vocab/ot"
    assert events[0].details["corp"] is False


def test_ingest_corp_scheme(client: TestClient, editor: dict[str, str], store: MemoryStore) -> None:
    response = client.post("/schemes", content=SCHEME_CORP, headers=editor | TTL)
    assert response.status_code == 201, response.text
    assert response.json()["corp"] is True
    assert response.json()["slug"] == "trl"
    assert response.json()["concepts"] == 9
    assert user_graphs(store) == {f"{BASE_URI}vocab/corp/trl"}


def _scheme(body: str, uri: str = "vocab/prueba", *, description: bool = True) -> bytes:
    """Esquema mínimo que cumple las formas de semantico."""
    text = 'dct:description "Esquema de prueba"@es ;' if description else ""
    return f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
<{uri}> a skos:ConceptScheme ; skos:prefLabel "Prueba"@es ; dct:title "Prueba"@es ; {text}
    owl:versionInfo "1.0" ; adms:status {STATUS} ;
    vann:preferredNamespacePrefix "prueba" ; vann:preferredNamespaceUri <{uri}/> .
{body}
""".encode()


INVALID_SCHEMES = [
    (_scheme("<vocab/otro> a skos:ConceptScheme ."), "structure"),
    (_scheme("", uri="vocab/corp"), "uri"),
    (_scheme("", uri="vocab/corp/a/b"), "uri"),
    (_scheme("", uri="vocab/Mayusculas"), "uri"),
    (_scheme("", uri="onto/prueba"), "uri"),
    (_scheme("", uri="https://otro.example/vocab/x"), "uri"),
    (b"@prefix skos: <http://www.w3.org/2004/02/skos/core#> . [] a skos:ConceptScheme .", "uri"),
    (_scheme('<vocab/ot/modbus-tcp> skos:prefLabel "pisado"@es .'), "uri"),
    (_scheme("<vocab/prueba/a/b> a skos:Concept ."), "uri"),
    (_scheme('<dataset/x> skos:prefLabel "x" .'), "uri"),
    (_scheme('<https://otro.example/c> skos:prefLabel "externo" .'), "uri"),
    (_scheme("<vocab/prueba/c> skos:exactMatch <http://x.example/a b> ."), "uri"),
]


@pytest.mark.parametrize(("content", "kind"), INVALID_SCHEMES)
def test_invalid_scheme_is_rejected(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    content: bytes,
    kind: str,
) -> None:
    response = client.post("/schemes", content=content, headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == kind
    assert user_graphs(store) == set()
    assert _events(session_factory, AuditAction.SCHEME_PUBLISHED) == []


# --- SHACL (formas de semantico) ----------------------------------------------------


@pytest.mark.usefixtures("fake_metrics")
def test_valid_minimal_ontology_and_scheme_pass_shacl(
    client: TestClient, editor: dict[str, str]
) -> None:
    onto = client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=editor | TTL)
    assert onto.status_code == 201, onto.text
    scheme = client.post("/schemes", content=_scheme(""), headers=editor | TTL)
    assert scheme.status_code == 201, scheme.text


@pytest.mark.usefixtures("fake_metrics")
def test_shacl_violations_reject_ontology_and_scheme(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    onto = client.post(
        "/ontologies", content=_onto(":A a owl:Class .", status=False), headers=editor | TTL
    )
    assert onto.status_code == 422
    body = onto.json()
    assert body["kind"] == "shacl"
    assert body["report"]
    assert any(i["path"] == "http://www.w3.org/ns/adms#status" for i in body["issues"])

    scheme = client.post("/schemes", content=_scheme("", description=False), headers=editor | TTL)
    assert scheme.status_code == 422
    assert scheme.json()["kind"] == "shacl"
    assert user_graphs(store) == set()


@pytest.mark.parametrize(
    "path",
    sorted((FIXTURE_SEMANTIC_DIR.parent / "invalid-ontologias-vocabularios").glob("*.ttl")),
    ids=lambda p: p.stem,
)
def test_semantico_invalid_examples_are_rejected(path: Path, settings: Settings) -> None:
    """Los ejemplos inválidos de semantico fallan en la ingesta (estructura o SHACL)."""
    uris = Uris(BASE_URI)
    graph = ingest.parse_rdf(path.read_bytes(), "turtle", BASE_URI)
    with pytest.raises(ingest.IngestError):
        if (None, RDF.type, SKOS.ConceptScheme) in graph:
            vocab_ingest.prepare_scheme(graph, uris, settings)
        else:
            vocab_ingest.prepare_ontology(graph, uris, settings)
