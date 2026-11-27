"""Fixtures comunes.

Base de datos de pruebas: por defecto, SQLite en memoria (rápido, sin servicios externos,
igual en local y en CI). Los modelos solo usan tipos portables (``Uuid``, ``JSON``,
``Enum`` no nativo con CHECK), y ``test_migrations.py`` comprueba que las migraciones de
Alembic producen exactamente el esquema de los modelos. Para ejecutar la misma batería
contra PostgreSQL, define ``TEST_DATABASE_URL`` (ver ``backend/README.md``).
"""

import os

# La configuración se valida al importar la app: fija el entorno de pruebas antes.
# Valores de relleno, no son credenciales reales.
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_EXPIRE_MINUTES"] = "60"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["FUSEKI_URL"] = "http://fuseki.test:3030"
os.environ["FUSEKI_DATASET"] = "itot"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
# Sin trabajador FAIR en segundo plano: las pruebas llaman a fair.process_pending.
os.environ["FAIR_WORKER_POLL_SECONDS"] = "0"
os.environ.pop("FUJI_USERNAME", None)
os.environ.pop("FUJI_PASSWORD", None)
os.environ.pop("FAIR_TARGET_BASE_URL", None)
os.environ.pop("BASE_URI", None)
os.environ.pop("FUSEKI_USER", None)
os.environ.pop("FUSEKI_PASSWORD", None)
os.environ.pop("FRONTEND_BASE_URL", None)

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from rdflib import Graph, URIRef
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import bajas, ingest, owl_metrics, security, vocab_ingest
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.deps import get_storage, get_triplestore
from app.main import create_app
from app.models import OntologyMetricsRecord, Role, User
from app.routers.health import get_fuseki_checker
from app.routers.sparql import get_query_runner
from app.schemas import ComponentStatus
from app.security import hash_password
from app.sparql_public import MemoryQueryRunner
from app.storage import DiskStorage
from app.triplestore import MemoryStore
from app.uris import Uris

DEFAULT_PASSWORD = "contrasena-de-prueba-larga"

# argon2id con los parámetros de producción (64 MiB, 3 pasadas, 4 hilos) cuesta decenas de
# milisegundos por hash y por verificación, y casi todas las pruebas crean usuarios y
# hacen login: era buena parte del tiempo de la batería. Las pruebas usan argon2id con
# parámetros mínimos (mismo algoritmo, mismo formato «$argon2id$…»). Las que dependen del
# coste real (parámetros de producción, tiempo de login) piden la fixture
# ``production_password_hash``, y test_security.py comprueba los parámetros de producción.
PRODUCTION_PASSWORD_HASH = security._password_hash
PRODUCTION_DUMMY_HASH = security._DUMMY_HASH
security._password_hash = PasswordHash(
    (Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1),)
)
security._DUMMY_HASH = security._password_hash.hash("relleno-de-pruebas")


@pytest.fixture
def production_password_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """argon2id con los parámetros de producción, para esta prueba."""
    monkeypatch.setattr(security, "_password_hash", PRODUCTION_PASSWORD_HASH)
    monkeypatch.setattr(security, "_DUMMY_HASH", PRODUCTION_DUMMY_HASH)


DCAT_RESOURCE = URIRef("http://www.w3.org/ns/dcat#resource")
BASE_URI = "https://semantic.example.org/itot/"  # valor por defecto del proyecto

TESTS_DIR = Path(__file__).resolve().parent
REPO_SEMANTIC_DIR = TESTS_DIR.parent.parent / "semantic"


# Variables de .env.example que solo leen Docker Compose, Caddy o los scripts de copia del
# despliegue del piloto (docker-compose.prod.yml, infra/caddy, infra/scripts), no el backend.
DEPLOY_ONLY_ENV = frozenset(
    {
        "FRONTEND_HOST",
        "API_HOST",
        "CADDY_TLS",
        "PROXY_HTTP_PORT",
        "PROXY_HTTPS_PORT",
        "PROXY_MAX_BODY_RDF",
        "PROXY_MAX_BODY_UPLOAD",
        "BACKUP_DIR",
        "BACKUP_RETENTION_DAYS",
    }
)

