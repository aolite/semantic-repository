"""Pruebas de seguridad de la fase 3 (agente ``qa``): vocabularios y ontologías.

Complementan ``test_security_fase3.py``, ``test_vocab_ingest.py``, ``test_vocab_read.py`` y
``test_owl_metrics.py`` (del agente ``backend``) con estos bloques:

1. **Inyección SPARQL** en los parámetros nuevos que aquellas no cubren (``kind``,
   ``domain``, ``format``, ``download`` y ``version`` de ``/rdf``) y en IRIs hostiles
   guardadas por una ingesta.
2. **Ingesta maliciosa** de ontologías y esquemas: escribir en el grafo de otro recurso,
   slugs reservados, versiones incoherentes, IRIs que imitan ``BASE_URI``, ``owl:imports``
   remotos (ninguna petición de red), XXE, bombas de expansión, tokens manipulados y
   auditoría.
3. **Pellet y Java**: tiempo máximo, fallos del razonador y entradas que owlready2 no
   sabe leer, sin tumbar el servicio ni filtrar trazas o rutas.
4. **Lectura pública** limitada a los grafos publicados.
5. **``Content-Disposition``** con nombres de fichero seguros.
6. **Contenido guardado** que no debe romper la lectura.

Defectos abiertos: van con ``xfail(strict=True)`` y su identificador ``QA-G3-nn``. Cuando
el agente dueño los corrija, la prueba pasará y habrá que quitar la marca.

Todas las credenciales son ficticias. Ninguna prueba sale a la red.
"""

import json
import shutil
import socket
import subprocess
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import downloads, ingest, owl_metrics
from app.config import Settings
from app.models import AuditAction, AuditEvent, OntologyMetricsRecord, Role, User
from app.negotiation import JSONLD, RDFXML, TURTLE
from app.triplestore import MemoryStore
from app.uris import DCAT, DCT, SKOS, Uris
from tests.conftest import BASE_URI
from tests.test_security_fase2 import INJECTIONS
from tests.test_security_fase3 import _assert_only_fixed_queries
from tests.test_vocab_ingest import _onto, _scheme

TTL = {"Content-Type": TURTLE}
LD = {"Content-Type": JSONLD}
PRUEBA = f"{BASE_URI}onto/prueba"
RDF_NS = str(RDF)
XSD_NS = "http://www.w3.org/2001/XMLSchema#"

requires_java = pytest.mark.skipif(
    not owl_metrics.java_available(), reason="Pellet necesita Java 25 o superior en el PATH"
)


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]) -> dict[str, str]:
    make_user("editora", Role.EDITOR)
    return login("editora")


@pytest.fixture
def quiet(client: TestClient) -> TestClient:
    """Cliente que devuelve el 500 en lugar de relanzar la excepción del servidor."""
    return TestClient(client.app, raise_server_exceptions=False)


