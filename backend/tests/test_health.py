import tomllib
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app import PYPROJECT_PATH, __version__
from app.config import Settings, get_settings
from app.db import get_db
from app.routers.health import check_fuseki
from app.schemas import ComponentStatus


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Las pruebas de ``APP_COMMIT`` cambian el entorno: que no quede en la caché."""
    yield
    get_settings.cache_clear()


def _pyproject_version() -> str:
    with PYPROJECT_PATH.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_liveness(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_COMMIT", raising=False)
    get_settings.cache_clear()
    response = client.get("/health")
    assert response.status_code == 200
    # Solo estos tres campos: ni rutas, ni variables, ni versiones de dependencias.
    assert response.json() == {"status": "ok", "version": _pyproject_version(), "commit": None}


def test_version_has_a_single_source(client: TestClient) -> None:
    assert __version__ == _pyproject_version()
    assert client.get("/openapi.json").json()["info"]["version"] == __version__


@pytest.mark.parametrize(("raw", "expected"), [("a1b2c3d", "a1b2c3d"), ("  ", None), ("", None)])
def test_liveness_reports_app_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, raw: str, expected: str | None
) -> None:
    monkeypatch.setenv("APP_COMMIT", raw)
    get_settings.cache_clear()
    assert client.get("/health").json()["commit"] == expected


@pytest.mark.parametrize("raw", ["abc def", "x" * 65, "<script>"])
def test_invalid_app_commit_is_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("APP_COMMIT", raw)
    with pytest.raises(ValidationError):
        Settings()


def test_readiness_ok(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["fuseki"]["status"] == "ok"


def test_readiness_fails_when_fuseki_is_down(
    client: TestClient, fuseki_status: dict[str, ComponentStatus]
) -> None:
    fuseki_status["value"] = ComponentStatus(status="error", detail="Fuseki no responde")
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["checks"]["fuseki"]["status"] == "error"
    assert body["checks"]["database"]["status"] == "ok"


def test_readiness_fails_when_database_is_down(client: TestClient) -> None:
    class BrokenSession:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("conexión rechazada"))

    def broken_db() -> Iterator[BrokenSession]:
        yield BrokenSession()

    client.app.dependency_overrides[get_db] = broken_db  # type: ignore[attr-defined]
    response = client.get("/health/ready")
    assert response.status_code == 503
    database = response.json()["checks"]["database"]
    assert database["status"] == "error"
    # No se filtran detalles de la conexión, solo el tipo de error.
    assert "conexión rechazada" not in database["detail"]


def test_check_fuseki_ok(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"head": {}, "boolean": True})

    result = check_fuseki(settings, transport=httpx.MockTransport(handler))
    assert result.status == "ok"
    assert seen[0].url.path == "/itot/query"
    assert seen[0].url.host == "fuseki.test"
    assert seen[0].url.params["query"] == "ASK {}"


def test_check_fuseki_dataset_missing(settings: Settings) -> None:
    result = check_fuseki(settings, transport=httpx.MockTransport(lambda _r: httpx.Response(404)))
    assert result.status == "error"
    assert "404" in (result.detail or "")


def test_check_fuseki_unreachable(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = check_fuseki(settings, transport=httpx.MockTransport(handler))
    assert result.status == "error"