# Copia de semantic/data/ de la rama de semantico (datos sintéticos de G2). Las formas
# SHACL no se copian: se usan las de semantic/shapes/ del repositorio.
FIXTURE_DATA_DIR = TESTS_DIR / "fixtures" / "data"
# Copia de semantic/vocabularios, semantic/ontologias y de la forma
# shapes/ontologias-vocabularios.ttl de la rama de semantico (fase 3). Cuando lleguen a
# main, la forma ya estará en semantic/shapes/ y la copia se puede borrar.
FIXTURE_SEMANTIC_DIR = TESTS_DIR / "fixtures" / "semantic"
# Ontología propia del backend con recuentos conocidos (pruebas de métricas).
FIXTURE_COUNTS_ONTOLOGY = TESTS_DIR / "fixtures" / "ontologia-recuentos.ttl"


@pytest.fixture(scope="session", autouse=True)
def semantic_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``SEMANTIC_DIR`` de pruebas: formas reales del repositorio + datos de fixtures."""
    root = tmp_path_factory.mktemp("semantic")
    shutil.copytree(REPO_SEMANTIC_DIR / "shapes", root / "shapes")
    for shape in (FIXTURE_SEMANTIC_DIR / "shapes").glob("*.ttl"):
        shutil.copy(shape, root / "shapes" / shape.name)
    shutil.copytree(FIXTURE_DATA_DIR, root / "data")
    shutil.copytree(FIXTURE_SEMANTIC_DIR / "vocabularios", root / "vocabularios")
    shutil.copytree(FIXTURE_SEMANTIC_DIR / "ontologias", root / "ontologias")
    # Consultas de referencia (fase 4): copia de semantic/consultas/ de semantico.
    shutil.copytree(FIXTURE_SEMANTIC_DIR / "consultas", root / "consultas")
    os.environ["SEMANTIC_DIR"] = str(root)
    ingest.clear_caches()
    return root


@pytest.fixture
def uris() -> Uris:
    return Uris(BASE_URI)


# Catálogo de las pruebas (decisión 49): las series de prueba («prueba», «oculta»…) llevan
# «<catalogo/pruebas> dcat:dataset <serie>», y el backend exige que el catálogo exista.
TEST_CATALOG = "pruebas"
TEST_CATALOG_URI = f"{BASE_URI}catalogo/{TEST_CATALOG}"
MEMBERSHIP = f"<catalogo/{TEST_CATALOG}> <http://www.w3.org/ns/dcat#dataset> <dataset/{{slug}}> .\n"


def membership(slug: str = "prueba") -> str:
    """Triple de pertenencia de la serie ``slug`` al catálogo de pruebas (Turtle)."""
    return MEMBERSHIP.format(slug=slug)


# Catálogos que siembra la fixture ``store``: el de pruebas y ``sintetico`` (el de los datos
# de semantic/, para publicar sus series en un triplestore vacío). ``load_fixture_data`` y
# ``load-semantic`` sustituyen ``sintetico`` por el de data/catalogos/sintetico.ttl.
SEEDED_CATALOGS = (TEST_CATALOG_URI, f"{BASE_URI}catalogo/sintetico")


def seed_test_catalog(store: MemoryStore) -> None:
    """Crea los catálogos de ``SEEDED_CATALOGS`` (sin enlazarlos desde el raíz)."""
    for uri in SEEDED_CATALOGS:
        graph = Graph()
        graph.parse(
            data=f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
<{uri}> a dcat:Catalog ; dct:title "Catálogo de pruebas"@es ;
    dct:description "Catálogo de las pruebas del backend"@es ;
    dct:publisher [ a foaf:Agent ; foaf:name "Pruebas" ] .
""",
            format="turtle",
        )
        store.put_graph(uri, graph)