@pytest.fixture
def fake_reasoner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Métricas reales de owlready2, sin lanzar Java (consistencia «no disponible»)."""
    monkeypatch.setattr(
        owl_metrics,
        "check_consistency",
        lambda *_args, **_kwargs: owl_metrics.Consistency(detail="razonador desactivado"),
    )


def _snapshot(store: MemoryStore) -> dict[str, set[tuple[str, str, str]]]:
    return {
        name: {(s.n3(), p.n3(), o.n3()) for s, p, o in store.dataset.graph(URIRef(name))}
        for name in sorted(store.graph_names())
    }


def _events(session_factory: sessionmaker[Session], *actions: AuditAction) -> list[AuditEvent]:
    with session_factory() as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.action.in_(actions))))


def _metric_rows(session_factory: sessionmaker[Session]) -> list[str]:
    with session_factory() as session:
        return sorted(session.scalars(select(OntologyMetricsRecord.version_iri)))


PUBLISH_ACTIONS = (AuditAction.ONTOLOGY_PUBLISHED, AuditAction.SCHEME_PUBLISHED)

CONCEPT = (
    "<vocab/prueba> skos:hasTopConcept <vocab/prueba/c> . <vocab/prueba/c> a skos:Concept ; "
    'skos:inScheme <vocab/prueba> ; skos:topConceptOf <vocab/prueba> ; skos:prefLabel "c"@es '
)


# --- 1. Inyección SPARQL ----------------------------------------------------------------


@pytest.fixture
def api(client: TestClient, vocab_store: MemoryStore, vocab_metrics: None) -> TestClient:
    return client


@pytest.mark.parametrize("payload", INJECTIONS)
@pytest.mark.parametrize(
    ("path", "param"),
    [
        ("/vocabularies", "kind"),
        ("/vocabularies", "domain"),
        ("/ontologies/itot/rdf", "format"),
        ("/ontologies/itot/rdf", "version"),
        ("/ontologies/itot/rdf", "download"),
        ("/schemes/ot/rdf", "format"),
        ("/schemes/ot/rdf", "download"),
        ("/schemes/corp/trl/rdf", "format"),
        ("/schemes/corp/trl/rdf", "download"),
        ("/datasets/modbus-tcp-testbed/rdf", "download"),
    ],
)
def test_enumerated_parameters_reject_payloads(
    api: TestClient, vocab_store: MemoryStore, path: str, param: str, payload: str
) -> None:
    before = _snapshot(vocab_store)
    vocab_store.queries.clear()
    response = api.get(path, params={param: payload}, headers={"Accept": TURTLE})
    assert response.status_code == 422, response.text
    assert vocab_store.queries == [], "un parámetro no válido no debe llegar al triplestore"
    assert "content-disposition" not in response.headers
    assert _snapshot(vocab_store) == before


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/vocabularies", {"domain": "did"}),  # did es un esquema, no un dominio
        ("/vocabularies", {"domain": "dominio"}),
        ("/vocabularies", {"kind": "OWN"}),
        ("/ontologies/itot/rdf", {"format": "nt"}),
        ("/ontologies/itot/rdf", {"format": "TURTLE"}),
        ("/datasets/modbus-tcp-testbed/rdf", {"format": "rdfxml"}),
        ("/ontologies/itot/rdf", {"download": "2"}),
        ("/ontologies/itot", {"version": "1.2"}),
        ("/ontologies/itot", {"version": "01.2.0"}),
        ("/ontologies/itot", {"version": "1.2.0\n"}),
    ],
)
def test_values_outside_the_contract_are_rejected(
    api: TestClient, path: str, params: dict[str, str]
) -> None:
    assert api.get(path, params=params).status_code == 422


HOSTILE_IRIS = [
    "http://x.example/a'b)*;DROP$graph",
    "http://x.example/$vocab_ns/$values/$$",
    "http://x.example/?q=1&r=%22%7D%20UNION%20%7B#frag",
    "urn:x:%3E%20%7D%20UNION%20%7B%20GRAPH%20%3Fg",
]


@pytest.mark.parametrize("hostile", HOSTILE_IRIS)
def test_hostile_iris_in_scheme_are_stored_as_data(
    client: TestClient, editor: dict[str, str], loaded_store: MemoryStore, hostile: str
) -> None:
    """IRIs con sintaxis de plantilla o de SPARQL: se guardan y se leen como datos."""
    body = _scheme(
        CONCEPT
        + f"; skos:exactMatch <{hostile}> ; skos:closeMatch <{hostile}> ; "
        + f"skos:related <{hostile}> ."
        + f"\n<vocab/prueba> dct:creator <{hostile}> ."
    )
    response = client.post("/schemes", content=body, headers=editor | TTL)
    assert response.status_code == 201, response.text
    loaded_store.queries.clear()
    concept = client.get("/schemes/prueba/concepts/c")
    assert concept.status_code == 200, concept.text
    assert concept.json()["exact_match"] == [hostile]
    assert concept.json()["close_match"] == [hostile]
    assert client.get("/schemes/prueba").status_code == 200
    assert client.get("/vocabularies").status_code == 200
    assert client.get("/vocab/prueba/c", headers={"Accept": TURTLE}).status_code == 200
    _assert_only_fixed_queries(loaded_store)
    for query in loaded_store.queries:
        assert hostile not in query


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("hostile", HOSTILE_IRIS)
def test_hostile_iris_in_ontology_are_stored_as_data(
    client: TestClient, editor: dict[str, str], loaded_store: MemoryStore, hostile: str
) -> None:
    body = _onto(
        f"<onto/prueba> dct:subject <{hostile}> , <vocab/ot/modbus-tcp> ; owl:imports <{hostile}> ."
        f"\n:A a owl:Class ; rdfs:subClassOf <{hostile}> ; rdfs:seeAlso <{hostile}> ."
    )
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 201, response.text
    loaded_store.queries.clear()
    detail = client.get("/ontologies/prueba")
    assert detail.status_code == 200, detail.text
    assert hostile in {s["uri"] for s in detail.json()["subjects"]}
    assert hostile in {i["uri"] for i in detail.json()["imports"]}
    assert client.get("/vocabularies").status_code == 200
    assert client.get("/schemes/ot/concepts/modbus-tcp").status_code == 200
    _assert_only_fixed_queries(loaded_store)
    for query in loaded_store.queries:
        assert hostile not in query


# --- 2. Ingesta maliciosa: escribir en otro grafo ----------------------------------------

# Cuerpos válidos salvo por un sujeto que pertenece a otro recurso.
FOREIGN_SUBJECTS = [
    "onto/itot",  # otra ontología
    "onto/itot/1.2.0",  # el versionIRI de otra ontología
    "onto/itot/9.9.9",  # una versión nueva de otra ontología
    "onto/itot#Controlador",  # un término de otra ontología
    "onto/prueba/2.0.0",  # otra versión de la misma
    "onto/prueba/1.0.0/extra",
    "onto/externas",  # el grafo de las externas
    "vocab/ot",  # un esquema
    "vocab/ot/modbus-tcp",  # un concepto
    "vocab/corp/trl",
    "vocab/dominio",  # el esquema de dominios
    "vocab/dominio/ot",
    "vocab/tipo-dataset/sintetico",
    "vocab/",  # el grafo del vocabulario de la fase 2
    "catalogo",  # el catálogo
    "dataset/modbus-tcp-testbed",  # una serie
    "dataset/modbus-tcp-testbed/2.1.0",
    "dataset/modbus-tcp-testbed/2.1.0/pcap",
    "actividad/extraccion-caracteristicas",
    "shapes#DatasetShape",
    "",  # la propia BASE_URI
]


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("subject", FOREIGN_SUBJECTS)
def test_ontology_ingest_cannot_describe_other_resources(
    client: TestClient,
    editor: dict[str, str],
    vocab_store: MemoryStore,
    session_factory: sessionmaker[Session],
    subject: str,
) -> None:
    before = _snapshot(vocab_store)
    body = _onto(f':A a owl:Class . <{subject}> rdfs:label "pisado"@es .')
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "uri"
    assert _snapshot(vocab_store) == before
    assert _events(session_factory, *PUBLISH_ACTIONS) == []
    assert _metric_rows(session_factory) == []


@pytest.mark.parametrize(
    "subject",
    [s for s in FOREIGN_SUBJECTS if not s.startswith("vocab/prueba")]
    + [
        "vocab/corp/prueba",
        "vocab/corp/prueba/c",
        "vocab/prueba/c/d",
        "vocab/prueba/",
        "onto/prueba",
    ],
)
def test_scheme_ingest_cannot_describe_other_resources(
    client: TestClient,
    editor: dict[str, str],
    vocab_store: MemoryStore,
    session_factory: sessionmaker[Session],
    subject: str,
) -> None:
    before = _snapshot(vocab_store)
    body = _scheme(CONCEPT + f'. <{subject}> skos:prefLabel "pisado"@es .')
    response = client.post("/schemes", content=body, headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "uri"
    assert _snapshot(vocab_store) == before
    assert _events(session_factory, *PUBLISH_ACTIONS) == []


def test_scheme_ingest_rejects_external_subjects(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    body = _scheme(CONCEPT + '. <https://otro.example/vocab/x> skos:prefLabel "externo"@es .')
    assert client.post("/schemes", content=body, headers=editor | TTL).status_code == 422
    assert store.graph_names() == set()


# IRIs que se parecen a BASE_URI pero no son la misma cadena. Pueden admitirse como
# sujetos externos, pero nunca deben tocar otro grafo ni aparecer en la lectura pública.
LOOKALIKES = [
    "https://SEMANTIC.example.org/itot/dataset/modbus-tcp-testbed",
    "https://semantic.example.org:443/itot/dataset/modbus-tcp-testbed",
    "http://semantic.example.org/itot/dataset/modbus-tcp-testbed",
    "https://semantic.example.org/itot",
    "https://semantic.example.org/itot/../itot/dataset/modbus-tcp-testbed",
    "https://semantic.example.org/itot/onto/../dataset/modbus-tcp-testbed",
    "https://semantic.example.org/itot/./vocab/ot",
    "https://semantic.example.org//itot/vocab/ot",
    "https://semantic.example.org/itot/dataset/%6dodbus-tcp-testbed",
    "https://user@semantic.example.org/itot/vocab/ot",
]

READS_TO_COMPARE = [
    "/datasets",
    "/datasets/modbus-tcp-testbed",
    "/vocabularies",
    "/ontologies/itot",
    "/schemes/ot",
    "/schemes/ot/concepts/modbus-tcp",
    "/schemes/corp/trl",
]


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("lookalike", LOOKALIKES)
def test_lookalike_iris_never_touch_other_graphs(
    api: TestClient, editor: dict[str, str], vocab_store: MemoryStore, lookalike: str
) -> None:
    before = _snapshot(vocab_store)
    reads = {path: api.get(path).json() for path in READS_TO_COMPARE}
    body = _onto(
        f"<{lookalike}> a <{DCAT.DatasetSeries}> , skos:ConceptScheme , skos:Concept ; "
        f'dct:title "PISADO"@es ; skos:prefLabel "PISADO"@es ; '
        f"skos:inScheme <vocab/ot> ; dcat:theme <vocab/ot/modbus-tcp> ."
    ).replace(
        b"@prefix : <onto/prueba#> .",
        b"@prefix : <onto/prueba#> . @prefix skos: <http://www.w3.org/2004/02/skos/core#> . "
        b"@prefix dcat: <http://www.w3.org/ns/dcat#> .",
    )
    response = api.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code in (201, 422), response.text
    after = _snapshot(vocab_store)
    if response.status_code == 201:
        # Solo se ha creado el grafo de la versión publicada.
        assert set(after) - set(before) == {f"{PRUEBA}/1.0.0"}
    for name, triples in before.items():
        assert after[name] == triples, name
    for path, expected in reads.items():
        if path == "/vocabularies" and response.status_code == 201:
            continue  # aparece la ontología nueva: se comprueba abajo
        assert api.get(path).json() == expected, path
    listing = json.dumps(api.get("/vocabularies").json(), ensure_ascii=False)
    assert "PISADO" not in listing
    assert "PISADO" not in api.get("/datasets").text


# --- Slugs reservados y versiones incoherentes ---------------------------------------------


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("slug", ["externas", "Externas", "externas/", "a_b", "-a", "a--b", "a/b"])
def test_ontology_slug_rules(
    client: TestClient, editor: dict[str, str], store: MemoryStore, slug: str
) -> None:
    body = _onto(":A a owl:Class .", slug=slug)
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert store.graph_names() == set()


@pytest.mark.parametrize("uri", ["vocab/corp", "vocab/corp/", "vocab/corp/corp/x", "vocab/Corp"])
def test_corp_is_a_reserved_scheme_slug(
    client: TestClient, editor: dict[str, str], store: MemoryStore, uri: str
) -> None:
    response = client.post("/schemes", content=_scheme("", uri=uri), headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert store.graph_names() == set()


@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-06: semantic/uris.md reserva los slugs 'dominio' y 'tipo-dataset', pero "
    "POST /schemes los admite y un editor sustituye los esquemas auxiliares del catálogo",
)
@pytest.mark.parametrize("slug", ["dominio", "tipo-dataset"])
def test_auxiliary_scheme_slugs_are_reserved(
    client: TestClient, editor: dict[str, str], loaded_store: MemoryStore, slug: str
) -> None:
    before = _snapshot(loaded_store)
    labels = [d["label"] for i in client.get("/datasets").json()["items"] for d in i["domains"]]
    body = _scheme(
        f"<vocab/{slug}> skos:hasTopConcept <vocab/{slug}/ot> . <vocab/{slug}/ot> a skos:Concept ; "
        f"skos:inScheme <vocab/{slug}> ; skos:topConceptOf <vocab/{slug}> ; "
        f'skos:prefLabel "PISADO"@es .',
        uri=f"vocab/{slug}",
    )
    response = client.post("/schemes", content=body, headers=editor | TTL)
    after = [d["label"] for i in client.get("/datasets").json()["items"] for d in i["domains"]]
    assert response.status_code == 422, response.text
    assert _snapshot(loaded_store) == before
    assert after == labels


INCOHERENT_VERSIONS = [
    # Dos owl:versionIRI.
    _onto("<onto/prueba> owl:versionIRI <onto/prueba/1.0.1> ."),
    # versionIRI de otra ontología, con o sin trucos de ruta.
    _onto("").replace(b"<onto/prueba/1.0.0>", b"<onto/itot/1.0.0>"),
    _onto("").replace(b"<onto/prueba/1.0.0>", b"<onto/prueba/../itot/1.0.0>"),
    _onto("").replace(b"<onto/prueba/1.0.0>", b"<onto/prueba//1.0.0>"),
    _onto("").replace(b"<onto/prueba/1.0.0>", b"<onto/prueba/1.0.0/>"),
    _onto("").replace(b"<onto/prueba/1.0.0>", b"<onto/prueba#1.0.0>"),
    _onto("").replace(b"<onto/prueba/1.0.0>", b'"onto/prueba/1.0.0"'),
    # Versiones que no son MAYOR.MENOR.PARCHE.
    _onto("", version="1.0"),
    _onto("", version="01.0.0"),
    _onto("", version="1.0.0-rc.1"),
    _onto("", version="1.0.0+build"),
    _onto("", version="v1.0.0"),
    _onto("", version="1.0.0.0"),
    # owl:versionInfo distinto del versionIRI.
    _onto('<onto/prueba> owl:versionInfo "9.9.9" .'),
    # Versiones anteriores que no lo son, o de otra ontología.
    _onto("<onto/prueba> owl:priorVersion <onto/prueba/1.0.0> ."),
    _onto("<onto/prueba> owl:priorVersion <onto/prueba/3.0.0> ."),
    _onto("<onto/prueba> owl:priorVersion <onto/itot/0.1.0> ."),
    _onto("<onto/prueba> owl:backwardCompatibleWith <onto/itot/0.1.0> ."),
    _onto("<onto/prueba> owl:incompatibleWith <https://otro.example/onto/x/0.1.0> ."),
]


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("body", INCOHERENT_VERSIONS)
def test_incoherent_versions_are_rejected(
    client: TestClient,
    editor: dict[str, str],
    vocab_store: MemoryStore,
    session_factory: sessionmaker[Session],
    body: bytes,
) -> None:
    before = _snapshot(vocab_store)
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert _snapshot(vocab_store) == before
    assert _events(session_factory, *PUBLISH_ACTIONS) == []
    assert _metric_rows(session_factory) == []


# --- owl:imports remotos: ninguna petición de red ------------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Cualquier conexión de red desde Python falla y queda registrada."""
    attempts: list[object] = []

    def refuse(*args: object, **_kwargs: object) -> None:
        attempts.append(args)
        raise OSError("red prohibida en esta prueba")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return attempts


