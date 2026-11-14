from collections.abc import Iterator

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.db import get_db
from app.routers.health import check_fuseki
from app.schemas import ComponentStatus


def test_liveness(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
