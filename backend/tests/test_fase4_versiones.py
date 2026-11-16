"""Fase 4: versiones inmutables (decisión 28), catálogo (29), búsqueda (30) y 303 (31)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import URIRef
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ingest
from app.models import AuditAction, AuditEvent, FairEvaluation, User
from app.triplestore import MemoryStore
from app.uris import DCAT, Uris
from tests.conftest import BASE_URI
from tests.fase4_data import V1, V2, editor_headers, publish, series

FRONTEND = "http://localhost:5173"


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    return editor_headers(make_user, login)


def test_new_version_is_added_and_old_one_kept(client: TestClient, editor, db: Session) -> None:
    assert publish(client, editor, series(V1)).status_code == 201
    response = publish(client, editor, series(V1, V2, last="2.0.0"))
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    rows = db.scalars(select(FairEvaluation.version_uri)).all()
    assert sorted(rows) == [f"{BASE_URI}dataset/prueba/1.0.0", f"{BASE_URI}dataset/prueba/2.0.0"]


def test_series_metadata_can_change(client: TestClient, editor) -> None:
    assert publish(client, editor, series(V1)).status_code == 201
    response = publish(client, editor, series(V1, title="Otro título"))
    assert response.status_code == 200, response.text
    assert client.get("/datasets/prueba").json()["title"] == "Otro título"


def test_republishing_identical_is_idempotent(client: TestClient, editor, store) -> None:
    publish(client, editor, series(V1))
    response = publish(client, editor, series(V1))
    assert response.status_code == 200
    assert response.json()["changed"] is False


def test_changed_version_is_409(client: TestClient, editor, store: MemoryStore) -> None:
    publish(client, editor, series(V1))
    before = len(store.get_graph(f"{BASE_URI}dataset/prueba"))
    changed = V1.replace('"Versión 1"@es', '"Versión 1 retocada"@es')
    response = publish(client, editor, series(changed))
    assert response.status_code == 409
    body = response.json()
    assert body["kind"] == "version_immutable"
    assert [i["focus_node"] for i in body["issues"]] == [f"{BASE_URI}dataset/prueba/1.0.0"]
    assert len(store.get_graph(f"{BASE_URI}dataset/prueba")) == before


def test_changed_distribution_is_409(client: TestClient, editor) -> None:
    publish(client, editor, series(V1))
    changed = V1.replace(
        "dcat:accessURL <dataset/prueba/1.0.0/npz> .",
        'dcat:accessURL <dataset/prueba/1.0.0/npz> ; dct:title "NPZ"@es .',
    )
    response = publish(client, editor, series(changed))
    assert response.status_code == 409
    assert response.json()["kind"] == "version_immutable"


def test_changed_blank_node_provenance_is_409(client: TestClient, editor) -> None:
    publish(client, editor, series(V1))
    response = publish(client, editor, series(V1.replace('"Captura"@es', '"Otra"@es')))
    assert response.status_code == 409


def test_blank_nodes_with_other_labels_are_the_same_version(
    client: TestClient, editor, store: MemoryStore, uris: Uris
) -> None:
    """Mismo contenido con otros identificadores de nodos en blanco: isomorfo, no 409."""
    publish(client, editor, series(V1))
    explicit = (
        V1.replace(
            'prov:wasGeneratedBy [ a prov:Activity ; rdfs:label "Captura"@es ] ;',
            "prov:wasGeneratedBy _:otro ;",
        )
        + '_:otro a prov:Activity ; rdfs:label "Captura"@es .\n'
    )
    response = publish(client, editor, series(explicit))
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is False


def test_removed_version_is_409(client: TestClient, editor) -> None:
    publish(client, editor, series(V1, V2, last="2.0.0"))
    response = publish(
        client,
        editor,
        series(V2.replace("dcat:previousVersion <dataset/prueba/1.0.0> ;", ""), last="2.0.0"),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["kind"] == "version_removed"
    assert body["issues"][0]["focus_node"] == f"{BASE_URI}dataset/prueba/1.0.0"


def test_reserved_distribution_slug_is_rejected(client: TestClient, editor) -> None:
    body = series(V1.replace("dataset/prueba/1.0.0/npz", "dataset/prueba/1.0.0/fichero"))
    response = publish(client, editor, body)
    assert response.status_code == 422
    assert response.json()["kind"] == "uri"


def test_series_is_linked_from_catalog(
    client: TestClient, editor, store: MemoryStore, uris: Uris
) -> None:
    publish(client, editor, series(V1))
    catalog = store.get_graph(uris.catalog)
    assert (URIRef(uris.catalog), DCAT.dataset, URIRef(uris.series("prueba"))) in catalog


def test_load_semantic_catalog_keeps_api_series(
    loaded_store: MemoryStore, semantic_dir: Path, uris: Uris
) -> None:
    ingest.ensure_in_catalog(loaded_store, uris.catalog, uris.series("prueba"))
    loaded = ingest.parse_file(semantic_dir / "data" / "catalogo.ttl", uris.base)
    merged = ingest.merge_catalog(loaded_store.get_graph(uris.catalog), loaded, uris)
    assert (URIRef(uris.catalog), DCAT.dataset, URIRef(uris.series("prueba"))) in merged
    for triple in loaded:
        assert triple in merged


def test_publish_audits_new_versions(client: TestClient, editor, db: Session) -> None:
    publish(client, editor, series(V1))
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DATASET_PUBLISHED.value)
    ).one()
    assert event.details["new_versions"] == [f"{BASE_URI}dataset/prueba/1.0.0"]


# --- Búsqueda (decisión 30) -----------------------------------------------------------------


def test_q_matches_series_uri_but_not_base_uri(
    loaded_store: MemoryStore, client: TestClient
) -> None:
    every = client.get("/datasets").json()["total"]
    assert client.get("/datasets", params={"q": "itot"}).json()["total"] < every
    hits = client.get("/datasets", params={"q": "modbus-tcp"}).json()["items"]
    assert [card["slug"] for card in hits] == ["modbus-tcp-testbed"]


def test_vocabulary_q_ignores_namespace(vocab_store: MemoryStore, client: TestClient) -> None:
    every = client.get("/vocabularies").json()["total"]
    found = client.get("/vocabularies", params={"q": "itot"}).json()
    assert found["total"] < every
    assert any(card["uri"] == f"{BASE_URI}onto/itot" for card in found["items"])


# --- Negociación (decisión 31) ---------------------------------------------------------


@pytest.mark.parametrize("accept", [None, "*/*", "text/html"])
@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/dataset/modbus-tcp-testbed", "/datasets/modbus-tcp-testbed"),
        ("/dataset/modbus-tcp-testbed/2.1.0", "/datasets/modbus-tcp-testbed?version=2.1.0"),
        (
            "/dataset/modbus-tcp-testbed/2.1.0/pcap",
            "/datasets/modbus-tcp-testbed?version=2.1.0#distribuciones",
        ),
        ("/onto/itot", "/ontologias/itot"),
        ("/vocab/ot", "/vocabularios/ot"),
    ],
)
def test_persistent_uris_redirect_without_rdf_accept(
    vocab_store: MemoryStore, client: TestClient, accept: str | None, path: str, target: str
) -> None:
    headers = {"Accept": accept} if accept else {}
    if accept is None:
        # httpx añade «Accept: */*» por defecto: se quita para probar la petición sin cabecera.
        response = client.get(path, headers={"Accept": ""}, follow_redirects=False)
    else:
        response = client.get(path, headers=headers, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND}{target}"


@pytest.mark.parametrize("accept", ["text/turtle", "application/ld+json", "application/rdf+xml"])
def test_distribution_uri_serves_rdf(
    loaded_store: MemoryStore, client: TestClient, accept: str
) -> None:
    response = client.get("/dataset/modbus-tcp-testbed/2.1.0/pcap", headers={"Accept": accept})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(accept)
    assert f"{BASE_URI}dataset/modbus-tcp-testbed/2.1.0/pcap" in response.text


def test_unknown_distribution_is_404(loaded_store: MemoryStore, client: TestClient) -> None:
    response = client.get(
        "/dataset/modbus-tcp-testbed/2.1.0/no-existe", headers={"Accept": "text/turtle"}
    )
    assert response.status_code == 404