REMOTE_IMPORTS = [
    "http://127.0.0.1:9/no-existe.owl",
    "http://169.254.169.254/latest/meta-data/",
    "https://www.w3.org/ns/sosa/",
    "file:///etc/passwd",
    "ftp://127.0.0.1/x.owl",
    "jar:http://127.0.0.1:9/x.jar!/x.owl",
]
IMPORTS_TTL = (
    "<onto/prueba> owl:imports "
    + " , ".join(f"<{i}>" for i in REMOTE_IMPORTS)
    + " .\n:Sensor a owl:Class ; rdfs:subClassOf <http://www.w3.org/ns/sosa/Sensor> ."
)


@requires_java
@pytest.mark.parametrize("rdf_format", ["turtle", "json-ld"])
def test_remote_imports_cause_no_network_request(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    no_network: list[object],
    monkeypatch: pytest.MonkeyPatch,
    rdf_format: str,
) -> None:
    """Ni rdflib, ni pyshacl, ni owlready2 abren conexiones, y Pellet recibe un fichero
    sin ``owl:imports`` y la opción ``--ignore-imports``."""
    from owlready2 import reasoning

    commands: list[list[str]] = []
    inputs: list[str] = []
    real_run = subprocess.run

    def spy(command: list[str], *args: Any, **kwargs: Any) -> Any:
        commands.append(list(command))
        with open(command[-1], encoding="utf-8") as handle:
            inputs.append(handle.read())
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(reasoning.subprocess, "run", spy)
    body, headers = _onto(IMPORTS_TTL), TTL
    if rdf_format == "json-ld":
        graph = Graph().parse(data=body, format="turtle", publicID=BASE_URI)
        body, headers = graph.serialize(format="json-ld").encode(), LD
    response = client.post("/ontologies", content=body, headers=editor | headers)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["metrics"]["imports"] == len(REMOTE_IMPORTS)
    assert result["consistency"]["consistent"] is True
    assert result["consistency"]["includes_imports"] is False
    assert no_network == []
    assert len(commands) == 1
    assert "--ignore-imports" in commands[0]
    assert "owl#imports" not in inputs[0]
    for remote in REMOTE_IMPORTS:
        assert remote not in inputs[0]
    # Los imports declarados se conservan en el RDF publicado y en la ficha.
    stored = store.dataset.graph(URIRef(f"{PRUEBA}/1.0.0"))
    assert {str(o) for o in stored.objects(URIRef(PRUEBA), OWL.imports)} == set(REMOTE_IMPORTS)
    detail = client.get("/ontologies/prueba").json()
    assert {i["uri"] for i in detail["imports"]} == set(REMOTE_IMPORTS)
    assert all(i["known"] is False for i in detail["imports"])
    assert no_network == []


def test_imports_that_are_not_iris_are_ignored(no_network: list[object]) -> None:
    graph = ingest.parse_rdf(
        _onto('<onto/prueba> owl:imports "http://127.0.0.1:9/literal.owl" , [ rdfs:label "x" ] .'),
        "turtle",
        BASE_URI,
    )
    metrics = owl_metrics.compute_metrics(graph, PRUEBA)
    assert metrics.imports == 0
    assert (None, OWL.imports, None) not in owl_metrics.without_imports(graph)
    assert no_network == []


# --- XXE y RDF/XML ------------------------------------------------------------------------

XXE = (
    b'<?xml version="1.0"?>\n<!DOCTYPE rdf:RDF [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> '
    b'<!ENTITY remoto SYSTEM "http://127.0.0.1:9/xxe"> ]>\n'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    b'xmlns:owl="http://www.w3.org/2002/07/owl#" xmlns:dct="http://purl.org/dc/terms/">'
    b'<owl:Ontology rdf:about="https://semantic.example.org/itot/onto/prueba">'
    b"<dct:title>&xxe;&remoto;</dct:title></owl:Ontology></rdf:RDF>"
)


@pytest.mark.parametrize("path", ["/ontologies", "/schemes"])
@pytest.mark.parametrize(
    "content_type",
    ["application/rdf+xml", "application/xml", "text/xml", "application/owl+xml", "text/html"],
)
def test_xml_is_not_an_ingest_format(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    no_network: list[object],
    path: str,
    content_type: str,
) -> None:
    """La ingesta no acepta RDF/XML: no hay analizador XML que atacar con entidades."""
    response = client.post(path, content=XXE, headers=editor | {"Content-Type": content_type})
    assert response.status_code == 415, response.text
    assert "root:" not in response.text
    assert store.graph_names() == set()
    assert no_network == []


@pytest.mark.parametrize("path", ["/ontologies", "/schemes"])
@pytest.mark.parametrize("headers", [TTL, LD])
def test_xml_sent_as_turtle_or_jsonld_is_a_syntax_error(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    no_network: list[object],
    path: str,
    headers: dict[str, str],
) -> None:
    response = client.post(path, content=XXE, headers=editor | headers)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "syntax"
    assert "root:" not in response.text
    assert store.graph_names() == set()
    assert no_network == []


