"""Fase 4: evaluación FAIR con F-UJI (decisión 45).

F-UJI se simula con ``httpx.MockTransport`` y una respuesta con su formato real
(``tests/fixtures/fuji/evaluate-respuesta.json``). Fuente del formato, F-UJI v4.0.1
(proyecto ``pangaea-data-publisher/fuji``):

- Envoltorio: esquema ``FAIRResults`` de ``fuji_server/yaml/openapi.yaml`` (``test_id``,
  ``request``, ``resolved_url``, ``start_timestamp``, ``end_timestamp``,
  ``metric_specification``, ``metric_version``, ``software_version``, ``total_metrics``,
  ``summary``, ``results``, ``harvested_metadata``), que construye
  ``fuji_server/controllers/fair_object_controller.py``.
- ``summary``: copiado tal cual del resumen grabado de una evaluación real (2023-09-22)
  que guarda ``tests/functional/test_evaluation.py`` de F-UJI; es la salida de
  ``FAIRCheck.get_assessment_summary`` (``score_percent``, ``maturity``…, por categoría,
  principio y ``FAIR``).
- Los valores del envoltorio (identificador, fechas, ``test_id``) son de prueba, y
  ``results`` va vacío para no copiar el detalle de cada métrica.
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import fair
from app.config import Settings
from app.models import AuditAction, AuditEvent, FairEvaluation, Role, User
from tests.conftest import BASE_URI
from tests.fase4_data import V1, V2, editor_headers, publish, series

FIXTURE = Path(__file__).parent / "fixtures" / "fuji" / "evaluate-respuesta.json"
REPORT = json.loads(FIXTURE.read_text(encoding="utf-8"))
VERSION = f"{BASE_URI}dataset/prueba/1.0.0"
# Lo que se pasa a F-UJI: el RDF de la versión bajo FAIR_TARGET_BASE_URL (QA-G4-01).
TARGET = "http://backend:8000/datasets/prueba/rdf?version=1.0.0&format=turtle"


@pytest.fixture
def fuji_settings(settings: Settings) -> Settings:
    settings.fuji_username = "usuario-prueba"
    settings.fuji_password = "clave-prueba"
    settings.fair_target_base_url = "http://backend:8000/"
    return settings


def _client(fuji_settings: Settings, handler: Callable[[httpx.Request], httpx.Response]):
    return fair.FujiClient(fuji_settings, transport=httpx.MockTransport(handler))


@pytest.fixture
def requests_seen() -> list[httpx.Request]:
    return []


@pytest.fixture
def ok_client(fuji_settings: Settings, requests_seen: list[httpx.Request]) -> fair.FujiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(200, json=REPORT)

    return _client(fuji_settings, handler)


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    return editor_headers(make_user, login)


def test_parse_report_uses_fuji_summary_as_is() -> None:
    scores = fair.parse_report(REPORT)
    assert scores.total == 70.83
    assert (scores.findable, scores.accessible, scores.interoperable, scores.reusable) == (
        85.71,
        66.67,
        100.0,
        50.0,
    )
    assert scores.maturity == "2.25"
    assert scores.evaluator == "F-UJI 4.0.1 (metrics_v0.5)"


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"summary": {}},
        {"summary": {"score_percent": {"F": 10}}},
        {"summary": {"score_percent": {"FAIR": "70"}}},
        {"summary": {"score_percent": {"FAIR": 170}}},
        {"summary": {"score_percent": {"FAIR": 50, "F": True}}},
        [],
    ],
)
def test_invalid_reports_are_rejected(report: object) -> None:
    with pytest.raises(fair.FujiError):
        fair.parse_report(report)


def test_publish_enqueues_and_worker_evaluates(
    client: TestClient,
    editor,
    session_factory: sessionmaker[Session],
    fuji_settings: Settings,
    ok_client: fair.FujiClient,
    requests_seen: list[httpx.Request],
) -> None:
    publish(client, editor, series(V1))
    detail = client.get("/datasets/prueba").json()
    assert detail["version"]["fair"]["status"] == "pending"
    assert fair.process_pending(session_factory, fuji_settings, ok_client) == 1

    sent = json.loads(requests_seen[0].content)
    assert sent["object_identifier"] == TARGET
    assert sent["metadata_service_endpoint"] == "http://backend:8000/sparql"
    assert sent["metadata_service_type"] == "sparql"
    assert sent["use_datacite"] is False
    assert requests_seen[0].url.path.endswith("/evaluate")
    assert requests_seen[0].headers["authorization"].startswith("Basic ")

    summary = client.get("/datasets/prueba").json()["version"]["fair"]
    assert summary["status"] == "done"
    assert summary["total"] == 70.83
    assert summary["findable"] == 85.71
    assert summary["maturity"] == "2.25"
    assert summary["evaluator"] == "F-UJI 4.0.1 (metrics_v0.5)"
    assert summary["evaluated_at"]
    assert summary["report_url"] == "/datasets/prueba/versions/1.0.0/fair/report"
    served = client.get(summary["report_url"]).json()
    assert "backend:8000" not in json.dumps(served)  # sin el host interno
    assert served["request"]["object_identifier"] == VERSION
    assert served["request"]["metadata_service_endpoint"] == f"{BASE_URI}sparql"
    assert served["summary"] == REPORT["summary"]
    card = client.get("/datasets").json()["items"][0]
    assert card["fair_total"] == 70.83

    with session_factory() as session:
        row = session.scalars(select(FairEvaluation)).one()
        assert row.evaluated_url == TARGET
        event = session.scalars(
            select(AuditEvent).where(AuditEvent.action == AuditAction.FAIR_EVALUATED.value)
        ).one()
        assert event.details["status"] == "done"
        assert event.actor_username == "editora"


def test_existing_versions_are_not_reevaluated(client: TestClient, editor, db: Session) -> None:
    publish(client, editor, series(V1))
    publish(client, editor, series(V1, V2, last="2.0.0"))
    publish(client, editor, series(V1, V2, last="2.0.0"))
    uris = db.scalars(select(FairEvaluation.version_uri)).all()
    assert sorted(uris) == [VERSION, f"{BASE_URI}dataset/prueba/2.0.0"]


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("x", request=r)),
            fair.ERROR_UNREACHABLE,
        ),
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("x", request=r)), fair.ERROR_TIMEOUT),
        (lambda r: httpx.Response(500, text="Traceback /usr/src/app/x.py"), "F-UJI respondió 500"),
        (lambda r: httpx.Response(200, text="no es json"), fair.ERROR_INVALID),
        (lambda r: httpx.Response(200, json={"summary": {}}), fair.ERROR_INVALID),
        (lambda r: httpx.Response(401), fair.ERROR_AUTH),
    ],
)
def test_fuji_errors_leave_failed_with_sanitized_message(
    client: TestClient,
    editor,
    session_factory: sessionmaker[Session],
    fuji_settings: Settings,
    handler: Callable[[httpx.Request], httpx.Response],
    message: str,
) -> None:
    publish(client, editor, series(V1))
    fair.process_pending(session_factory, fuji_settings, _client(fuji_settings, handler))
    with session_factory() as session:
        row = session.scalars(select(FairEvaluation)).one()
        assert row.status == "failed"
        assert row.error == message
        assert "Traceback" not in row.error and row.score_total is None
    summary = client.get("/datasets/prueba").json()["version"]["fair"]
    assert summary["status"] == "failed"
    assert summary["total"] is None and summary["report_url"] is None
    assert client.get("/datasets/prueba/versions/1.0.0/fair/report").status_code == 404


def test_missing_credentials_fail_cleanly(
    client: TestClient, editor, session_factory: sessionmaker[Session], settings: Settings
) -> None:
    publish(client, editor, series(V1))
    fair.process_pending(session_factory, settings)
    with session_factory() as session:
        assert session.scalars(select(FairEvaluation.error)).one() == fair.ERROR_NO_CREDENTIALS


def test_reevaluation_endpoint(
    client: TestClient,
    editor,
    session_factory: sessionmaker[Session],
    fuji_settings: Settings,
    ok_client: fair.FujiClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    publish(client, editor, series(V1))
    fair.process_pending(session_factory, fuji_settings, ok_client)
    path = "/datasets/prueba/versions/1.0.0/fair"
    assert client.post(path).status_code == 401
    make_user("socia", Role.MIEMBRO)
    assert client.post(path, headers=login("socia")).status_code == 403
    response = client.post(path, headers=editor)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["total"] == 70.83  # la última done sigue a la vista
    assert client.post(path, headers=editor).status_code == 202  # no duplica
    with session_factory() as session:
        assert len(session.scalars(select(FairEvaluation)).all()) == 2
    assert client.post("/datasets/prueba/versions/9.9.9/fair", headers=editor).status_code == 404


def test_not_evaluated_and_report_404(loaded_store, client: TestClient) -> None:
    detail = client.get("/datasets/modbus-tcp-testbed").json()
    assert detail["version"]["fair"]["status"] == "not_evaluated"
    assert detail["version"]["fair"]["total"] is None
    response = client.get("/datasets/modbus-tcp-testbed/versions/2.1.0/fair/report")
    assert response.status_code == 404


def test_stale_running_evaluation_is_failed(
    session_factory: sessionmaker[Session], fuji_settings: Settings
) -> None:
    from datetime import UTC, datetime, timedelta

    with session_factory() as session:
        session.add(
            FairEvaluation(
                version_uri=VERSION,
                status="running",
                started_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
        session.commit()
        assert fair.fail_stale(session, fuji_settings) == 1
        assert session.scalars(select(FairEvaluation.status)).one() == "failed"


def test_worker_survives_errors(fuji_settings: Settings) -> None:
    calls = []

    def broken_factory():
        calls.append(1)
        raise RuntimeError("base de datos caída")

    fuji_settings.fair_worker_poll_seconds = 0.01
    worker = fair.FairWorker(broken_factory, fuji_settings)
    worker.start()
    import time

    deadline = time.monotonic() + 2
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert len(calls) >= 3