def user_graphs(store: MemoryStore) -> set[str]:
    """Grafos del triplestore sin los catálogos que siembra la fixture ``store``."""
    return store.graph_names() - set(SEEDED_CATALOGS)


def fake_fuseki_read(request: object) -> str:
    """N-Triples para un Fuseki simulado con ``httpx.MockTransport``: el catálogo de pruebas
    existe (decisión 49: publicar exige que el catálogo exista); el resto, vacío."""
    content = getattr(request, "content", b"").decode()
    if "query=" in content and "catalogo%2Fpruebas%3E" in content and "GRAPH" in content:
        return (
            f"<{TEST_CATALOG_URI}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
            "<http://www.w3.org/ns/dcat#Catalog> .\n"
        )
    return ""


def without_membership(graph: Graph) -> Graph:
    """El grafo sin «<catálogo> dcat:dataset <serie>»: así queda guardada la serie."""
    result = Graph()
    for triple in graph:
        if str(triple[1]) != "http://www.w3.org/ns/dcat#dataset":
            result.add(triple)
    return result


@pytest.fixture
def store() -> MemoryStore:
    """Doble en memoria de Fuseki (rdflib ``Dataset``) con solo el catálogo de pruebas."""
    memory = MemoryStore()
    seed_test_catalog(memory)
    return memory


def seed_synthetic_themes(store: MemoryStore) -> set[str]:
    """Solo los conceptos que usan como ``dcat:theme`` las series sintéticas
    (``<concepto> a skos:Concept`` en el grafo de su esquema), sin el resto del esquema.
    Para las pruebas que publican esas series en un triplestore sin vocabularios: desde
    QA-50-03 un tema de ``{BASE_URI}vocab/`` tiene que ser un concepto vivo. Devuelve los
    grafos sembrados."""
    skos_concept = URIRef("http://www.w3.org/2004/02/skos/core#Concept")
    rdf_type = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    theme = URIRef("http://www.w3.org/ns/dcat#theme")
    graphs: dict[str, Graph] = {}
    for path in sorted((FIXTURE_DATA_DIR / "sintetico").glob("*.ttl")):
        series = Graph().parse(path, format="turtle", publicID=BASE_URI)
        for concept in series.objects(None, theme):
            if isinstance(concept, URIRef) and str(concept).startswith(f"{BASE_URI}vocab/"):
                scheme = str(concept).rsplit("/", 1)[0]
                graphs.setdefault(scheme, Graph()).add((concept, rdf_type, skos_concept))
    for scheme, graph in graphs.items():
        store.append_graph(scheme, graph)
    return set(graphs)


@pytest.fixture
def synthetic_themes(store: MemoryStore) -> set[str]:
    return seed_synthetic_themes(store)


def load_schemes(store: MemoryStore, semantic_dir: Path, uris: Uris) -> None:
    """Cada esquema SKOS de las fixtures en el grafo de su URI (como ``load-semantic``),
    también los auxiliares de ``data/vocab-minimo.ttl``."""
    auxiliary = ingest.parse_file(semantic_dir / "data" / "vocab-minimo.ttl", uris.base)
    for prepared in vocab_ingest.split_schemes(auxiliary, uris):
        ingest.store_graph(store, prepared.uri, prepared.graph)
    paths = sorted((semantic_dir / "vocabularios").glob("*.ttl"))
    paths += sorted((semantic_dir / "vocabularios" / "corp").glob("*.ttl"))
    for path in paths:
        graph = ingest.parse_file(path, uris.base)
        prepared = vocab_ingest.check_scheme_structure(graph, uris, allow_auxiliary=True)
        ingest.store_graph(store, prepared.uri, graph)


def load_ontology_graphs(store: MemoryStore, semantic_dir: Path, uris: Uris) -> None:
    """Versiones de ontología y externas en sus grafos, sin calcular métricas."""
    root = semantic_dir / "ontologias"
    for path in sorted(root.glob("*/*.ttl")):
        graph = ingest.parse_file(path, uris.base)
        prepared = vocab_ingest.check_ontology_structure(graph, uris)
        ingest.store_graph(store, prepared.version_iri, graph)
    externas = ingest.parse_file(root / "externas.ttl", uris.base)
    ingest.store_graph(store, uris.external_ontologies_graph, externas)


