"""Integración con un Fuseki real (opcional).

Se salta salvo que se definan ``TEST_FUSEKI_URL``, ``TEST_FUSEKI_USER`` y
``TEST_FUSEKI_PASSWORD``, apuntando a un Fuseki **desechable** (las pruebas sustituyen
grafos con nombre). Ver «Pruebas contra un Fuseki real» en ``backend/README.md``.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef

from app import ingest
from app.deps import get_triplestore
from app.triplestore import FusekiStore, TriplestoreConfigError
from app.uris import Uris
from tests.conftest import BASE_URI, load_ontology_graphs, load_schemes

URL = os.environ.get("TEST_FUSEKI_URL")
USER = os.environ.get("TEST_FUSEKI_USER")
PASSWORD = os.environ.get("TEST_FUSEKI_PASSWORD")
DATASET = os.environ.get("TEST_FUSEKI_DATASET", "itot")

pytestmark = pytest.mark.skipif(
    not (URL and USER and PASSWORD), reason="sin TEST_FUSEKI_URL/USER/PASSWORD"
)


@pytest.fixture
def fuseki() -> FusekiStore:
    return FusekiStore(
        URL.rstrip("/"),  # type: ignore[union-attr]
        DATASET,
        credentials=(USER, PASSWORD),  # type: ignore[arg-type]
        timeout_seconds=20,
    )


@pytest.fixture
def fuseki_client(client: TestClient, fuseki: FusekiStore) -> Iterator[TestClient]:
    client.app.dependency_overrides[get_triplestore] = lambda: fuseki
    yield client


def _load(fuseki: FusekiStore, semantic_dir: Path) -> None:
    uris = Uris(BASE_URI)
    data = semantic_dir / "data"
    load_schemes(fuseki, semantic_dir, uris)  # type: ignore[arg-type]
    load_ontology_graphs(fuseki, semantic_dir, uris)  # type: ignore[arg-type]
    ingest.store_graph(fuseki, uris.catalog, ingest.parse_file(data / "catalogo.ttl", BASE_URI))
    for path in sorted((data / "sintetico").glob("*.ttl")):
        graph = ingest.parse_file(path, BASE_URI)
        ingest.publish(fuseki, ingest.prepare_series(graph, uris, semantic_dir))


def test_load_read_and_idempotency(
    fuseki: FusekiStore, fuseki_client: TestClient, semantic_dir: Path
) -> None:
    _load(fuseki, semantic_dir)
    series = f"{BASE_URI}dataset/modbus-tcp-testbed"
    stored = fuseki.get_graph(series)
    expected = ingest.parse_file(
        semantic_dir / "data" / "sintetico" / "modbus-tcp-testbed.ttl", BASE_URI
    )
    created, changed = ingest.store_graph(fuseki, series, expected)
    assert (created, changed) == (False, False)  # isomorfo: no se reescribe
    assert len(stored) == len(expected)

    body = fuseki_client.get("/datasets").json()
    assert body["total"] >= 3
    domains = {c["slug"]: c["domain"]["slug"] for c in body["items"] if c["domain"]}
    assert domains["modbus-tcp-testbed"] == "ot"
    assert domains["hallazgos-auditorias-intrusion"] == "it"
    assert domains["ejemplos-adversarios-vision"] == "ia"
    assert (
        fuseki_client.get("/datasets", params={"q": '" } UNION { ?s ?p ?o } #'}).json()["total"]
        == 0
    )

    detail = fuseki_client.get("/datasets/modbus-tcp-testbed").json()
    assert detail["current_version"] == "2.1.0"
    assert [s["kind"] for s in detail["version"]["provenance"]] == [
        "activity",
        "entity",
        "activity",
    ]
    assert detail["version"]["metadata"]["publisher"]["label"]

    ttl = fuseki_client.get("/dataset/modbus-tcp-testbed/2.1.0", headers={"Accept": "text/turtle"})
    graph = Graph().parse(data=ttl.text, format="turtle")
    assert (URIRef(f"{series}/2.1.0"), None, None) in graph


def test_wrong_credentials_are_reported(fuseki: FusekiStore) -> None:
    bad = FusekiStore(
        URL.rstrip("/"),  # type: ignore[union-attr]
        DATASET,
        credentials=(USER, "clave-equivocada"),  # type: ignore[arg-type]
        timeout_seconds=10,
    )
    with pytest.raises(TriplestoreConfigError, match="FUSEKI_USER"):
        bad.put_graph(f"{BASE_URI}dataset/prueba-credenciales", Graph())


def test_vocabularies_and_ontologies_on_real_fuseki(
    fuseki: FusekiStore,
    fuseki_client: TestClient,
    semantic_dir: Path,
    vocab_metrics: None,
) -> None:
    """Fase 3: las plantillas de lectura funcionan igual con el motor de Jena."""
    _load(fuseki, semantic_dir)
    counts = fuseki_client.get("/vocabularies").json()["counts"]
    assert counts == {"own": 3, "external": 3, "skos_corp": 4, "skos_domain": 5}

    onto = fuseki_client.get("/ontologies/itot").json()
    assert onto["versioning"]["current_version"] == "1.2.0"
    assert [h["version"] for h in onto["versioning"]["history"]] == ["1.2.0", "1.1.0", "1.0.0"]
    assert onto["metrics"]["classes"] > 0
    assert {i["prefix"] for i in onto["imports"]} == {"sosa", "saref"}
    assert onto["used_by_datasets"][0]["slug"] == "modbus-tcp-testbed"
    assert len(onto["subjects"]) == 11

    scheme = fuseki_client.get("/schemes/ot").json()
    assert scheme["domain"]["label"] == "OT / ICS"
    assert scheme["concept_count"] == 16
    concept = fuseki_client.get("/schemes/ot/concepts/modbus-tcp").json()
    assert concept["used_by"]["ontologies"][0]["slug"] == "itot"
    assert concept["used_by"]["datasets"][0]["slug"] == "modbus-tcp-testbed"

    card = fuseki_client.get("/datasets/modbus-tcp-testbed").json()
    assert card["domain"] == {
        "slug": "ot",
        "uri": f"{BASE_URI}vocab/dominio/ot",
        "label": "OT / ICS",
    }
    ttl = fuseki_client.get("/onto/itot", headers={"Accept": "text/turtle"})
    assert (URIRef(f"{BASE_URI}onto/itot#Control"), None, None) in Graph().parse(
        data=ttl.text, format="turtle"
    )
    payload = '" } UNION { ?s ?p ?o } #'
    assert fuseki_client.get("/vocabularies", params={"q": payload}).json()["total"] == 0
