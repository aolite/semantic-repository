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

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import create_app
from app.models import Role, User
from app.routers.health import get_fuseki_checker
from app.schemas import ComponentStatus
from app.security import hash_password

DEFAULT_PASSWORD = "contrasena-de-prueba-larga"


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
