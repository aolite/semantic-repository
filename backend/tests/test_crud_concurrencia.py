"""QA-49-01: escrituras simultáneas del CRUD de catálogos (decisión 49).

Antes, las altas y bajas leían el grafo entero (raíz, bajas, catálogo) y lo reescribían:
con varias peticiones a la vez se perdían enlaces del raíz y lápidas, y un slug dado de
baja volvía a ser reutilizable. Ahora las escrituras de ``app.bajas`` añaden y quitan
triples sin reescribir (``append_graph`` y SPARQL Update) y las operaciones que comprueban
y escriben van con ``app.write_lock``.

``SlowStore`` espera dentro de cada lectura de un grafo entero: si alguna escritura vuelve
a ser «leer y reescribir», las peticiones paralelas se pisan y estas pruebas fallan.
"""

import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from sqlalchemy import Engine, create_engine

from app import bajas
from app.db import Base
from app.deps import get_triplestore
from app.models import Role, User
from app.triplestore import MemoryStore
from app.uris import DCAT, Uris
from tests.conftest import BASE_URI

PARALLEL = 8
ROOT = URIRef(f"{BASE_URI}catalogo")


class SlowStore(MemoryStore):
    """MemoryStore cuya lectura de un grafo entero tarda: agranda la ventana entre leer y
    escribir de cualquier «leer y reescribir»."""

    def get_graph(self, graph_uri: str) -> Graph:
        graph = super().get_graph(graph_uri)
        time.sleep(0.02)
        return graph


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """SQLite en fichero, con una conexión por hilo: el de conftest (en memoria con
    ``StaticPool``) comparte una sola conexión y no admite peticiones simultáneas. Con
    ``TEST_DATABASE_URL`` (PostgreSQL) se usa ese, y el bloqueo es el advisory lock."""
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'concurrencia.db'}"
    args = {} if url.startswith("postgresql") else {"connect_args": {"timeout": 30}}
    engine = create_engine(url, **args)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def slow_store(loaded_store: MemoryStore) -> SlowStore:
    slow = SlowStore()
    for graph in loaded_store.dataset.graphs():
        if len(graph) and isinstance(graph.identifier, URIRef):
            target = slow.dataset.graph(graph.identifier)
            for triple in graph:
                target.add(triple)
    return slow


@pytest.fixture
def api(client: TestClient, slow_store: SlowStore) -> Iterator[TestClient]:
    client.app.dependency_overrides[get_triplestore] = lambda: slow_store
    yield client


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("editora", Role.EDITOR)
    return login("editora")


def _catalog(slug: str) -> dict[str, str]:
    return {"slug": slug, "title": f"Catálogo {slug}", "description": "D", "publisher_name": "P"}


def _parallel(function: Callable[[int], object]) -> list:
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        return list(pool.map(function, range(PARALLEL)))


# --- Funciones de app.bajas ----------------------------------------------------------------


def test_parallel_root_links_and_tombstones_are_not_lost(slow_store: SlowStore) -> None:
    uris = Uris(BASE_URI)
    catalogs = [uris.catalog(f"paralelo-{n}") for n in range(PARALLEL)]
    _parallel(lambda n: bajas.add_to_root(slow_store, uris, catalogs[n]))
    _parallel(
        lambda n: bajas.add_tombstone(
            slow_store, uris, bajas.tombstone_graph(catalogs[n], [Literal(f"T{n}")])
        )
    )
    linked = set(slow_store.get_graph(str(ROOT)).objects(ROOT, DCAT.catalog))
    assert {URIRef(c) for c in catalogs} <= linked
    assert set(catalogs) <= bajas.withdrawn_uris(slow_store, uris)
    _parallel(lambda n: bajas.remove_from_root(slow_store, uris, catalogs[n]))
    linked = set(slow_store.get_graph(str(ROOT)).objects(ROOT, DCAT.catalog))
    assert not {URIRef(c) for c in catalogs} & linked
    assert URIRef(f"{BASE_URI}catalogo/sintetico") in linked  # lo demás sigue


def test_parallel_memberships_are_not_lost(slow_store: SlowStore) -> None:
    uris = Uris(BASE_URI)
    catalog = uris.catalog("sintetico")
    series = [uris.series(f"paralela-{n}") for n in range(PARALLEL)]
    _parallel(lambda n: bajas.add_membership(slow_store, catalog, series[n]))
    members = set(slow_store.get_graph(catalog).objects(URIRef(catalog), DCAT.dataset))
    assert {URIRef(s) for s in series} <= members and len(members) == 3 + PARALLEL
    # Mover cada una a otro catálogo es una sola petición de Update.
    target = uris.catalog("pruebas")
    _parallel(lambda n: bajas.set_membership(slow_store, uris, series[n], target))
    moved = set(slow_store.get_graph(target).objects(URIRef(target), DCAT.dataset))
    assert {URIRef(s) for s in series} <= moved
    left = set(slow_store.get_graph(catalog).objects(URIRef(catalog), DCAT.dataset))
    assert len(left) == 3


