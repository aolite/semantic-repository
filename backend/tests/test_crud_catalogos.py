"""Decisión 49: varios catálogos, CRUD de catálogos y datasets, bajas con 410.

Cubre los endpoints de ``/catalogs`` y ``PATCH``/``DELETE /datasets/{slug}``, los permisos
por rol, el borrado lógico (lápida en ``{BASE_URI}bajas``), el 410 por prefijo, los dos 409
(slug dado de baja y catálogo con datasets), que las bajas no salen en SPARQL ni en los
listados y lo que hace ``load-semantic`` con lo hecho desde la aplicación.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import catalog, ingest, owl_metrics, vocab_ingest
from app import cli as cli_module
from app.config import get_settings
from app.models import AuditAction, AuditEvent, DistributionFile, Role, User
from app.storage import DiskStorage
from app.triplestore import MemoryStore
from app.uris import ADMS, DCAT, DCT, PROV, Uris
from tests import fase4_data
from tests.conftest import BASE_URI, TEST_CATALOG_URI

ROOT = f"{BASE_URI}catalogo"
SINTETICO = f"{BASE_URI}catalogo/sintetico"
BAJAS = f"{BASE_URI}bajas"
MODBUS = f"{BASE_URI}dataset/modbus-tcp-testbed"
WITHDRAWN = URIRef("http://purl.org/adms/status/Withdrawn")
TURTLE = {"Accept": "text/turtle"}

NEW_CATALOG = {
    "slug": "piloto",
    "title": "Datasets del piloto",
    "description": "Catálogo de prueba",
    "publisher_name": "Agente de prueba",
}
NEW_DATASET = {"slug": "nuevo", "title": "Dataset nuevo", "description": "Descripción"}


@pytest.fixture
def api(client: TestClient, loaded_store: MemoryStore) -> TestClient:
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


def _events(session_factory: sessionmaker[Session], action: AuditAction) -> list[AuditEvent]:
    with session_factory() as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.action == action.value)))


def _sparql_uris(api: TestClient, query: str) -> set[str]:
    response = api.get("/sparql", params={"query": query})
    assert response.status_code == 200, response.text
    return {
        value["value"] for row in response.json()["results"]["bindings"] for value in row.values()
    }


# --- Modelo: raíz, catálogos y pertenencia ----------------------------------------------


def test_root_groups_catalogs_and_series_belong_to_their_catalog(
    loaded_store: MemoryStore,
) -> None:
    root = loaded_store.get_graph(ROOT)
    assert (URIRef(ROOT), DCAT.catalog, URIRef(SINTETICO)) in root
    assert not list(root.objects(URIRef(ROOT), DCAT.dataset))  # el raíz no lista series
    members = set(loaded_store.get_graph(SINTETICO).objects(URIRef(SINTETICO), DCAT.dataset))
    assert URIRef(MODBUS) in members and len(members) == 3
    # El triple de pertenencia está en el grafo del catálogo, no en el de la serie.
    assert not list(loaded_store.get_graph(MODBUS).triples((None, DCAT.dataset, None)))


def test_list_and_get_catalogs(api: TestClient) -> None:
    page = api.get("/catalogs").json()
    by_slug = {item["slug"]: item for item in page["items"]}
    assert by_slug["sintetico"]["title"] == "Datasets sintéticos de demostración"
    assert by_slug["sintetico"]["dataset_count"] == 3
    assert by_slug["sintetico"]["publisher"]["label"] == "Eurecat · Unidad IT&OT Security"
    assert all(item["uri"] != ROOT for item in page["items"])  # sin el raíz
    detail = api.get("/catalogs/sintetico").json()
    assert {d["slug"] for d in detail["datasets"]} == {
        "modbus-tcp-testbed",
        "hallazgos-auditorias-intrusion",
        "ejemplos-adversarios-vision",
    }
    assert api.get("/catalogs/no-existe").status_code == 404
    assert api.get("/catalogs/No_Valido").status_code == 422


def test_detail_carries_the_series_publisher(api: TestClient, editor: dict[str, str]) -> None:
    """El publicador de la serie, para precargar el formulario de edición."""
    detail = api.get("/datasets/modbus-tcp-testbed").json()
    assert detail["publisher"] == {"uri": None, "label": "Eurecat · Unidad IT&OT Security"}
    created = api.post(
        "/catalogs/sintetico/datasets",
        json={**NEW_DATASET, "publisher_name": "Agente de prueba"},
        headers=editor,
    ).json()
    assert created["publisher"] == {"uri": None, "label": "Agente de prueba"}
    edited = api.patch(
        "/datasets/nuevo", json={"publisher_name": "Otro agente"}, headers=editor
    ).json()
    assert edited["publisher"] == {"uri": None, "label": "Otro agente"}
    kept = api.patch("/datasets/nuevo", json={"title": "Otro título"}, headers=editor).json()
    assert kept["publisher"] == {"uri": None, "label": "Otro agente"}


def test_cards_and_detail_carry_their_catalog(api: TestClient) -> None:
    cards = api.get("/datasets").json()["items"]
    assert {c["catalog"]["slug"] for c in cards} == {"sintetico"}
    assert api.get("/datasets", params={"catalog": "sintetico"}).json()["total"] == 3
    assert api.get("/datasets", params={"catalog": "pruebas"}).json()["total"] == 0
    detail = api.get("/datasets/modbus-tcp-testbed").json()
    assert detail["catalog"] == {
        "slug": "sintetico",
        "uri": SINTETICO,
        "title": "Datasets sintéticos de demostración",
    }


def test_series_rdf_includes_its_membership(api: TestClient) -> None:
    response = api.get("/dataset/modbus-tcp-testbed", headers=TURTLE)
    graph = Graph().parse(data=response.text, format="turtle")
    assert (URIRef(SINTETICO), DCAT.dataset, URIRef(MODBUS)) in graph


def test_catalog_uris_negotiate_content(api: TestClient, settings) -> None:
    response = api.get("/catalogo/sintetico", headers=TURTLE)
    assert response.status_code == 200
    graph = Graph().parse(data=response.text, format="turtle")
    assert (URIRef(SINTETICO), RDF.type, DCAT.Catalog) in graph
    redirect = api.get("/catalogo/sintetico", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"].endswith("/catalogos/sintetico")
    root = api.get("/catalogo", headers=TURTLE)
    assert (URIRef(ROOT), DCAT.catalog, URIRef(SINTETICO)) in Graph().parse(
        data=root.text, format="turtle"
    )
    assert api.get("/catalogo", follow_redirects=False).status_code == 303
    assert api.get("/catalogo/no-existe", headers=TURTLE).status_code == 404


# --- Permisos ---------------------------------------------------------------------------

WRITES = [
    ("POST", "/catalogs", NEW_CATALOG),
    ("PATCH", "/catalogs/sintetico", {"title": "Otro"}),
    ("DELETE", "/catalogs/sintetico", None),
    ("POST", "/catalogs/sintetico/datasets", NEW_DATASET),
    ("PATCH", "/datasets/modbus-tcp-testbed", {"title": "Otro"}),
    ("DELETE", "/datasets/modbus-tcp-testbed", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_anonymous_and_member_cannot_write(
    api: TestClient,
    loaded_store: MemoryStore,
    member: dict[str, str],
    method: str,
    path: str,
    body: dict | None,
) -> None:
    before = {name: len(loaded_store.get_graph(name)) for name in loaded_store.graph_names()}
    assert api.request(method, path, json=body).status_code == 401
    assert api.request(method, path, json=body, headers=member).status_code == 403
    after = {name: len(loaded_store.get_graph(name)) for name in loaded_store.graph_names()}
    assert after == before


@pytest.mark.parametrize("who", ["editor", "admin"])
def test_editor_and_admin_can_create_edit_and_withdraw(
    api: TestClient, request: pytest.FixtureRequest, who: str
) -> None:
    headers = request.getfixturevalue(who)
    assert api.post("/catalogs", json=NEW_CATALOG, headers=headers).status_code == 201
    created = api.post("/catalogs/piloto/datasets", json=NEW_DATASET, headers=headers)
    assert created.status_code == 201, created.text
    assert api.patch("/datasets/nuevo", json={"title": "T"}, headers=headers).status_code == 200
    assert api.patch("/catalogs/piloto", json={"title": "T"}, headers=headers).status_code == 200
    assert api.delete("/datasets/nuevo", headers=headers).status_code == 204
    assert api.delete("/catalogs/piloto", headers=headers).status_code == 204


# --- Catálogos --------------------------------------------------------------------------


def test_create_catalog(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["uri"] == f"{BASE_URI}catalogo/piloto"
    assert body["datasets"] == [] and body["dataset_count"] == 0
    graph = loaded_store.get_graph(body["uri"])
    assert (URIRef(body["uri"]), RDF.type, DCAT.Catalog) in graph
    assert (URIRef(ROOT), DCAT.catalog, URIRef(body["uri"])) in loaded_store.get_graph(ROOT)
    assert "piloto" in {c["slug"] for c in api.get("/catalogs").json()["items"]}
    events = _events(session_factory, AuditAction.CATALOG_CREATED)
    assert [(e.actor_username, e.details["catalog"]) for e in events] == [("editora", body["uri"])]
    # El slug ya existe: 409 slug_in_use.
    again = api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    assert again.status_code == 409
    assert again.json() == {
        "detail": "Ya existe el catálogo con ese slug",
        "kind": "slug_in_use",
        "datasets": [],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"slug": "No Valido"},
        {"slug": "-mal"},
        {"title": "   "},
        {"title": "con\x00control"},
        {"description": ""},
        {"publisher_name": None},
        {"extra": "no admitido"},
    ],
)
def test_create_catalog_rejects_invalid_forms(
    api: TestClient, loaded_store: MemoryStore, editor: dict[str, str], change: dict
) -> None:
    before = loaded_store.graph_names()
    body = {**NEW_CATALOG, **change}
    assert api.post("/catalogs", json=body, headers=editor).status_code == 422
    assert loaded_store.graph_names() == before


def test_root_catalog_is_not_managed_by_the_api(api: TestClient, editor: dict[str, str]) -> None:
    # «catalogo» a secas no es un slug de catalogo/{slug}: no hay ruta para el raíz.
    assert api.patch("/catalogs", json={"title": "x"}, headers=editor).status_code == 405
    assert api.delete("/catalogs", headers=editor).status_code == 405


def test_update_catalog_keeps_its_datasets(
    api: TestClient, loaded_store: MemoryStore, editor: dict[str, str]
) -> None:
    response = api.patch(
        "/catalogs/sintetico",
        json={"title": "Sintéticos", "publisher_name": "Otro agente"},
        headers=editor,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Sintéticos"
    assert body["publisher"]["label"] == "Otro agente"
    assert body["description"].startswith("Datasets sintéticos que reproducen")
    assert body["dataset_count"] == 3
    graph = loaded_store.get_graph(SINTETICO)
    assert len(list(graph.objects(URIRef(SINTETICO), DCT.publisher))) == 1
    assert api.patch("/catalogs/no-existe", json={"title": "x"}, headers=editor).status_code == 404
    assert api.patch("/catalogs/sintetico", json={"title": ""}, headers=editor).status_code == 422


def test_withdraw_catalog_with_datasets_is_409(
    api: TestClient, loaded_store: MemoryStore, editor: dict[str, str]
) -> None:
    response = api.delete("/catalogs/sintetico", headers=editor)
    assert response.status_code == 409
    assert response.json()["kind"] == "catalog_not_empty"
    assert MODBUS in response.json()["datasets"]
    assert (URIRef(SINTETICO), RDF.type, DCAT.Catalog) in loaded_store.get_graph(SINTETICO)
    assert BAJAS not in loaded_store.graph_names()


def test_withdraw_empty_catalog(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    semantic_dir: Path,
) -> None:
    api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    uri = f"{BASE_URI}catalogo/piloto"
    assert api.delete("/catalogs/piloto", headers=editor).status_code == 204
    # Sale del triplestore publicado y del raíz; queda la lápida.
    assert uri not in loaded_store.graph_names()
    assert (URIRef(ROOT), DCAT.catalog, URIRef(uri)) not in loaded_store.get_graph(ROOT)
    bajas = loaded_store.get_graph(BAJAS)
    node = URIRef(uri)
    assert set(bajas.objects(node, RDF.type)) == {PROV.Entity}
    assert (node, ADMS.status, WITHDRAWN) in bajas
    assert str(bajas.value(node, DCT.title)) == "Datasets del piloto"
    assert bajas.value(node, PROV.invalidatedAtTime) is not None
    ingest.validate_plain(bajas, semantic_dir, BASE_URI)  # cumple itsh:BajaShape
    # Quién la dio de baja, en la auditoría (no en el RDF).
    events = _events(session_factory, AuditAction.CATALOG_WITHDRAWN)
    assert [e.actor_username for e in events] == ["editora"]
    # Fuera de los listados; su URI responde 410.
    assert "piloto" not in {c["slug"] for c in api.get("/catalogs").json()["items"]}
    gone = api.get("/catalogs/piloto")
    assert gone.status_code == 410
    assert gone.json() == {
        "detail": "Recurso dado de baja",
        "uri": uri,
        "resource": "catalog",
        "title": "Datasets del piloto",
        "withdrawn_at": str(bajas.value(node, PROV.invalidatedAtTime)),
    }
    assert api.patch("/catalogs/piloto", json={"title": "x"}, headers=editor).status_code == 410
    assert api.delete("/catalogs/piloto", headers=editor).status_code == 410
    assert (
        api.post("/catalogs/piloto/datasets", json=NEW_DATASET, headers=editor).status_code == 410
    )
    # El slug no se reutiliza: 409 withdrawn (distinto de slug_in_use).
    reused = api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    assert reused.status_code == 409
    assert reused.json()["kind"] == "withdrawn" and reused.json()["datasets"] == []


def test_withdrawn_catalog_uri_answers_410_in_html_and_rdf(
    api: TestClient, editor: dict[str, str]
) -> None:
    api.post("/catalogs", json={**NEW_CATALOG, "title": "<b>Piloto</b>"}, headers=editor)
    api.delete("/catalogs/piloto", headers=editor)
    html = api.get("/catalogo/piloto", follow_redirects=False)
    assert html.status_code == 410
    assert html.headers["content-type"].startswith("text/html")
    assert "&lt;b&gt;Piloto&lt;/b&gt;" in html.text and "<b>" not in html.text
    rdf = api.get("/catalogo/piloto", headers=TURTLE)
    assert rdf.status_code == 410
    graph = Graph().parse(data=rdf.text, format="turtle")
    assert (URIRef(f"{BASE_URI}catalogo/piloto"), ADMS.status, WITHDRAWN) in graph


# --- Datasets ---------------------------------------------------------------------------


def test_create_dataset_in_catalog(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = api.post("/catalogs/sintetico/datasets", json=NEW_DATASET, headers=editor)
    assert response.status_code == 201, response.text
    body = response.json()
    uri = f"{BASE_URI}dataset/nuevo"
    assert body["uri"] == uri and body["catalog"]["slug"] == "sintetico"
    assert body["version"] is None and body["versions"] == []
    assert (URIRef(SINTETICO), DCAT.dataset, URIRef(uri)) in loaded_store.get_graph(SINTETICO)
    assert not list(loaded_store.get_graph(uri).triples((None, DCAT.dataset, None)))
    assert [e.details["series"] for e in _events(session_factory, AuditAction.DATASET_CREATED)] == [
        uri
    ]
    assert body["publisher"] is None  # el formulario no lo indicó
    again = api.post("/catalogs/sintetico/datasets", json=NEW_DATASET, headers=editor)
    assert again.status_code == 409
    assert again.json()["kind"] == "slug_in_use"
    # El slug de un dataset es único en todo el repositorio, no por catálogo.
    other = api.post("/catalogs/pruebas/datasets", json=NEW_DATASET, headers=editor)
    assert other.status_code == 409 and other.json()["kind"] == "slug_in_use"
    missing = api.post("/catalogs/no-existe/datasets", json=NEW_DATASET, headers=editor)
    assert missing.status_code == 404


def test_versions_are_published_with_the_rdf_flow_and_catalog_param(
    api: TestClient, loaded_store: MemoryStore, editor: dict[str, str]
) -> None:
    api.post(
        "/catalogs/pruebas/datasets",
        json={**NEW_DATASET, "slug": "prueba"},
        headers=editor,
    )
    body = fase4_data.series(fase4_data.V1).replace(
        "<catalogo/pruebas> dcat:dataset <dataset/prueba> .\n", ""
    )
    response = api.post(
        "/datasets",
        params={"catalog": "pruebas"},
        content=body.encode(),
        headers=editor | fase4_data.TURTLE_CT,
    )
    assert response.status_code == 200, response.text  # la serie ya existía
    assert response.json()["versions"] == ["1.0.0"]
    detail = api.get("/datasets/prueba").json()
    assert detail["current_version"] == "1.0.0" and detail["catalog"]["slug"] == "pruebas"
    # Sin catálogo (ni triple ni parámetro): SHACL lo rechaza.
    without = api.post("/datasets", content=body.encode(), headers=editor | fase4_data.TURTLE_CT)
    assert without.status_code == 422 and without.json()["kind"] == "shacl"
    # Parámetro distinto del triple declarado: 422.
    both = api.post(
        "/datasets",
        params={"catalog": "sintetico"},
        content=fase4_data.series(fase4_data.V1).encode(),
        headers=editor | fase4_data.TURTLE_CT,
    )
    assert both.status_code == 422 and both.json()["kind"] == "catalog"


def test_publishing_into_another_catalog_is_a_conflict(
    api: TestClient, loaded_store: MemoryStore, editor: dict[str, str]
) -> None:
    assert fase4_data.publish(api, editor, fase4_data.series(fase4_data.V1)).status_code == 201
    moved = fase4_data.series(fase4_data.V1).replace("<catalogo/pruebas>", "<catalogo/sintetico>")
    response = fase4_data.publish(api, editor, moved)
    assert response.status_code == 409
    assert response.json()["kind"] == "catalog_conflict"
    assert response.json()["issues"][0]["focus_node"] == TEST_CATALOG_URI
    members = loaded_store.get_graph(SINTETICO).objects(URIRef(SINTETICO), DCAT.dataset)
    assert URIRef(f"{BASE_URI}dataset/prueba") not in set(members)


@pytest.mark.parametrize(
    ("membership", "status", "kind"),
    [
        ("<catalogo/no-existe> dcat:dataset <dataset/prueba> .", 422, "catalog"),
        ("<catalogo> dcat:dataset <dataset/prueba> .", 422, "uri"),
        ('<catalogo/pruebas> dct:title "Cambio"@es .', 422, "uri"),
        ("<catalogo/pruebas/sub> dcat:dataset <dataset/prueba> .", 422, "uri"),
        ("<catalogo/sintetico> dcat:dataset <dataset/prueba> .", 422, "shacl"),
    ],
)
def test_membership_rules_on_ingest(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    membership: str,
    status: int,
    kind: str,
) -> None:
    body = fase4_data.series(fase4_data.V1)
    if kind != "shacl":  # en el caso shacl se añade un segundo catálogo
        body = body.replace("<catalogo/pruebas> dcat:dataset <dataset/prueba> .\n", "")
    response = fase4_data.publish(api, editor, body + membership + "\n")
    assert response.status_code == status, response.text
    assert response.json()["kind"] == kind
    assert f"{BASE_URI}dataset/prueba" not in loaded_store.graph_names()


def test_update_series_metadata_keeps_versions(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    uris: Uris,
    session_factory: sessionmaker[Session],
) -> None:
    before = loaded_store.get_graph(MODBUS)
    response = api.patch(
        "/datasets/modbus-tcp-testbed",
        json={"title": "Nuevo título", "description": "Nueva descripción"},
        headers=editor,
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Nuevo título"
    after = loaded_store.get_graph(MODBUS)
    series = URIRef(MODBUS)
    for version in ingest.published_versions(before, MODBUS).values():
        assert isomorphic(
            catalog.version_subgraph(before, series, version),
            catalog.version_subgraph(after, series, version),
        )
    assert [str(t) for t in after.objects(series, DCT.title)] == ["Nuevo título"]
    events = _events(session_factory, AuditAction.DATASET_UPDATED)
    assert events[0].details["fields"] == ["description", "title"]
    assert events[0].details["moved_from"] == []


def test_move_dataset_to_another_catalog(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = api.patch(
        "/datasets/modbus-tcp-testbed", json={"catalog": "pruebas"}, headers=editor
    )
    assert response.status_code == 200, response.text
    assert response.json()["catalog"]["slug"] == "pruebas"
    assert response.json()["uri"] == MODBUS  # la URI no cambia
    origin = set(loaded_store.get_graph(SINTETICO).objects(URIRef(SINTETICO), DCAT.dataset))
    target = set(
        loaded_store.get_graph(TEST_CATALOG_URI).objects(URIRef(TEST_CATALOG_URI), DCAT.dataset)
    )
    assert URIRef(MODBUS) not in origin and URIRef(MODBUS) in target
    assert api.get("/catalogs/sintetico").json()["dataset_count"] == 2
    events = _events(session_factory, AuditAction.DATASET_UPDATED)
    assert events[0].details["moved_from"] == [SINTETICO]
    # Destino inexistente o dado de baja: 422 catalog.
    missing = api.patch("/datasets/modbus-tcp-testbed", json={"catalog": "nada"}, headers=editor)
    assert missing.status_code == 422 and missing.json()["kind"] == "catalog"
    api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    api.delete("/catalogs/piloto", headers=editor)
    gone = api.patch("/datasets/modbus-tcp-testbed", json={"catalog": "piloto"}, headers=editor)
    assert gone.status_code == 422 and gone.json()["kind"] == "catalog"


def test_update_unknown_or_invalid(api: TestClient, editor: dict[str, str]) -> None:
    assert api.patch("/datasets/no-existe", json={"title": "x"}, headers=editor).status_code == 404
    bad = api.patch("/datasets/modbus-tcp-testbed", json={"dcat:last": "x"}, headers=editor)
    assert bad.status_code == 422


# --- Baja de un dataset: lápida, ficheros y 410 por prefijo -----------------------------


@pytest.fixture
def withdrawn_prueba(
    api: TestClient,
    editor: dict[str, str],
    file_storage: DiskStorage,
    session_factory: sessionmaker[Session],
) -> None:
    """Serie «prueba» con ficheros subidos y después dada de baja."""
    assert fase4_data.publish(api, editor, fase4_data.series(fase4_data.V1)).status_code == 201
    for dist in ("abierta", "restringida"):
        assert fase4_data.upload(api, editor, dist, b"contenido").status_code == 201
    assert file_storage.exists("prueba/1.0.0/abierta")
    assert api.delete("/datasets/prueba", headers=editor).status_code == 204


def test_withdraw_dataset_removes_description_and_files(
    api: TestClient,
    loaded_store: MemoryStore,
    withdrawn_prueba: None,
    file_storage: DiskStorage,
    session_factory: sessionmaker[Session],
    semantic_dir: Path,
) -> None:
    uri = f"{BASE_URI}dataset/prueba"
    assert uri not in loaded_store.graph_names()
    members = loaded_store.get_graph(TEST_CATALOG_URI).objects(
        URIRef(TEST_CATALOG_URI), DCAT.dataset
    )
    assert URIRef(uri) not in set(members)
    assert not file_storage.exists("prueba/1.0.0/abierta")
    assert not file_storage.exists("prueba/1.0.0/restringida")
    with session_factory() as session:
        assert session.scalars(select(DistributionFile)).all() == []
    bajas = loaded_store.get_graph(BAJAS)
    ingest.validate_plain(bajas, semantic_dir, BASE_URI)
    assert set(bajas.subjects(PROV.invalidatedAtTime, None)) == {URIRef(uri)}
    assert str(bajas.value(URIRef(uri), DCT.title)) == "Serie de prueba"
    events = _events(session_factory, AuditAction.DATASET_WITHDRAWN)
    assert len(events) == 1 and events[0].actor_username == "editora"
    assert events[0].details["files_deleted"] == [
        "prueba/1.0.0/abierta",
        "prueba/1.0.0/restringida",
    ]
    assert events[0].details["catalogs"] == [TEST_CATALOG_URI]


@pytest.mark.parametrize(
    "path",
    [
        "/datasets/prueba",
        "/datasets/prueba?version=1.0.0",
        "/datasets/prueba/rdf",
        "/datasets/prueba/versions/1.0.0/fair/report",
    ],
)
def test_withdrawn_dataset_api_answers_410(
    api: TestClient, withdrawn_prueba: None, path: str
) -> None:
    response = api.get(path)
    assert response.status_code == 410, path
    body = response.json()
    assert body["uri"] == f"{BASE_URI}dataset/prueba"
    assert body["resource"] == "dataset" and body["title"] == "Serie de prueba"


@pytest.mark.parametrize(
    "path",
    [
        "/dataset/prueba",
        "/dataset/prueba/1.0.0",
        "/dataset/prueba/1.0.0/abierta",
        "/dataset/prueba/1.0.0/abierta/fichero",
        "/dataset/prueba/9.9.9",  # por prefijo, aunque esa versión no existiera
    ],
)
def test_withdrawn_dataset_uris_answer_410_by_prefix(
    api: TestClient, withdrawn_prueba: None, path: str
) -> None:
    html = api.get(path, follow_redirects=False)
    assert html.status_code == 410, path
    assert html.headers["content-type"].startswith("text/html")
    assert "Serie de prueba" in html.text
    rdf = api.get(path, headers=TURTLE)
    assert rdf.status_code == 410
    graph = Graph().parse(data=rdf.text, format="turtle")
    assert (URIRef(f"{BASE_URI}dataset/prueba"), ADMS.status, WITHDRAWN) in graph


def test_withdrawn_dataset_edits_answer_410(
    api: TestClient, withdrawn_prueba: None, editor: dict[str, str]
) -> None:
    assert api.patch("/datasets/prueba", json={"title": "x"}, headers=editor).status_code == 410
    assert api.delete("/datasets/prueba", headers=editor).status_code == 410
    assert fase4_data.upload(api, editor, "abierta", b"x").status_code == 410
    link = api.post(
        "/datasets/prueba/versions/1.0.0/distributions/abierta/download-link", headers=editor
    )
    assert link.status_code == 410


def test_withdrawn_slug_is_not_reused(
    api: TestClient, withdrawn_prueba: None, editor: dict[str, str]
) -> None:
    response = fase4_data.publish(api, editor, fase4_data.series(fase4_data.V1))
    assert response.status_code == 409
    assert response.json()["kind"] == "withdrawn"
    again = api.post(
        "/catalogs/pruebas/datasets", json={**NEW_DATASET, "slug": "prueba"}, headers=editor
    )
    assert again.status_code == 409
    assert again.json()["kind"] == "withdrawn"


def test_withdrawn_resources_leave_listings_and_sparql(
    api: TestClient, editor: dict[str, str], query_runner
) -> None:
    api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    api.delete("/catalogs/piloto", headers=editor)
    assert api.delete("/datasets/modbus-tcp-testbed", headers=editor).status_code == 204
    slugs = {c["slug"] for c in api.get("/datasets").json()["items"]}
    assert "modbus-tcp-testbed" not in slugs and len(slugs) == 2
    assert api.get("/datasets", params={"q": "Modbus"}).json()["total"] == 0
    assert "piloto" not in {c["slug"] for c in api.get("/catalogs").json()["items"]}
    assert api.get("/catalogs/sintetico").json()["dataset_count"] == 2
    # Ni el grafo de bajas ni las lápidas se ven en SPARQL, tampoco con GRAPH ?g.
    graphs = _sparql_uris(api, "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")
    assert BAJAS not in graphs and MODBUS not in graphs and graphs
    subjects = _sparql_uris(api, "SELECT DISTINCT ?s WHERE { ?s ?p ?o }")
    assert MODBUS not in subjects and f"{BASE_URI}catalogo/piloto" not in subjects
    ask = api.get(
        "/sparql",
        params={
            "query": "ASK { GRAPH ?g { ?s <http://www.w3.org/ns/prov#invalidatedAtTime> ?t } }"
        },
    )
    assert ask.json()["boolean"] is False
    for clause in (f"FROM <{BAJAS}>", f"FROM NAMED <{BAJAS}>"):
        response = api.get("/sparql", params={"query": f"SELECT * {clause} WHERE {{ ?s ?p ?o }}"})
        assert response.status_code == 400
    # Con FROM hacia un grafo publicado se consulta solo ese grafo.
    hallazgos = f"{BASE_URI}dataset/hallazgos-auditorias-intrusion"
    query = "SELECT DISTINCT ?s FROM <GRAFO> WHERE { ?s a ?t }".replace("GRAFO", hallazgos)
    only = _sparql_uris(api, query)
    assert hallazgos in only and MODBUS not in only
    assert query_runner.graphs[-1] is None  # con FROM no se pasa la lista de grafos


# --- load-semantic respeta lo hecho desde la aplicación ---------------------------------


@pytest.fixture
def cli_doubles(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    loaded_store: MemoryStore,
    tmp_path: Path,
    file_storage: DiskStorage,
) -> CliRunner:
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: loaded_store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)

    def fake_metrics(prepared: vocab_ingest.PreparedOntology, _settings: object):
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri)
        return metrics.to_dict(), owl_metrics.Consistency(detail="prueba").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake_metrics)
    get_settings.cache_clear()
    ingest.clear_caches()
    return CliRunner()


def test_load_semantic_keeps_withdrawals_and_moves(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    cli_doubles: CliRunner,
) -> None:
    api.post("/catalogs", json=NEW_CATALOG, headers=editor)
    assert api.delete("/datasets/modbus-tcp-testbed", headers=editor).status_code == 204
    hallazgos = f"{BASE_URI}dataset/hallazgos-auditorias-intrusion"
    moved = api.patch(
        "/datasets/hallazgos-auditorias-intrusion", json={"catalog": "piloto"}, headers=editor
    )
    assert moved.status_code == 200
    result = cli_doubles.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert "se omite (dataset dado de baja)" in result.output
    assert MODBUS not in loaded_store.graph_names()
    # El traslado no se deshace y el catálogo creado por la API sigue en el raíz.
    piloto = URIRef(f"{BASE_URI}catalogo/piloto")
    assert (piloto, DCAT.dataset, URIRef(hallazgos)) in loaded_store.get_graph(str(piloto))
    sintetico = set(loaded_store.get_graph(SINTETICO).objects(URIRef(SINTETICO), DCAT.dataset))
    assert URIRef(hallazgos) not in sintetico and URIRef(MODBUS) not in sintetico
    assert (URIRef(ROOT), DCAT.catalog, piloto) in loaded_store.get_graph(ROOT)


def test_load_semantic_skips_a_withdrawn_catalog(
    api: TestClient,
    loaded_store: MemoryStore,
    editor: dict[str, str],
    cli_doubles: CliRunner,
) -> None:
    for slug in (
        "modbus-tcp-testbed",
        "hallazgos-auditorias-intrusion",
        "ejemplos-adversarios-vision",
    ):
        assert api.delete(f"/datasets/{slug}", headers=editor).status_code == 204
    assert api.delete("/catalogs/sintetico", headers=editor).status_code == 204
    result = cli_doubles.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert "se omite (catálogo dado de baja)" in result.output
    assert SINTETICO not in loaded_store.graph_names()
    assert (URIRef(ROOT), DCAT.catalog, URIRef(SINTETICO)) not in loaded_store.get_graph(ROOT)


def test_withdraw_dataset_removes_orphan_files_only_of_its_slug(
    api: TestClient,
    editor: dict[str, str],
    file_storage: DiskStorage,
    session_factory: sessionmaker[Session],
) -> None:
    """QA-49-02: los ficheros de {slug}/ sin fila en distribution_files también se borran,
    y nunca los de otro slug que empiece igual (prueba-otra/…)."""
    import io

    assert fase4_data.publish(api, editor, fase4_data.series(fase4_data.V1)).status_code == 201
    assert fase4_data.upload(api, editor, "abierta", b"con fila").status_code == 201
    file_storage.save("prueba/1.0.0/huerfano", io.BytesIO(b"sin fila"))
    file_storage.save("prueba/9.9.9/csv", io.BytesIO(b"sin fila"))
    file_storage.save("prueba-otra/1.0.0/csv", io.BytesIO(b"otro slug"))
    assert api.delete("/datasets/prueba", headers=editor).status_code == 204
    for key in ("prueba/1.0.0/abierta", "prueba/1.0.0/huerfano", "prueba/9.9.9/csv"):
        assert not file_storage.exists(key), key
    assert not (file_storage.root / "prueba").exists()
    assert file_storage.exists("prueba-otra/1.0.0/csv")
    events = _events(session_factory, AuditAction.DATASET_WITHDRAWN)
    assert sorted(events[0].details["files_deleted"]) == [
        "prueba/1.0.0/abierta",
        "prueba/1.0.0/huerfano",
        "prueba/9.9.9/csv",
    ]
    assert events[0].details["files_not_deleted"] == []
