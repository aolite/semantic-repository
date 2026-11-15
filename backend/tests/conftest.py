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
os.environ.pop("BASE_URI", None)
os.environ.pop("FUSEKI_USER", None)
os.environ.pop("FUSEKI_PASSWORD", None)
os.environ.pop("FRONTEND_BASE_URL", None)

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import ingest, owl_metrics, vocab_ingest
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.deps import get_triplestore
from app.main import create_app
from app.models import OntologyMetricsRecord, Role, User
from app.routers.health import get_fuseki_checker
from app.schemas import ComponentStatus
from app.security import hash_password
from app.triplestore import MemoryStore
from app.uris import Uris

DEFAULT_PASSWORD = "contrasena-de-prueba-larga"
BASE_URI = "https://semantic.example.org/itot/"  # valor por defecto del proyecto

TESTS_DIR = Path(__file__).resolve().parent
REPO_SEMANTIC_DIR = TESTS_DIR.parent.parent / "semantic"
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
    os.environ["SEMANTIC_DIR"] = str(root)
    ingest.clear_caches()
    return root


@pytest.fixture
def uris() -> Uris:
    return Uris(BASE_URI)


@pytest.fixture
def store() -> MemoryStore:
    """Doble en memoria de Fuseki (rdflib ``Dataset``), vacío en cada prueba."""
    return MemoryStore()


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
        prepared = vocab_ingest.check_scheme_structure(graph, uris)
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
    ingest.store_graph(store, uris.catalog, catalog)
    for path in sorted((data / "sintetico").glob("*.ttl")):
        graph = ingest.parse_file(path, uris.base)
        ingest.publish(store, ingest.prepare_series(graph, uris, semantic_dir))


@pytest.fixture
def loaded_store(store: MemoryStore, semantic_dir: Path, uris: Uris) -> MemoryStore:
    load_fixture_data(store, semantic_dir, uris)
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
    load_ontology_graphs(loaded_store, semantic_dir, uris)
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
def client(
    settings: Settings,
    session_factory: sessionmaker[Session],
    fuseki_status: dict[str, ComponentStatus],
    store: MemoryStore,
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