def load_fixture_data(store: MemoryStore, semantic_dir: Path, uris: Uris) -> None:
    """Carga esquemas SKOS, catálogo y series como lo haría ``load-semantic``."""
    data = semantic_dir / "data"
    load_schemes(store, semantic_dir, uris)
    catalog = ingest.parse_file(data / "catalogo.ttl", uris.base)
    ingest.store_graph(store, uris.root_catalog, catalog)
    for path in sorted((data / "catalogos").glob("*.ttl")):
        graph = ingest.parse_file(path, uris.base)
        uri = uris.catalog(path.stem)
        # Sin los dcat:dataset del fichero: la pertenencia la aporta cada serie.
        ingest.store_graph(store, uri, ingest.merge_catalog(Graph(), graph, uri))
        # Decisión 50: los esquemas y las ontologías del fichero (dcat:resource), como los
        # deja load-semantic al publicarlos.
        for resource in graph.objects(URIRef(uri), DCAT_RESOURCE):
            bajas.set_resource_membership(store, uris, str(resource), uri)
    for path in sorted((data / "sintetico").glob("*.ttl")):
        graph = ingest.parse_file(path, uris.base)
        ingest.publish(store, ingest.prepare_series(graph, uris, semantic_dir))


# Contenido del triplestore tras cargar las fixtures, calculado una vez por sesión y por
# carpeta ``semantic``. Cargarlo cuesta unos segundos por prueba (SHACL de cada serie en
# un proceso hijo, consultas de pertenencia…) y lo usan cientos de pruebas: cada una
# recibe un ``MemoryStore`` nuevo con una copia de las cuádruplas, idéntico al que dejaría
# la carga. Solo se copia sobre un triplestore recién sembrado; si una prueba ya ha escrito
# algo antes, se carga de verdad.
Quad = tuple[Any, Any, Any, Any]
_SNAPSHOTS: dict[tuple[str, Path], list[Quad]] = {}
_ONTOLOGY_GRAPHS: dict[tuple[str, Path], list[tuple[str, Graph]]] = {}


def _is_pristine(store: MemoryStore) -> bool:
    if store.queries or store.updates or store.graph_names() != set(SEEDED_CATALOGS):
        return False
    fresh = MemoryStore()
    seed_test_catalog(fresh)
    return len(store.dataset) == len(fresh.dataset) and all(
        len(store.dataset.graph(URIRef(uri))) == len(fresh.dataset.graph(URIRef(uri)))
        for uri in SEEDED_CATALOGS
    )


def _load_cached(
    store: MemoryStore, key: tuple[str, Path], load: Callable[[MemoryStore], None]
) -> None:
    if not _is_pristine(store):
        load(store)
        return
    if key not in _SNAPSHOTS:
        loaded = MemoryStore()
        seed_test_catalog(loaded)
        load(loaded)
        _SNAPSHOTS[key] = list(loaded.dataset.quads((None, None, None, None)))
    with store._lock:
        for uri in SEEDED_CATALOGS:
            store.dataset.remove_graph(URIRef(uri))
        store.dataset.addN((s, p, o, store.dataset.graph(g)) for s, p, o, g in _SNAPSHOTS[key])


@pytest.fixture
def loaded_store(store: MemoryStore, semantic_dir: Path, uris: Uris) -> MemoryStore:
    _load_cached(
        store,
        ("loaded", semantic_dir),
        lambda target: load_fixture_data(target, semantic_dir, uris),
    )
    store.queries.clear()
    return store


