"""QA-49-01 y QA-49-03: escrituras simultáneas del CRUD de catálogos (decisión 49).

Antes, las altas y bajas leían el grafo entero (raíz, bajas, catálogo) y lo reescribían:
con varias peticiones a la vez se perdían enlaces del raíz y lápidas, y un slug dado de
baja volvía a ser reutilizable. Ahora las escrituras de ``app.bajas`` añaden y quitan
triples sin reescribir (``append_graph`` y SPARQL Update) y las operaciones que comprueban
y escriben van con ``app.write_lock``.

``SlowStore`` espera dentro de cada lectura de un grafo entero: si alguna escritura vuelve
a ser «leer y reescribir», las peticiones paralelas se pisan y estas pruebas fallan.

QA-49-03: el pool de la base de datos de este módulo tiene **una sola conexión**
(``POOL_SIZE``). Si una petición que espera el bloqueo retuviera su conexión, o el bloqueo
necesitara otra del pool, las escrituras simultáneas y las lecturas se quedarían sin
conexión (``QueuePool limit``) y estas pruebas fallarían.
"""

import os
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import bajas, write_lock
from app.config import Settings
from app.db import Base
from app.deps import get_triplestore
from app.models import Role, User
from app.triplestore import MemoryStore
from app.uris import DCAT, Uris
from tests.conftest import BASE_URI

PARALLEL = 8
POOL_SIZE = 1
POOL_TIMEOUT = 10
BURST = 20
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
    args: dict = {} if url.startswith("postgresql") else {"connect_args": {"timeout": 30}}
    # QA-49-03: pool mínimo, para que retener una conexión mientras se espera se note.
    engine = create_engine(
        url, pool_size=POOL_SIZE, max_overflow=0, pool_timeout=POOL_TIMEOUT, **args
    )
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


# --- QA-49-03: el bloqueo no agota el pool ni bloquea las lecturas -------------------------


def test_many_simultaneous_writes_do_not_exhaust_the_pool_nor_block_reads(
    api: TestClient, slow_store: SlowStore, editor: dict[str, str]
) -> None:
    """20 altas a la vez con un pool de una conexión: todas 201, y GET /auth/me responde
    mientras tanto sin esperar a las escrituras."""

    def write(n: int):
        return api.post("/catalogs", json=_catalog(f"rafaga-{n}"), headers=editor)

    def read(_n: int) -> float:
        started = time.monotonic()
        response = api.get("/auth/me", headers=editor)
        assert response.status_code == 200, response.text
        return time.monotonic() - started

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=BURST + 5) as pool:
        writes = [pool.submit(write, n) for n in range(BURST)]
        time.sleep(0.05)  # las lecturas, con las escrituras ya esperando el bloqueo
        reads = [pool.submit(read, n) for n in range(5)]
        codes = [future.result().status_code for future in writes]
        latencies = [future.result() for future in reads]
    elapsed = time.monotonic() - started
    assert codes == [201] * BURST
    assert max(latencies) < POOL_TIMEOUT / 2, latencies
    assert elapsed < POOL_TIMEOUT * 2, elapsed
    linked = set(slow_store.get_graph(str(ROOT)).objects(ROOT, DCAT.catalog))
    assert {URIRef(f"{BASE_URI}catalogo/rafaga-{n}") for n in range(BURST)} <= linked


def test_lock_timeout_is_a_clear_503(
    api: TestClient,
    editor: dict[str, str],
    settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si otra escritura retiene el bloqueo más de CATALOG_LOCK_TIMEOUT_SECONDS, 503."""
    monkeypatch.setattr(settings, "catalog_lock_timeout_seconds", 0.3)
    holding, release = threading.Event(), threading.Event()

    def hold() -> None:
        with session_factory() as session, write_lock.catalog_write_lock(session):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert holding.wait(5)
        response = api.post("/catalogs", json=_catalog("espera"), headers=editor)
    finally:
        release.set()
        holder.join(10)
    assert response.status_code == 503
    assert "CATALOG_LOCK_TIMEOUT_SECONDS" in response.json()["detail"]
    assert response.headers["retry-after"] == "5"
    # Liberado el bloqueo, la misma alta funciona.
    assert api.post("/catalogs", json=_catalog("espera"), headers=editor).status_code == 201


def test_lock_refuses_a_session_with_pending_changes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(User(username="pendiente", password_hash="x", role=Role.MIEMBRO))
        with (
            pytest.raises(RuntimeError, match="sin confirmar"),
            write_lock.catalog_write_lock(session),
        ):
            pass


def test_lock_releases_the_session_connection_before_waiting(
    session_factory: sessionmaker[Session],
) -> None:
    """La transacción de la sesión se cierra antes de esperar: su conexión vuelve al pool."""
    with session_factory() as session:
        session.scalars(select(User)).all()
        assert session.in_transaction()
        with write_lock.catalog_write_lock(session):
            assert not session.in_transaction()


def test_advisory_connection_is_closed_if_locking_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si falla pg_advisory_lock (p. ej. vence lock_timeout), la conexión se cierra y se
    informa con CatalogLockTimeoutError."""

    class FakeConnection:
        closed = False

        def execute(self, statement, _params=None):
            if "pg_advisory_lock" in str(statement):
                raise OperationalError("SELECT pg_advisory_lock", {}, Exception("lock timeout"))

        def commit(self) -> None:
            pass

        def close(self) -> None:
            FakeConnection.closed = True

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setattr(write_lock, "_lock_engine", lambda _url: FakeEngine())
    engine = create_engine("postgresql://usuario@db.invalid/itot")
    with pytest.raises(write_lock.CatalogLockTimeoutError):
        write_lock._acquire_advisory(engine, 1.0, 1.0)
    assert FakeConnection.closed


def test_writers_waiting_for_the_lock_hold_no_pool_connection(
    api: TestClient,
    editor: dict[str, str],
    engine: Engine,
    session_factory: sessionmaker[Session],
) -> None:
    """Mientras una escritura tiene el bloqueo, las que esperan no retienen conexiones del
    pool (de una sola conexión) y GET /auth/me responde enseguida. Antes, cada petición que
    esperaba guardaba la conexión con la que leyó el usuario, «idle in transaction»."""
    holding, release = threading.Event(), threading.Event()

    def hold() -> None:
        with session_factory() as session, write_lock.catalog_write_lock(session):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert holding.wait(5)
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        writes = [
            pool.submit(
                lambda n: api.post("/catalogs", json=_catalog(f"espera-{n}"), headers=editor), n
            )
            for n in range(PARALLEL)
        ]
        try:
            time.sleep(0.5)  # todas autenticadas y esperando el bloqueo
            assert engine.pool.checkedout() == 0
            started = time.monotonic()
            me = api.get("/auth/me", headers=editor)
            assert me.status_code == 200
            assert time.monotonic() - started < 2
        finally:
            release.set()
            holder.join(10)
        assert [future.result().status_code for future in writes] == [201] * PARALLEL