def test_rdfxml_output_escapes_stored_markup(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    """El RDF/XML servido escapa el contenido: una entidad guardada no se interpreta."""
    hostile = '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>&e;</rdf:RDF><script>'
    escaped = hostile.replace('"', '\\"')
    body = _scheme(CONCEPT + f'; skos:definition "{escaped}"@es .')
    assert client.post("/schemes", content=body, headers=editor | TTL).status_code == 201
    response = client.get("/schemes/prueba/rdf", params={"format": "rdfxml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(RDFXML)
    assert "<!DOCTYPE" not in response.text and "<script>" not in response.text
    parsed = Graph().parse(data=response.text, format="xml")
    assert Literal(hostile, lang="es") in set(parsed.objects(None, SKOS.definition))


# --- Bombas de expansión --------------------------------------------------------------------


def _peak_bytes(data: bytes, rdf_format: ingest.RdfFormat) -> int:
    tracemalloc.start()
    try:
        ingest.parse_rdf(data, rdf_format, BASE_URI)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


LONG_PREFIX = "http://x.example/" + "a" * 100_000 + "/"
BOMB_TURTLE = (
    f"@prefix p: <{LONG_PREFIX}> .\n" + "\n".join(f"p:s{i} p:p p:o{i} ." for i in range(200))
).encode()
BOMB_JSONLD = json.dumps(
    {
        "@context": {"p": LONG_PREFIX},
        "@graph": [{"@id": f"p:s{i}", "p:p": {"@id": f"p:o{i}"}} for i in range(200)],
    }
).encode()


@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-03: un prefijo largo repetido expande ~100 KB de RDF a ~60 MB en memoria "
    "(x590); con el límite de 10 MB de la ingesta son varios órdenes de magnitud más",
)
@pytest.mark.parametrize(
    ("data", "rdf_format"), [(BOMB_TURTLE, "turtle"), (BOMB_JSONLD, "json-ld")]
)
def test_prefix_expansion_is_bounded(data: bytes, rdf_format: ingest.RdfFormat) -> None:
    """Un documento pequeño no puede ocupar cientos de veces su tamaño al analizarlo: o
    se rechaza (IRIs desmesuradas) o la memoria se mantiene proporcional a la entrada."""
    assert len(data) < 120_000
    try:
        peak = _peak_bytes(data, rdf_format)
    except ingest.IngestError:
        return
    assert peak < 50 * len(data), f"{len(data)} bytes de entrada, {peak} bytes de pico"


def test_body_over_the_limit_is_rejected_before_parsing(
    client: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no debe analizarse un cuerpo que supera el límite")

    monkeypatch.setattr(ingest, "parse_rdf", fail)
    big = b"# " + b"a" * settings.ingest_max_bytes
    for path in ("/ontologies", "/schemes"):
        for headers in (TTL, LD):
            response = client.post(path, content=big, headers=editor | headers)
            assert response.status_code == 413, response.text
    assert store.graph_names() == set()


# --- Tokens y roles -------------------------------------------------------------------------


def _claims(user: User, **extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        **extra,
    }


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize(
    ("path", "body"), [("/ontologies", _onto("")), ("/schemes", _scheme(CONCEPT + "."))]
)
def test_forged_tokens_cannot_publish(
    client: TestClient,
    settings: Settings,
    store: MemoryStore,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
    path: str,
    body: bytes,
) -> None:
    member = make_user("miembro", Role.MIEMBRO)
    editor_user = make_user("editora", Role.EDITOR)
    inactive = make_user("baja", Role.EDITOR, is_active=False)
    good = login("editora")["Authorization"].removeprefix("Bearer ")
    head, payload, signature = good.split(".")
    now = int(datetime.now(UTC).timestamp())
    forged = {
        "sin token": None,
        "firma de otro secreto": jwt.encode(_claims(editor_user), "x" * 40, algorithm="HS256"),
        "firma truncada": f"{head}.{payload}.{signature[:-4]}",
        "sin firma": f"{head}.{payload}.",
        "caducado": jwt.encode(
            _claims(editor_user, exp=now - 60), settings.jwt_secret, algorithm="HS256"
        ),
        "miembro que se sube el rol": jwt.encode(
            _claims(member) | {"role": "editor"}, "x" * 40, algorithm="HS256"
        ),
        "cuenta de baja": jwt.encode(_claims(inactive), settings.jwt_secret, algorithm="HS256"),
        "otro algoritmo": jwt.encode(_claims(editor_user), settings.jwt_secret, algorithm="HS512"),
        "basura": "no.es.un-jwt",
    }
    for name, token in forged.items():
        headers = dict(TTL)
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        response = client.post(path, content=body, headers=headers)
        assert response.status_code == 401, f"{name}: {response.status_code} {response.text}"
    # Un miembro auténtico: 403. El rol del token no cuenta, cuenta el de la base de datos.
    claimed = jwt.encode(
        _claims(member) | {"role": "admin"}, settings.jwt_secret, algorithm="HS256"
    )
    for token in (login("miembro")["Authorization"].removeprefix("Bearer "), claimed):
        response = client.post(
            path, content=body, headers=TTL | {"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403, response.text
    assert store.graph_names() == set()
    assert _events(session_factory, *PUBLISH_ACTIONS) == []
    # Y el editor auténtico sí publica.
    assert (
        client.post(
            path, content=body, headers=TTL | {"Authorization": f"Bearer {good}"}
        ).status_code
        == 201
    )


@pytest.mark.usefixtures("fake_reasoner")
def test_publish_is_audited_without_content_or_secrets(
    client: TestClient,
    settings: Settings,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    user = make_user("editora", Role.EDITOR)
    headers = login("editora")
    marker = "CONTENIDO-QUE-NO-VA-A-LA-AUDITORIA"
    onto = _onto(f':A a owl:Class ; rdfs:comment "{marker}"@es .')
    scheme = _scheme(CONCEPT + f'; skos:definition "{marker}"@es .')
    assert client.post("/ontologies", content=onto, headers=headers | TTL).status_code == 201
    assert client.post("/schemes", content=scheme, headers=headers | TTL).status_code == 201
    # Un rechazo no se audita.
    assert (
        client.post(
            "/ontologies", content=_onto("", version="1.0"), headers=headers | TTL
        ).status_code
        == 422
    )
    assert (
        client.post("/schemes", content=b"no es turtle", headers=headers | TTL).status_code == 422
    )
    events = _events(session_factory, *PUBLISH_ACTIONS)
    assert sorted(e.action for e in events) == sorted(PUBLISH_ACTIONS)
    token = headers["Authorization"].removeprefix("Bearer ")
    for event in events:
        assert event.actor_id == user.id
        assert event.actor_username == "editora"
        assert event.details["via"] == "api"
        assert event.details["created"] is True
        text = json.dumps(event.details, ensure_ascii=False)
        for secret in (marker, token, settings.jwt_secret, "contrasena"):
            assert secret not in text
    by_action = {e.action: e.details for e in events}
    assert by_action[AuditAction.ONTOLOGY_PUBLISHED]["graph"] == f"{PRUEBA}/1.0.0"
    assert by_action[AuditAction.SCHEME_PUBLISHED]["graph"] == f"{BASE_URI}vocab/prueba"


# --- 3. Pellet y Java -----------------------------------------------------------------------


def hard_ontology(n: int = 22) -> bytes:
    """Ontología pequeña y costosa para un razonador de tableau: ``n`` sucesores que hay
    que fundir bajo una cardinalidad máxima, con disyunciones y clases disjuntas."""
    lines = [":r a owl:ObjectProperty ."]
    for i in range(n):
        lines.append(f":p{i} a owl:ObjectProperty ; rdfs:subPropertyOf :r .")
        lines.append(f":C{i} a owl:Class . :D{i} a owl:Class .")
    members = " ".join(
        f"[ a owl:Restriction ; owl:onProperty :p{i} ; "
        f"owl:someValuesFrom [ a owl:Class ; owl:unionOf ( :C{i} :D{i} ) ] ]"
        for i in range(n)
    )
    lines.append(
        f":X a owl:Class ; rdfs:subClassOf [ a owl:Class ; owl:intersectionOf ( {members} "
        f"[ a owl:Restriction ; owl:onProperty :r ; "
        f'owl:maxCardinality "{n // 2}"^^<{XSD_NS}nonNegativeInteger> ] ) ] .'
    )
    for i in range(n):
        for j in range(i + 1, n):
            lines.append(
                f":C{i} owl:disjointWith :C{j} , :D{j} . :D{i} owl:disjointWith :D{j} , :C{j} ."
            )
    lines.append(":x a :X .")
    return _onto("\n".join(lines))


def _pellet_processes() -> list[str]:
    if shutil.which("pgrep") is None:
        return []
    found = subprocess.run(
        ["pgrep", "-fl", "pellet.Pellet"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in found.stdout.splitlines() if "pgrep" not in line]


@pytest.fixture
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> float:
    """``REASONER_TIMEOUT_SECONDS`` corto. Debe pedirse antes que ``client``."""
    monkeypatch.setenv("REASONER_TIMEOUT_SECONDS", "3")
    return 3.0


@requires_java
def test_hung_reasoner_is_killed_and_the_service_keeps_working(
    short_timeout: float,
    client: TestClient,
    settings: Settings,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
) -> None:
    assert settings.reasoner_timeout_seconds == short_timeout
    body = hard_ontology()
    assert len(body) < 100_000
    start = time.monotonic()
    response = client.post("/ontologies", content=body, headers=editor | TTL)
    elapsed = time.monotonic() - start
    # La publicación no se bloquea: se guarda con la consistencia «no disponible».
    assert response.status_code == 201, response.text
    consistency = response.json()["consistency"]
    assert consistency["consistent"] is None
    assert consistency["unsatisfiable_classes"] is None
    assert "tiempo" in consistency["detail"]
    assert elapsed < short_timeout + 20, f"tardó {elapsed:.1f} s con un límite de {short_timeout} s"
    assert _pellet_processes() == [], "el proceso Java de Pellet sigue vivo tras el timeout"
    assert f"{PRUEBA}/1.0.0" in store.graph_names()
    assert _metric_rows(session_factory) == [f"{PRUEBA}/1.0.0"]
    # La ficha se sirve y el razonador sigue disponible para la siguiente ingesta.
    detail = client.get("/ontologies/prueba")
    assert detail.status_code == 200
    assert detail.json()["consistency"]["consistent"] is None
    simple = _onto(":A a owl:Class .", version="1.0.1")
    after = client.post("/ontologies", content=simple, headers=editor | TTL)
    assert after.status_code == 201, after.text
    assert after.json()["consistency"]["consistent"] is True
    assert client.get("/health").status_code == 200


REASONER_OUTCOMES = {
    "consistente": (":A a owl:Class .", 60.0),
    "inconsistente": (":A a owl:Class ; owl:equivalentClass owl:Nothing . :i a :A .", 60.0),
    "fallo de Pellet": (None, 60.0),  # se rellena con PELLET_CRASHES
    "tiempo agotado": (None, 2.0),  # se rellena con hard_ontology()
}


def _reasoner_leftovers(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Ficheros que quedan en el directorio temporal tras razonar."""
    body, timeout = REASONER_OUTCOMES[name]
    if name == "fallo de Pellet":
        data = _onto(PELLET_CRASHES["lista cíclica"])
    elif name == "tiempo agotado":
        data = hard_ontology()
    else:
        data = _onto(body or "")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    graph = ingest.parse_rdf(data, "turtle", BASE_URI)
    result = owl_metrics.check_consistency(
        graph, PRUEBA, timeout_seconds=timeout, java_memory_mb=512
    )
    expected = {"consistente": True, "inconsistente": False}.get(name)
    assert result.consistent is expected, result
    return sorted(p.name for p in tmp_path.iterdir())


@requires_java
def test_reasoner_leaves_no_temporary_file_when_it_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _reasoner_leftovers("consistente", tmp_path, monkeypatch) == []


@requires_java
@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-07: owlready2 solo borra el fichero temporal que pasa a Pellet cuando el "
    "razonamiento termina bien. Si la ontología es inconsistente, Pellet falla o se agota el "
    "tiempo, queda en /tmp una copia en N-Triples de la ontología en cada ingesta",
)
@pytest.mark.parametrize("name", ["inconsistente", "fallo de Pellet", "tiempo agotado"])
def test_reasoner_leaves_no_temporary_file_when_it_fails(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _reasoner_leftovers(name, tmp_path, monkeypatch) == []


def test_reasoner_timeout_has_an_upper_bound() -> None:
    field = Settings.model_fields["reasoner_timeout_seconds"]
    assert field.default == 120
    limits = {type(m).__name__: m for m in field.metadata}
    assert limits["Le"].le <= 3600 and limits["Gt"].gt == 0


# Entradas que hacen fallar a Pellet (bucle en una lista RDF, restricción mal formada).
PELLET_CRASHES = {
    "lista cíclica": f":A a owl:Class ; owl:unionOf _:l . _:l <{RDF_NS}first> :B ; "
    f"<{RDF_NS}rest> _:l . :B a owl:Class .",
    "restricción sobre un literal": ":A a owl:Class ; rdfs:subClassOf [ a owl:Restriction ; "
    'owl:onProperty "x" ; owl:someValuesFrom :B ] .',
    "clave y cadena vacías": ":A a owl:Class ; owl:hasKey ( ) . :p a owl:ObjectProperty ; "
    "owl:propertyChainAxiom ( ) ; owl:inverseOf :p .",
}


@requires_java
@pytest.mark.parametrize("name", list(PELLET_CRASHES))
def test_reasoner_failure_does_not_break_the_service(
    quiet: TestClient, editor: dict[str, str], store: MemoryStore, name: str
) -> None:
    response = quiet.post("/ontologies", content=_onto(PELLET_CRASHES[name]), headers=editor | TTL)
    assert response.status_code == 201, response.text
    consistency = response.json()["consistency"]
    assert consistency["consistent"] in (None, True, False)
    assert _pellet_processes() == []
    assert quiet.get("/ontologies/prueba").status_code == 200
    assert quiet.get("/vocabularies").status_code == 200
    ok = quiet.post(
        "/ontologies", content=_onto(":A a owl:Class .", version="1.0.1"), headers=editor | TTL
    )
    assert ok.status_code == 201 and ok.json()["consistency"]["consistent"] is True


def _leaks(detail: str | None) -> list[str]:
    """Fragmentos de traza de Java o rutas del sistema de ficheros en el detalle."""
    if not detail:
        return []
    markers = [
        "\tat ",
        ".java:",
        "Exception",
        "/tmp/",  # noqa: S108
        "/var/",
        "/Users/",
        "/home/",
        "/app/",
        "site-packages",
    ]
    return [m for m in markers if m in detail]


@requires_java
@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-02: cuando Pellet falla, consistency.detail publica una línea de la traza "
    "de Java ('\\tat org.mindswap.pellet…(DefaultGraphLoader.java:339)') en la respuesta y "
    "en la ficha pública de la ontología",
)
@pytest.mark.parametrize("name", ["lista cíclica", "restricción sobre un literal"])
def test_reasoner_failure_detail_has_no_stack_trace(
    quiet: TestClient, editor: dict[str, str], name: str
) -> None:
    response = quiet.post("/ontologies", content=_onto(PELLET_CRASHES[name]), headers=editor | TTL)
    assert response.status_code == 201, response.text
    public = quiet.get("/ontologies/prueba").json()["consistency"]["detail"]
    assert _leaks(response.json()["consistency"]["detail"]) == []
    assert _leaks(public) == []


def test_reasoner_error_message_is_reduced_to_one_short_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un error de Java con rutas y traza: al detalle no llega ni la ruta del fichero
    temporal ni más de una línea."""
    import owlready2

    trace = (
        "Java error message is:\nException in thread main java.io.FileNotFoundException: "
        "/tmp/tmpabc123 (No such file)\n\tat pellet.Pellet.main(Pellet.java:59)\n"
        "Caused by: /opt/venv/lib/python3.15/site-packages/owlready2/pellet/x.jar\n"
        "Use -v for detail."
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise owlready2.OwlReadyJavaError(trace)

    monkeypatch.setattr(owl_metrics, "java_available", lambda: True)
    monkeypatch.setattr(owlready2, "sync_reasoner_pellet", boom)
    graph = ingest.parse_rdf(_onto(":A a owl:Class ."), "turtle", BASE_URI)
    result = owl_metrics.check_consistency(graph, PRUEBA, timeout_seconds=5, java_memory_mb=256)
    assert result.consistent is None
    assert result.detail is not None and "\n" not in result.detail
    assert len(result.detail) < 350
    for leaked in ("tmpabc123", "site-packages", "FileNotFoundException"):
        assert leaked not in result.detail


@pytest.mark.parametrize(
    "error",
    [RuntimeError("fallo inesperado en /opt/venv/lib/owlready2"), ValueError("salida ilegible")],
)
@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-01: check_consistency solo captura OwlReadyJavaError, OSError y el timeout; "
    "cualquier otra excepción de owlready2 al razonar acaba en un 500",
)
def test_unexpected_reasoner_exception_is_not_a_500(
    quiet: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    import owlready2

    def boom(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(owl_metrics, "java_available", lambda: True)
    monkeypatch.setattr(owlready2, "sync_reasoner_pellet", boom)
    response = quiet.post("/ontologies", content=_onto(":A a owl:Class ."), headers=editor | TTL)
    assert response.status_code == 201, response.text
    assert response.json()["consistency"]["consistent"] is None
    assert "/opt/venv" not in response.text


# RDF válido que owlready2 no sabe cargar (el cálculo de métricas lanza una excepción).
UNLOADABLE = {
    "literal mal tipado": ":p a owl:DatatypeProperty . :i a owl:NamedIndividual ; "
    f':p "abc"^^<{XSD_NS}integer> .',
    "decimal mal tipado": f':A a owl:Class ; rdfs:comment "x"^^<{XSD_NS}decimal> .',
}


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.xfail(
    strict=True,
    reason='QA-G3-01: un literal mal tipado (p. ej. "abc"^^xsd:integer) pasa la validación y '
    "owlready2 lanza OwlReadyOntologyParsingError al calcular las métricas: POST /ontologies "
    "responde 500 en lugar de 422 o de publicar sin métricas",
)
@pytest.mark.parametrize("name", list(UNLOADABLE))
def test_ontology_that_owlready2_cannot_load_is_not_a_500(
    quiet: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    name: str,
) -> None:
    response = quiet.post("/ontologies", content=_onto(UNLOADABLE[name]), headers=editor | TTL)
    assert response.status_code in (201, 422), f"{response.status_code}: {response.text}"
    if response.status_code == 422:
        assert store.graph_names() == set()
        assert _events(session_factory, *PUBLISH_ACTIONS) == []


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("name", list(UNLOADABLE))
def test_unloadable_ontology_leaves_nothing_behind(
    quiet: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    name: str,
) -> None:
    """Pase lo que pase con QA-G3-01: un fallo no deja ni grafo, ni métricas, ni auditoría a
    medias, no filtra la traza y la siguiente ingesta funciona."""
    response = quiet.post("/ontologies", content=_onto(UNLOADABLE[name]), headers=editor | TTL)
    if response.status_code != 201:
        assert store.graph_names() == set()
        assert _metric_rows(session_factory) == []
        assert _events(session_factory, *PUBLISH_ACTIONS) == []
    assert "Traceback" not in response.text and "owlready2" not in response.text
    ok = quiet.post(
        "/ontologies", content=_onto(":A a owl:Class .", version="1.0.1"), headers=editor | TTL
    )
    assert ok.status_code == 201, ok.text


# --- 4. Lectura pública: solo los grafos publicados ----------------------------------------

SECRET = "SECRETO-NO-PUBLICADO"


def _turtle(body: str) -> Graph:
    prefixes = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> . "
        "@prefix dct: <http://purl.org/dc/terms/> . "
        "@prefix dcat: <http://www.w3.org/ns/dcat#> . "
        "@prefix vann: <http://purl.org/vocab/vann/> . "
    )
    return Graph().parse(data=prefixes + body, format="turtle", publicID=BASE_URI)


def _secret_ontology(slug: str, version: str = "1.0.0") -> str:
    return (
        f"<onto/{slug}> a owl:Ontology ; owl:versionIRI <onto/{slug}/{version}> ; "
        f'owl:versionInfo "{version}" ; dct:title "{SECRET}"@es ; '
        f'vann:preferredNamespacePrefix "{SECRET}" ; dct:subject <vocab/ot/modbus-tcp> . '
        f'<onto/{slug}#Clase> a owl:Class ; skos:prefLabel "{SECRET}"@es . '
    )


def _secret_scheme(uri: str) -> str:
    return (
        f'<{uri}> a skos:ConceptScheme ; skos:prefLabel "{SECRET}"@es ; dct:title "{SECRET}"@es ; '
        f'dct:subject <vocab/dominio/ot> ; owl:versionInfo "1.0" ; skos:hasTopConcept <{uri}/c> . '
        f"<{uri}/c> a skos:Concept ; skos:inScheme <{uri}> ; skos:topConceptOf <{uri}> ; "
        f'skos:prefLabel "{SECRET}"@es ; skos:related <vocab/ot/modbus-tcp> . '
        # Etiquetas falsas para recursos publicados, que no deben imponerse a las reales.
        f'<vocab/ot/modbus-tcp> skos:prefLabel "{SECRET}"@es ; skos:altLabel "{SECRET}"@es ; '
        f"skos:inScheme <{uri}> ; skos:related <{uri}/c> . "
        f'<vocab/dominio/ot> skos:prefLabel "{SECRET}"@es ; skos:inScheme <vocab/dominio> . '
        f'<vocab/ot> skos:prefLabel "{SECRET}"@es ; dct:title "{SECRET}"@es . '
    )


# Grafos que nadie ha publicado por la API ni por load-semantic.
UNPUBLISHED = {
    # Fuera de BASE_URI y en rutas que no son de ningún recurso.
    "urn:x:privado": _secret_ontology("secreta") + _secret_scheme("vocab/secreto"),
    f"{BASE_URI}privado/borrador": _secret_ontology("secreta-b")
    + _secret_scheme("vocab/secreto-b"),
    # El grafo no es el versionIRI de la ontología que contiene.
    f"{BASE_URI}onto/secreta-c": _secret_ontology("secreta-c"),
    f"{BASE_URI}onto/secreta-d/2.0.0": _secret_ontology("secreta-d", "1.0.0"),
    f"{BASE_URI}onto/itot/7.0.0": _secret_ontology("otra", "7.0.0"),
    # El grafo no es la URI del esquema que contiene.
    f"{BASE_URI}vocab/secreto-e": _secret_scheme("vocab/secreto-f"),
    f"{BASE_URI}vocab/corp/secreto-g/": _secret_scheme("vocab/corp/secreto-g"),
    f"{BASE_URI}vocab/": _secret_scheme("vocab/secreto-h"),
    # Externas en un grafo que no es onto/externas.
    f"{BASE_URI}onto/externas-borrador": (
        f'<https://externa.example/onto> a owl:Ontology ; dct:title "{SECRET}"@es . '
    ),
    # Un esquema guardado bajo dataset/ y una serie bajo vocab/.
    f"{BASE_URI}dataset/secreto-i": _secret_scheme("dataset/secreto-i"),
    f"{BASE_URI}vocab/secreto-j": (
        f'<vocab/secreto-j> a dcat:DatasetSeries ; dct:title "{SECRET}"@es . '
        f"<vocab/secreto-j/1.0.0> a dcat:Dataset ; dcat:inSeries <vocab/secreto-j> ; "
        f'dcat:version "1.0.0" ; dct:title "{SECRET}"@es ; dcat:theme <vocab/ot/modbus-tcp> ; '
        f"dct:conformsTo <onto/itot> , <onto/itot/1.2.0> . "
    ),
}

HIDDEN_PATHS = [
    "/ontologies/secreta",
    "/ontologies/secreta-b",
    "/ontologies/secreta-c",
    "/ontologies/secreta-d",
    "/ontologies/secreta-d?version=1.0.0",
    "/ontologies/secreta-d?version=2.0.0",
    "/ontologies/otra",
    "/ontologies/itot?version=7.0.0",
    "/ontologies/itot/rdf?version=7.0.0",
    "/ontologies/externas",
    "/ontologies/externas-borrador",
    "/schemes/secreto",
    "/schemes/secreto-b",
    "/schemes/secreto-e",
    "/schemes/secreto-f",
    "/schemes/secreto-h",
    "/schemes/secreto-j",
    "/schemes/corp/secreto-g",
    "/schemes/secreto/concepts/c",
    "/schemes/secreto-f/concepts/c",
    "/schemes/corp/secreto-g/concepts/c",
    "/schemes/secreto-e/rdf",
    "/onto/secreta",
    "/onto/secreta-c",
    "/onto/secreta-d/2.0.0",
    "/onto/itot/7.0.0",
    "/onto/externas",
    "/vocab/secreto",
    "/vocab/secreto-e",
    "/vocab/secreto-f/c",
    "/vocab/corp/secreto-g",
    "/vocab/corp/secreto-g/c",
    "/datasets/secreto-i",
    "/datasets/secreto-j",
]

VISIBLE_PATHS = [
    "/vocabularies",
    "/vocabularies?kind=own",
    "/vocabularies?kind=external",
    "/vocabularies?kind=skos_corp",
    "/vocabularies?kind=skos_domain",
    "/vocabularies?domain=ot",
    f"/vocabularies?q={SECRET}",
    "/ontologies/itot",
    "/ontologies/itot?version=1.0.0",
    "/ontologies/itot/rdf",
    "/ontologies/itot/rdf?format=rdfxml",
    "/ontologies/itot/rdf?format=jsonld",
    "/ontologies/pqcm",
    "/ontologies/didx",
    "/schemes/ot",
    "/schemes/ot/rdf",
    "/schemes/ot/concepts/modbus-tcp",
    "/schemes/ot/concepts/purdue-nivel-1",
    "/schemes/corp/trl",
    "/schemes/corp/trl/concepts/trl-1",
    "/schemes/dominio",
    "/schemes/dominio/concepts/ot",
    "/onto/itot",
    "/onto/itot/1.2.0",
    "/vocab/ot",
    "/vocab/ot/modbus-tcp",
    "/vocab/dominio/ot",
    "/datasets",
    "/datasets?domain=ot",
    "/datasets/modbus-tcp-testbed",
    "/datasets/modbus-tcp-testbed/rdf",
]


@pytest.fixture
def with_unpublished(api: TestClient, vocab_store: MemoryStore) -> dict[str, Any]:
    """Respuestas públicas antes de plantar los grafos sin publicar, y los grafos ya
    plantados (también en el grafo por defecto)."""
    before = {path: api.get(path, headers={"Accept": TURTLE}).text for path in VISIBLE_PATHS}
    for name, body in UNPUBLISHED.items():
        target = vocab_store.dataset.graph(URIRef(name))
        for triple in _turtle(body):
            target.add(triple)
    default = _turtle(_secret_ontology("secreta-z") + _secret_scheme("vocab/secreto-z"))
    for triple in default:
        vocab_store.dataset.default_graph.add(triple)
    vocab_store.queries.clear()
    return before


def test_unpublished_graphs_are_not_resolvable(
    api: TestClient, with_unpublished: dict[str, Any]
) -> None:
    for path in HIDDEN_PATHS:
        response = api.get(path, headers={"Accept": TURTLE})
        assert response.status_code == 404, f"{path}: {response.status_code} {response.text[:200]}"
        assert SECRET not in response.text


def test_unpublished_graphs_do_not_change_public_reads(
    api: TestClient, with_unpublished: dict[str, Any], vocab_store: MemoryStore
) -> None:
    for path, expected in with_unpublished.items():
        response = api.get(path, headers={"Accept": TURTLE})
        assert response.status_code == 200, path
        assert SECRET not in response.text, path
        if response.headers["content-type"].startswith("application/json"):
            assert response.json() == json.loads(expected), path
    _assert_only_fixed_queries(vocab_store)


def test_counts_ignore_unpublished_graphs(
    api: TestClient, with_unpublished: dict[str, Any]
) -> None:
    page = api.get("/vocabularies").json()
    assert page["counts"] == {"own": 3, "external": 3, "skos_corp": 4, "skos_domain": 5}
    assert page["total"] == 15
    concept = api.get("/schemes/ot/concepts/modbus-tcp").json()
    assert [d["slug"] for d in concept["used_by"]["datasets"]] == ["modbus-tcp-testbed"]
    assert {o["slug"] for o in concept["used_by"]["ontologies"]} <= {"itot", "pqcm", "didx"}
    used = api.get("/ontologies/itot").json()["used_by_datasets"]
    assert "secreto-j" not in {u["slug"] for u in used}


# --- 5. Content-Disposition -----------------------------------------------------------------

SAFE_DISPOSITION = r'attachment; filename="[a-z0-9]+(?:[.-][a-z0-9]+)*\.(?:ttl|jsonld|rdf)"'

HOSTILE_PARTS = [
    '1.0"\r\nSet-Cookie: a=b',
    "1.0\r\nX-Inyectada: 1",
    "1.0\n",
    '1.0"; filename="evil.exe',
    "../../etc/passwd",
    "..",
    ".",
    ".oculto",
    "1..0",
    "1.0.",
    "-1.0",
    "a/b",
    "a\\b",
    "C:\\windows\\system32",
    "1.0%0d%0aX: 1",
    "1.0\x00.exe",
    "versión",
    "1.0 final",
    "",
    "A" * 5,
]


@pytest.mark.parametrize("hostile", HOSTILE_PARTS)
@pytest.mark.parametrize("media", [TURTLE, JSONLD, RDFXML, "text/html"])
def test_download_filename_drops_unsafe_parts(hostile: str, media: str) -> None:
    import re

    name = downloads.filename(["itot", hostile], media)
    assert re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.(?:ttl|jsonld|rdf|txt)", name), name
    assert name.startswith("itot.")
    only = downloads.filename([hostile, None], media)
    assert only.startswith("rdf."), only


@pytest.mark.parametrize("hostile", [h for h in HOSTILE_PARTS if h and "\x00" not in h])
def test_content_disposition_ignores_hostile_stored_versions(
    api: TestClient, vocab_store: MemoryStore, uris: Uris, hostile: str
) -> None:
    """Versiones hostiles guardadas en el triplestore (sin pasar por la ingesta): la
    cabecera solo lleva el slug."""
    import re

    scheme = URIRef(uris.scheme("ot"))
    graph = vocab_store.dataset.graph(scheme)
    graph.remove((scheme, OWL.versionInfo, None))
    graph.add((scheme, OWL.versionInfo, Literal(hostile)))
    series = URIRef(uris.series("modbus-tcp-testbed"))
    series_graph = vocab_store.dataset.graph(series)
    for version in list(series_graph.subjects(DCAT.inSeries, series)):
        series_graph.remove((version, DCAT.version, None))
        series_graph.add((version, DCAT.version, Literal(hostile)))
    for path, expected in (
        ("/schemes/ot/rdf", "ot"),
        ("/datasets/modbus-tcp-testbed/rdf", "modbus-tcp-testbed"),
    ):
        for fmt, ext in (("turtle", "ttl"), ("jsonld", "jsonld")):
            response = api.get(path, params={"format": fmt, "download": "1"})
            assert response.status_code == 200, response.text
            header = response.headers["content-disposition"]
            assert header == f'attachment; filename="{expected}.{ext}"'
            assert re.fullmatch(SAFE_DISPOSITION, header)
            for name, value in response.headers.items():
                assert "\r" not in value and "\n" not in value, name
            assert "set-cookie" not in response.headers
            assert "x-inyectada" not in response.headers


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("/ontologies/itot/rdf", "itot-1.2.0"),
        ("/ontologies/itot/rdf?version=1.0.0", "itot-1.0.0"),
        ("/ontologies/pqcm/rdf", "pqcm-0.4.0"),
        ("/schemes/ot/rdf", "ot-1.0"),
        ("/schemes/corp/trl/rdf", "corp-trl-1.0"),
        ("/schemes/corp/financiacion/rdf", "corp-financiacion-2026.1"),
        ("/datasets/modbus-tcp-testbed/rdf", "modbus-tcp-testbed-2.1.0"),
        ("/datasets/modbus-tcp-testbed/rdf?version=1.0.0", "modbus-tcp-testbed-1.0.0"),
    ],
)
def test_content_disposition_only_with_download(api: TestClient, path: str, name: str) -> None:
    import re

    sep = "&" if "?" in path else "?"
    formats = [("turtle", "ttl"), ("jsonld", "jsonld")]
    if not path.startswith("/datasets"):
        formats.append(("rdfxml", "rdf"))
    for fmt, ext in formats:
        inline = api.get(f"{path}{sep}format={fmt}")
        assert inline.status_code == 200
        assert "content-disposition" not in inline.headers
        for flag in ("1", "true"):
            response = api.get(f"{path}{sep}format={fmt}&download={flag}")
            header = response.headers["content-disposition"]
            assert header == f'attachment; filename="{name}.{ext}"'
            assert re.fullmatch(SAFE_DISPOSITION, header)
        off = api.get(f"{path}{sep}format={fmt}&download=0")
        assert "content-disposition" not in off.headers


def test_persistent_uris_never_send_content_disposition(api: TestClient) -> None:
    for path in (
        "/onto/itot",
        "/onto/itot/1.2.0",
        "/vocab/ot",
        "/vocab/corp/trl",
        "/vocab/ot/modbus-tcp",
    ):
        response = api.get(path, params={"download": "1"}, headers={"Accept": TURTLE})
        assert response.status_code == 200
        assert "content-disposition" not in response.headers


# --- 6. Contenido guardado que no debe romper la lectura -----------------------------------


def _chain(depth: int) -> bytes:
    lines = [
        "<vocab/prueba> skos:hasTopConcept <vocab/prueba/c0> .",
        "<vocab/prueba/c0> a skos:Concept ; skos:inScheme <vocab/prueba> ; "
        'skos:topConceptOf <vocab/prueba> ; skos:prefLabel "c0"@es .',
    ]
    lines += [
        f"<vocab/prueba/c{i}> a skos:Concept ; skos:inScheme <vocab/prueba> ; "
        f'skos:broader <vocab/prueba/c{i - 1}> ; skos:prefLabel "c{i}"@es .'
        for i in range(1, depth)
    ]
    return _scheme("\n".join(lines))


@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-04: un esquema con una jerarquía skos:broader de unos 300 niveles se admite "
    "y después GET /schemes/{slug} responde 500 (profundidad de serialización del árbol)",
)
def test_deep_concept_hierarchy_does_not_break_the_scheme(
    quiet: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    response = quiet.post("/schemes", content=_chain(300), headers=editor | TTL)
    if response.status_code == 422:  # rechazarla también es una corrección válida
        assert store.graph_names() == set()
        return
    assert response.status_code == 201, response.text
    assert quiet.get("/schemes/prueba").status_code == 200
    assert quiet.get("/schemes/prueba/concepts/c299").status_code == 200


def test_moderate_concept_hierarchy_is_served(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    assert client.post("/schemes", content=_chain(40), headers=editor | TTL).status_code == 201
    tree = client.get("/schemes/prueba").json()["tree"]
    depth, node = 0, tree[0]
    while node["children"]:
        depth, node = depth + 1, node["children"][0]
    assert depth == 39
    leaf = client.get("/schemes/prueba/concepts/c39").json()
    assert [b["uri"] for b in leaf["broader"]] == [f"{BASE_URI}vocab/prueba/c38"]


@pytest.mark.parametrize(
    "body",
    [
        # Ciclo de dos conceptos, concepto que es su propio padre y ciclo con raíz.
        '<vocab/prueba/a> a skos:Concept ; skos:inScheme <vocab/prueba> ; skos:prefLabel "a"@es ; '
        "skos:broader <vocab/prueba/b> . <vocab/prueba/b> a skos:Concept ; "
        'skos:inScheme <vocab/prueba> ; skos:prefLabel "b"@es ; skos:broader <vocab/prueba/a> .',
        '<vocab/prueba/a> a skos:Concept ; skos:inScheme <vocab/prueba> ; skos:prefLabel "a"@es ; '
        "skos:broader <vocab/prueba/a> ; skos:narrower <vocab/prueba/a> ; "
        "skos:related <vocab/prueba/a> .",
        CONCEPT + "; skos:broader <vocab/prueba/b> . <vocab/prueba/b> a skos:Concept ; "
        'skos:inScheme <vocab/prueba> ; skos:prefLabel "b"@es ; skos:broader <vocab/prueba/c> .',
    ],
)
def test_cyclic_hierarchies_do_not_hang_or_break_reads(
    quiet: TestClient, editor: dict[str, str], store: MemoryStore, body: str
) -> None:
    response = quiet.post("/schemes", content=_scheme(body), headers=editor | TTL)
    assert response.status_code in (201, 422), response.text
    if response.status_code == 201:
        assert quiet.get("/schemes/prueba").status_code == 200
        for slug in ("a", "b", "c"):
            assert quiet.get(f"/schemes/prueba/concepts/{slug}").status_code in (200, 404)
        assert quiet.get("/vocabularies").status_code == 200
        assert quiet.get("/vocab/prueba", headers={"Accept": TURTLE}).status_code == 200


# Predicados que RDF/XML no puede escribir como nombre de elemento.
UNSPLITTABLE = ["http://x.example/p/1", "http://x.example/p/", "http://x.example/2024", "urn:x:1"]


@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-05: una ontología o un esquema con un predicado que RDF/XML no puede "
    "abreviar (p. ej. <http://x.example/p/1>) se admite, y su descarga en RDF/XML y su URI "
    "persistente con Accept: application/rdf+xml responden 500",
)
@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("predicate", UNSPLITTABLE)
def test_rdfxml_download_works_for_any_accepted_content(
    quiet: TestClient, editor: dict[str, str], store: MemoryStore, predicate: str
) -> None:
    onto = quiet.post(
        "/ontologies", content=_onto(f':A a owl:Class ; <{predicate}> "v" .'), headers=editor | TTL
    )
    scheme = quiet.post(
        "/schemes", content=_scheme(CONCEPT + f'; <{predicate}> "v" .'), headers=editor | TTL
    )
    if onto.status_code == 422 and scheme.status_code == 422:
        return  # rechazarlo en la ingesta también es una corrección válida
    for path in ("/ontologies/prueba/rdf?format=rdfxml", "/schemes/prueba/rdf?format=rdfxml"):
        assert quiet.get(path).status_code == 200, path
    for path in ("/onto/prueba", "/vocab/prueba", "/vocab/prueba/c"):
        assert quiet.get(path, headers={"Accept": RDFXML}).status_code == 200, path


@pytest.mark.usefixtures("fake_reasoner")
@pytest.mark.parametrize("predicate", UNSPLITTABLE)
def test_unsplittable_predicates_are_served_in_turtle_and_jsonld(
    client: TestClient, editor: dict[str, str], store: MemoryStore, predicate: str
) -> None:
    body = _onto(f':A a owl:Class ; <{predicate}> "v" .')
    assert client.post("/ontologies", content=body, headers=editor | TTL).status_code == 201
    for fmt in ("turtle", "jsonld"):
        response = client.get("/ontologies/prueba/rdf", params={"format": fmt})
        assert response.status_code == 200
        parsed = Graph().parse(data=response.text, format="json-ld" if fmt == "jsonld" else fmt)
        assert URIRef(predicate) in set(parsed.predicates())
    assert client.get("/ontologies/prueba").status_code == 200


@pytest.mark.usefixtures("fake_reasoner")
def test_non_http_iris_are_data_not_links_to_follow(
    client: TestClient, editor: dict[str, str], store: MemoryStore, no_network: list[object]
) -> None:
    """``javascript:`` o ``file:`` son IRIs sintácticamente válidas: el backend las guarda
    y las devuelve tal cual, sin resolverlas. El frontend solo enlaza http(s)
    (``isLinkableIri``, cubierto en sus pruebas)."""
    body = _scheme(
        CONCEPT + "; skos:exactMatch <javascript:alert(1)> ; skos:closeMatch <file:///etc/passwd> ."
    )
    assert client.post("/schemes", content=body, headers=editor | TTL).status_code == 201
    concept = client.get("/schemes/prueba/concepts/c").json()
    assert concept["exact_match"] == ["javascript:alert(1)"]
    assert concept["close_match"] == ["file:///etc/passwd"]
    assert "root:" not in json.dumps(concept)
    assert no_network == []


def test_scheme_subject_must_be_one_iri(
    client: TestClient, editor: dict[str, str], loaded_store: MemoryStore
) -> None:
    """El dominio de un esquema decide el dominio de los datasets que usan sus conceptos:
    solo un ``dct:subject`` y solo una IRI."""
    before = _snapshot(loaded_store)
    for extra in (
        f'<vocab/prueba> dct:subject "{BASE_URI}vocab/dominio/ot" .',
        "<vocab/prueba> dct:subject <vocab/dominio/ot> , <vocab/dominio/it> .",
        "<vocab/prueba> dct:subject [ a skos:Concept ] .",
    ):
        response = client.post(
            "/schemes", content=_scheme(CONCEPT + ". " + extra), headers=editor | TTL
        )
        assert response.status_code == 422, response.text
        assert response.json()["kind"] == "shacl"
    assert _snapshot(loaded_store) == before


def test_new_scheme_cannot_relabel_published_concepts(
    api: TestClient, editor: dict[str, str], vocab_store: MemoryStore
) -> None:
    """Un esquema nuevo que declara el dominio OT aparece como SKOS de dominio, pero no
    cambia el dominio, las etiquetas ni los usos de lo ya publicado."""
    datasets = api.get("/datasets").json()
    concept = api.get("/schemes/ot/concepts/modbus-tcp").json()
    body = _scheme(
        CONCEPT
        + "; skos:related <vocab/ot/modbus-tcp> . <vocab/prueba> dct:subject <vocab/dominio/ot> ."
    )
    assert api.post("/schemes", content=body, headers=editor | TTL).status_code == 201
    assert api.get("/datasets").json() == datasets
    after = api.get("/schemes/ot/concepts/modbus-tcp").json()
    # skos:related es simétrica solo dentro del grafo del propio esquema.
    assert after == concept
    page = api.get("/vocabularies", params={"domain": "ot"}).json()
    assert {c["slug"] for c in page["items"]} == {"ot", "prueba"}


def test_dct_namespace_matches() -> None:
    assert str(DCT) == "http://purl.org/dc/terms/"