@pytest.fixture(scope="session")
def itot_metrics(semantic_dir: Path) -> tuple[dict, dict]:
    """Métricas y consistencia de la fixture ``itot`` 1.2.0, calculadas una vez.

    Con Java, la consistencia es la real de Pellet; sin Java, el resultado «no disponible»
    que devuelve el backend en ese caso."""
    uris = Uris(BASE_URI)
    graph = ingest.parse_file(semantic_dir / "ontologias" / "itot" / "1.2.0.ttl", uris.base)
    # Las de la fixture real (se comprueban en test_vocab_read.py).
    metrics = owl_metrics.compute_metrics(graph, uris.ontology("itot"))
    consistency = owl_metrics.check_consistency(
        graph, uris.ontology("itot"), timeout_seconds=120, java_memory_mb=512
    )
    return metrics.to_dict(), consistency.to_dict()


@pytest.fixture
def vocab_store(loaded_store: MemoryStore, semantic_dir: Path, uris: Uris) -> MemoryStore:
    """Catálogo, esquemas, ontologías (todas las versiones) y externas cargados."""
    # load_ontology_graphs solo sustituye grafos enteros: basta con guardar cuáles y con
    # qué tripletas, y volver a escribirlos en cada prueba.
    key = ("vocab", semantic_dir)
    if key not in _ONTOLOGY_GRAPHS:
        recorder = MemoryStore()
        load_ontology_graphs(recorder, semantic_dir, uris)
        _ONTOLOGY_GRAPHS[key] = [
            (uri, recorder.dataset.graph(URIRef(uri))) for uri in sorted(recorder.graph_names())
        ]
    for uri, graph in _ONTOLOGY_GRAPHS[key]:
        loaded_store.put_graph(uri, graph)
    loaded_store.queries.clear()
    return loaded_store


@pytest.fixture
def vocab_metrics(
    session_factory: sessionmaker[Session], itot_metrics: tuple[dict, dict], uris: Uris
) -> None:
    """Métricas guardadas para ``itot`` 1.2.0 (la 1.1.0 queda sin métricas)."""
    metrics, consistency = itot_metrics
    with session_factory() as session:
        session.add(
            OntologyMetricsRecord(
                version_iri=uris.ontology_version("itot", "1.2.0"),
                ontology_iri=uris.ontology("itot"),
                content_hash="0" * 64,
                metrics=metrics,
                consistency=consistency,
                tool="owlready2 (pruebas)",
            )
        )
        session.commit()


def _make_engine() -> Engine:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return create_engine(url)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = _make_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def fuseki_status() -> dict[str, ComponentStatus]:
    """Estado simulado de Fuseki para ``/health/ready``; las pruebas pueden cambiarlo."""
    return {"value": ComponentStatus(status="ok")}


@pytest.fixture
def file_storage(tmp_path: Path) -> DiskStorage:
    """Almacenamiento de distribuciones en disco, en una carpeta temporal por prueba."""
    return DiskStorage(tmp_path / "distribuciones")


@pytest.fixture
def query_runner(store: MemoryStore) -> MemoryQueryRunner:
    """SPARQL público sobre el mismo ``MemoryStore`` (grafo por defecto = unión)."""
    return MemoryQueryRunner(store.dataset)


@pytest.fixture
def client(
    settings: Settings,
    session_factory: sessionmaker[Session],
    fuseki_status: dict[str, ComponentStatus],
    store: MemoryStore,
    file_storage: DiskStorage,
    query_runner: MemoryQueryRunner,
) -> Iterator[TestClient]:
    app = create_app(settings)

    def _get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_fuseki_checker] = lambda: lambda _settings: fuseki_status["value"]
    app.dependency_overrides[get_triplestore] = lambda: store
    app.dependency_overrides[get_storage] = lambda: file_storage
    app.dependency_overrides[get_query_runner] = lambda: query_runner
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def _make_user(
        username: str,
        role: Role = Role.MIEMBRO,
        password: str = DEFAULT_PASSWORD,
        is_active: bool = True,
    ) -> User:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return _make_user


@pytest.fixture
def login(client: TestClient) -> Callable[..., dict[str, str]]:
    """Hace login y devuelve las cabeceras ``Authorization`` listas para usar."""

    def _login(username: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
        response = client.post("/auth/token", data={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