def test_writes_do_not_rewrite_shared_graphs(slow_store: SlowStore) -> None:
    """Ninguna escritura de app.bajas sustituye el raíz, el de bajas ni un catálogo."""
    uris = Uris(BASE_URI)
    puts: list[str] = []
    original = slow_store.put_graph

    def spy(uri: str, graph: Graph) -> None:
        puts.append(uri)
        original(uri, graph)

    slow_store.put_graph = spy  # type: ignore[method-assign]
    catalog = uris.catalog("paralelo")
    bajas.add_to_root(slow_store, uris, catalog)
    bajas.remove_from_root(slow_store, uris, catalog)
    bajas.add_tombstone(slow_store, uris, bajas.tombstone_graph(catalog, [Literal("T")]))
    bajas.add_membership(slow_store, uris.catalog("sintetico"), uris.series("x"))
    bajas.remove_membership(slow_store, uris.catalog("sintetico"), uris.series("x"))
    bajas.set_membership(slow_store, uris, uris.series("x"), uris.catalog("pruebas"))
    assert puts == []


# --- API: altas y bajas simultáneas ------------------------------------------------------


def test_simultaneous_catalog_creations_keep_every_root_link(
    api: TestClient, slow_store: SlowStore, editor: dict[str, str]
) -> None:
    responses = _parallel(
        lambda n: api.post("/catalogs", json=_catalog(f"simultaneo-{n}"), headers=editor)
    )
    assert [r.status_code for r in responses] == [201] * PARALLEL
    linked = set(slow_store.get_graph(str(ROOT)).objects(ROOT, DCAT.catalog))
    expected = {URIRef(f"{BASE_URI}catalogo/simultaneo-{n}") for n in range(PARALLEL)}
    assert expected <= linked


def test_simultaneous_withdrawals_keep_every_tombstone(
    api: TestClient, slow_store: SlowStore, editor: dict[str, str]
) -> None:
    for n in range(PARALLEL):
        assert api.post("/catalogs", json=_catalog(f"baja-{n}"), headers=editor).status_code == 201
    responses = _parallel(lambda n: api.delete(f"/catalogs/baja-{n}", headers=editor))
    assert [r.status_code for r in responses] == [204] * PARALLEL
    uris = Uris(BASE_URI)
    withdrawn = bajas.withdrawn_uris(slow_store, uris)
    assert {uris.catalog(f"baja-{n}") for n in range(PARALLEL)} <= withdrawn
    # Ningún slug dado de baja se puede reutilizar.
    again = _parallel(lambda n: api.post("/catalogs", json=_catalog(f"baja-{n}"), headers=editor))
    assert {r.status_code for r in again} == {409}
    assert {r.json()["kind"] for r in again} == {"withdrawn"}


def test_same_slug_created_at_once_only_once(
    api: TestClient, slow_store: SlowStore, editor: dict[str, str]
) -> None:
    """Comprobar «slug libre» y crear van juntos (app.write_lock): una sola alta."""
    responses = _parallel(lambda _n: api.post("/catalogs", json=_catalog("unico"), headers=editor))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * (PARALLEL - 1)
    assert {r.json()["kind"] for r in responses if r.status_code == 409} == {"slug_in_use"}


def test_withdraw_and_move_into_catalog_do_not_interleave(
    api: TestClient, slow_store: SlowStore, editor: dict[str, str]
) -> None:
    """Dar de baja un catálogo y mover un dataset a él a la vez: nunca acaban los dos con
    éxito (un dataset colgado de un catálogo dado de baja)."""
    assert api.post("/catalogs", json=_catalog("carrera"), headers=editor).status_code == 201

    def act(n: int):
        if n % 2:
            return api.delete("/catalogs/carrera", headers=editor)
        return api.patch(
            "/datasets/modbus-tcp-testbed", json={"catalog": "carrera"}, headers=editor
        )

    responses = _parallel(act)
    withdrawn = [r for r in responses if r.request.method == "DELETE" and r.status_code == 204]
    moved = [r for r in responses if r.request.method == "PATCH" and r.status_code == 200]
    assert not (withdrawn and moved)
    uris = Uris(BASE_URI)
    if withdrawn:
        assert uris.catalog("carrera") in bajas.withdrawn_uris(slow_store, uris)
        assert bajas.series_catalogs(slow_store, uris, uris.series("modbus-tcp-testbed")) == {
            uris.catalog("sintetico")
        }
