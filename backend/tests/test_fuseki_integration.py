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
from tests.conftest import BASE_URI

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
    ingest.store_graph(
        fuseki, uris.vocab_graph, ingest.parse_file(data / "vocab-minimo.ttl", BASE_URI)
    )
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
