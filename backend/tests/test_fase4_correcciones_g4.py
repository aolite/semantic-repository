"""Correcciones de la revisión G4 (QA-G4-01, -02, -03, -05 y observaciones de endurecimiento).

Todo es ficticio y local: Fuseki y F-UJI se simulan (``MemoryStore``, ``MemoryQueryRunner``
y ``httpx.MockTransport``).
"""

import io
import json
import logging
import logging.config
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import distributions, fair, login_guard, sparql_public
from app.config import Settings
from app.log_filters import RedactTokenFilter, redact
from app.models import AuditAction, AuditEvent, FairEvaluation, LoginAttempt, User
from app.storage import DiskStorage, OutsideRootError, StorageError
from app.triplestore import MemoryStore
from app.uris import Uris
from tests.conftest import BASE_URI, DEFAULT_PASSWORD
from tests.fase4_data import V1, editor_headers, publish, series

BACKEND_DIR = Path(__file__).resolve().parents[1]
CSV = b"a,b\r\n1,2\r\n"
VERSION = f"{BASE_URI}dataset/prueba/1.0.0"
INTERNAL = "http://backend:8000/"


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    return editor_headers(make_user, login)


@pytest.fixture
def published(client: TestClient, editor) -> dict[str, str]:
    assert publish(client, editor, series(V1)).status_code == 201
    return editor


# --- QA-G4-01: F-UJI evalúa el RDF de la versión ------------------------------------------


@pytest.fixture
def fuji_settings(settings: Settings) -> Settings:
    settings.fuji_username = "usuario-prueba"
    settings.fuji_password = "clave-prueba"
    settings.fair_target_base_url = INTERNAL
    return settings


def test_evaluation_target_is_the_version_rdf_under_fair_target(fuji_settings: Settings) -> None:
    assert fair.evaluation_target(fuji_settings, VERSION) == (
        f"{INTERNAL}datasets/prueba/rdf?version=1.0.0&format=turtle"
    )
    # Algo que no es una versión de dataset: solo se cambia la base.
    other = f"{BASE_URI}onto/itot/1.0.0"
    assert fair.evaluation_target(fuji_settings, other) == f"{INTERNAL}onto/itot/1.0.0"


def test_evaluation_target_without_fair_target_uses_base_uri(settings: Settings) -> None:
    settings.fair_target_base_url = ""
    assert fair.evaluation_target(settings, VERSION) == (
        f"{BASE_URI}datasets/prueba/rdf?version=1.0.0&format=turtle"
    )


def test_evaluation_target_answers_rdf_with_fuji_accept(
    client: TestClient, published, fuji_settings: Settings
) -> None:
    """F-UJI pide la URL con ``Accept: text/html, */*``: debe recibir RDF, no un 303."""
    path = fair.evaluation_target(fuji_settings, VERSION).removeprefix(INTERNAL)
    for accept in ("text/html, */*", "application/rdf+xml", "application/ld+json"):
        response = client.get(f"/{path}", headers={"Accept": accept}, follow_redirects=False)
        assert response.status_code == 200, accept
        assert response.headers["content-type"].startswith("text/turtle")
        graph = Graph().parse(data=response.text, format="turtle")
        assert (URIRef(VERSION), None, None) in graph


def test_worker_sends_the_rdf_url_and_stores_it(
    client: TestClient,
    published,
    session_factory: sessionmaker[Session],
    fuji_settings: Settings,
) -> None:
    sent: list[dict] = []
    target = f"{INTERNAL}datasets/prueba/rdf?version=1.0.0&format=turtle"
    report = {
        "request": {"object_identifier": target, "metadata_service_endpoint": f"{INTERNAL}sparql"},
        "resolved_url": target,
        "software_version": "4.0.1",
        "summary": {"score_percent": {"FAIR": 52.08}, "maturity": {"FAIR": 2}},
        "results": [{"output": f"Recurso en {INTERNAL.rstrip('/')}"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=report)

    worker_client = fair.FujiClient(fuji_settings, transport=httpx.MockTransport(handler))
    assert fair.process_pending(session_factory, fuji_settings, worker_client) == 1
    assert sent[0]["object_identifier"] == target
    assert sent[0]["metadata_service_endpoint"] == f"{INTERNAL}sparql"
    with session_factory() as session:
        row = session.scalars(select(FairEvaluation)).one()
        assert row.evaluated_url == target
        assert row.report == report  # se guarda tal cual

    # El informe público no revela el host interno.
    served = client.get("/datasets/prueba/versions/1.0.0/fair/report").json()
    text = json.dumps(served)
    assert "backend:8000" not in text
    assert served["request"]["object_identifier"] == VERSION
    assert served["resolved_url"] == VERSION
    assert served["request"]["metadata_service_endpoint"] == f"{BASE_URI}sparql"
    assert served["results"][0]["output"] == f"Recurso en {BASE_URI.rstrip('/')}"


def test_public_report_unchanged_without_internal_base(settings: Settings) -> None:
    settings.fair_target_base_url = ""
    report = {"request": {"object_identifier": VERSION}}
    assert fair.public_report(settings, report) == report


@pytest.mark.parametrize(
    ("path", "uri"),
    [
        ("/dataset/prueba", f"{BASE_URI}dataset/prueba"),
        ("/dataset/prueba/1.0.0", VERSION),
        ("/dataset/prueba/1.0.0/abierta", f"{VERSION}/abierta"),
    ],
)
@pytest.mark.parametrize("accept", ["text/html, */*", "text/turtle", "application/ld+json"])
def test_persistent_uris_carry_signposting(
    client: TestClient, published, path: str, uri: str, accept: str
) -> None:
    response = client.get(path, headers={"Accept": accept}, follow_redirects=False)
    assert response.status_code in (200, 303)
    link = response.headers["link"]
    assert f'<{uri}>; rel="cite-as"' in link
    for media in ("text/turtle", "application/ld+json", "application/rdf+xml"):
        assert f'<{uri}>; rel="describedby"; type="{media}"' in link


@pytest.mark.parametrize(
    ("accept", "parse_format"),
    [("application/rdf+xml", "xml"), ("application/n-triples", "nt")],
)
def test_sparql_describe_and_construct_in_rdfxml_and_ntriples(
    client: TestClient, published, accept: str, parse_format: str
) -> None:
    for query in (
        f"DESCRIBE <{VERSION}>",
        f"CONSTRUCT {{ <{VERSION}> ?p ?o }} WHERE {{ <{VERSION}> ?p ?o }}",
    ):
        response = client.get("/sparql", params={"query": query}, headers={"Accept": accept})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(accept)
        graph = Graph().parse(data=response.text, format=parse_format)
        assert (URIRef(VERSION), None, None) in graph


def test_sparql_rdfxml_that_cannot_be_written_gives_406(
    client: TestClient, store: MemoryStore, uris: Uris
) -> None:
    graph = Graph()
    # Un predicado que termina en «/» no se puede escribir como QName en RDF/XML.
    graph.add((URIRef(f"{BASE_URI}x"), URIRef("http://ejemplo.org/p/"), URIRef(f"{BASE_URI}y")))
    store.put_graph(f"{BASE_URI}grafo-raro", graph)
    query = f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{BASE_URI}grafo-raro> {{ ?s ?p ?o }} }}"
    response = client.get(
        "/sparql", params={"query": query}, headers={"Accept": "application/rdf+xml"}
    )
    assert response.status_code == 406
    assert client.get("/sparql", params={"query": query}).status_code == 200  # Turtle


# --- QA-G4-03: SELECT grandes en streaming -----------------------------------------------


def _runner(payload: bytes, chunk: int = 7) -> sparql_public.FusekiQueryRunner:
    def handler(_request: httpx.Request) -> httpx.Response:
        pieces = [payload[i : i + chunk] for i in range(0, len(payload), chunk)]
        return httpx.Response(200, stream=httpx.ByteStream(b"".join(pieces)))

    return sparql_public.FusekiQueryRunner(
        "http://fuseki.test:3030", "itot", transport=httpx.MockTransport(handler)
    )


SELECT = sparql_public.validate("SELECT ?s WHERE { ?s ?p ?o }", BASE_URI)
ROW = {"s": {"type": "uri", "value": "http://ejemplo.org/" + "x" * 100}}


def test_select_is_cut_at_max_rows() -> None:
    data = {"head": {"vars": ["s"]}, "results": {"bindings": [ROW] * 50}}
    result = _runner(json.dumps(data).encode()).run(SELECT, max_rows=5, timeout=5)
    assert result.truncated and result.bindings == [ROW] * 5 and result.variables == ["s"]


def test_select_exactly_max_rows_is_not_truncated() -> None:
    data = {"head": {"vars": ["s"]}, "results": {"bindings": [ROW] * 5}}
    result = _runner(json.dumps(data).encode()).run(SELECT, max_rows=5, timeout=5)
    assert not result.truncated and len(result.bindings) == 5


def test_select_over_byte_cap_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sparql_public, "MAX_RESPONSE_BYTES", 2000)
    data = {"head": {"vars": ["s"]}, "results": {"bindings": [ROW] * 500}}
    result = _runner(json.dumps(data).encode(), chunk=4096).run(SELECT, max_rows=10_000, timeout=5)
    assert result.truncated and 0 < len(result.bindings) < 500


def test_select_whose_first_row_exceeds_cap_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sparql_public, "MAX_RESPONSE_BYTES", 50)
    data = {"head": {"vars": ["s"]}, "results": {"bindings": [ROW]}}
    with pytest.raises(sparql_public.SparqlRequestError):
        _runner(json.dumps(data).encode()).run(SELECT, max_rows=10, timeout=5)


def test_select_with_results_before_head_and_unicode() -> None:
    row = {"s": {"type": "literal", "value": "señal ✓", "xml:lang": "es"}}
    payload = json.dumps(
        {"results": {"bindings": [row, row]}, "head": {"vars": ["s"]}}, ensure_ascii=False
    ).encode()
    full = _runner(payload, chunk=3).run(SELECT, max_rows=5, timeout=5)
    assert full.bindings == [row, row] and full.variables == ["s"] and not full.truncated
    cut = _runner(payload, chunk=3).run(SELECT, max_rows=1, timeout=5)
    assert cut.truncated and cut.variables == ["s"]  # deducidas de las filas


def test_ask_and_empty_select() -> None:
    ask = sparql_public.validate("ASK { ?s ?p ?o }", BASE_URI)
    assert _runner(b'{"head": {}, "boolean": true}').run(ask, max_rows=5, timeout=5).boolean
    empty = _runner(b'{"head": {"vars": []}, "results": {"bindings": []}}').run(
        SELECT, max_rows=5, timeout=5
    )
    assert empty.bindings == [] and not empty.truncated


@pytest.mark.parametrize(
    "payload", [b"no es json", b'{"head": {"vars": ["s"]}, "results": {"bindings": [1', b"[]"]
)
def test_invalid_select_json_is_a_backend_error(payload: bytes) -> None:
    with pytest.raises(sparql_public.SparqlBackendError):
        _runner(payload).run(SELECT, max_rows=5, timeout=5)


# --- QA-G4-02: el log de acceso no guarda el token ---------------------------------------


def test_entrypoint_uses_the_redacting_log_config() -> None:
    entrypoint = (BACKEND_DIR / "docker-entrypoint.sh").read_text(encoding="utf-8")
    command = next(line for line in entrypoint.splitlines() if line.startswith("exec uvicorn"))
    assert "--log-config app/log_config.json" in command
    config = json.loads((BACKEND_DIR / "app" / "log_config.json").read_text(encoding="utf-8"))
    for handler in ("default", "access"):
        assert "redact_token" in config["handlers"][handler]["filters"]


def test_access_log_hides_the_token(capsys: pytest.CaptureFixture[str]) -> None:
    config = json.loads((BACKEND_DIR / "app" / "log_config.json").read_text(encoding="utf-8"))
    logging.config.dictConfig(config)
    secret = "eyJhbGciOiJIUzI1NiJ9.cHJ1ZWJh.ZmlybWE"
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:5000",
        "GET",
        f"/dataset/prueba/1.0.0/abierta/fichero?token={secret}&x=1",
        "1.1",
        200,
    )
    out = capsys.readouterr().out
    assert secret not in out
    assert "token=[oculto]&x=1" in out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/a?token=abc", "/a?token=[oculto]"),
        ("/a?x=1&TOKEN=abc#f", "/a?x=1&TOKEN=[oculto]#f"),
        ("/a?mytoken=abc", "/a?mytoken=abc"),
        ("/a?token=", "/a?token=[oculto]"),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_filter_handles_dict_args() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "%(u)s", None, None)
    record.args = {"u": "/a?token=abc"}
    assert RedactTokenFilter().filter(record)
    assert record.getMessage() == "/a?token=[oculto]"


# --- QA-G4-05: subidas simultáneas -------------------------------------------------------


def _lose_the_race(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    """La primera lectura del registro no lo ve (otra subida lo inserta justo después)."""
    real_get = session.get
    calls = {"n": 0}

    def get(entity, ident, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_get(entity, ident, **kwargs)

    monkeypatch.setattr(session, "get", get)


def test_concurrent_same_upload_is_idempotent(
    client: TestClient,
    published,
    store: MemoryStore,
    uris: Uris,
    session_factory: sessionmaker[Session],
    file_storage: DiskStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = distributions.lookup(store, uris, "prueba", "1.0.0", "abierta")
    with session_factory() as winner:
        assert distributions.upload(winner, file_storage, info, io.BytesIO(CSV)).created
    with session_factory() as loser:
        _lose_the_race(monkeypatch, loser)
        result = distributions.upload(loser, file_storage, info, io.BytesIO(CSV))
        assert not result.created
    with session_factory() as session:
        uploads = session.scalars(
            select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_UPLOADED.value)
        ).all()
        assert len(uploads) == 1


def test_concurrent_different_upload_is_409_and_keeps_the_first_file(
    client: TestClient,
    published,
    store: MemoryStore,
    uris: Uris,
    session_factory: sessionmaker[Session],
    file_storage: DiskStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = distributions.lookup(store, uris, "prueba", "1.0.0", "abierta")
    with session_factory() as winner:
        distributions.upload(winner, file_storage, info, io.BytesIO(CSV))
    with session_factory() as loser:
        _lose_the_race(monkeypatch, loser)
        with pytest.raises(distributions.FileExistsConflictError):
            distributions.upload(loser, file_storage, info, io.BytesIO(b"otro contenido"))
    assert b"".join(file_storage.open_stream(info.storage_key)) == CSV


def test_failed_storage_write_leaves_no_record(
    client: TestClient,
    published,
    store: MemoryStore,
    uris: Uris,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    file_storage: DiskStorage,
) -> None:
    info = distributions.lookup(store, uris, "prueba", "1.0.0", "abierta")

    def broken(_key: str, _source: object) -> None:
        raise StorageError("No se puede escribir en el almacenamiento de disco")

    monkeypatch.setattr(file_storage, "save", broken)
    with pytest.raises(StorageError):
        distributions.upload(db, file_storage, info, io.BytesIO(CSV))
    assert db.get(distributions.DistributionFile, info.storage_key) is None


# --- Enlaces simbólicos fuera de la raíz --------------------------------------------------


def test_symlink_escaping_root_is_not_found(tmp_path: Path) -> None:
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto").write_bytes(b"no")
    storage = DiskStorage(tmp_path / "raiz")
    (tmp_path / "raiz" / "prueba" / "1.0.0").mkdir(parents=True)
    (tmp_path / "raiz" / "prueba" / "1.0.0" / "abierta").symlink_to(outside / "secreto")
    key = "prueba/1.0.0/abierta"
    with pytest.raises(FileNotFoundError):
        storage.open_stream(key)
    with pytest.raises(OutsideRootError):
        storage.size(key)
    assert storage.exists(key) is False
    with pytest.raises(StorageError):
        storage.save(key, io.BytesIO(b"x"))
    assert (outside / "secreto").read_bytes() == b"no"


def test_download_through_escaping_symlink_is_404(
    client: TestClient, published, file_storage: DiskStorage, tmp_path: Path
) -> None:
    assert (
        client.put(
            "/datasets/prueba/versions/1.0.0/distributions/abierta/file",
            files={"file": ("a.csv", CSV, "text/csv")},
            headers=published,
        ).status_code
        == 201
    )
    path = file_storage.root / "prueba" / "1.0.0" / "abierta"
    path.unlink()
    secret = tmp_path / "secreto"
    secret.write_bytes(b"no")
    path.symlink_to(secret)
    assert client.get("/dataset/prueba/1.0.0/abierta/fichero").status_code == 404


# --- Login: purga de login_attempts y auditoría del bloqueo ------------------------------


def test_blocked_attempts_do_not_write_audit_rows(
    client: TestClient, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures):
        client.post("/auth/token", data={"username": "ana", "password": "mala-contrasena-x"})
    before = len(db.scalars(select(AuditEvent)).all())
    for _ in range(5):
        response = client.post(
            "/auth/token", data={"username": "ana", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 429
    db.expire_all()
    assert len(db.scalars(select(AuditEvent)).all()) == before
    locked = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.LOGIN_LOCKED.value)
    ).all()
    assert len(locked) == 1


def test_old_login_attempts_are_purged(
    client: TestClient, settings: Settings, db: Session, make_user: Callable[..., User]
) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(minutes=settings.login_window_minutes + 1)
    db.add_all(
        [
            # Ventana caducada y sin bloqueo: se purga.
            LoginAttempt(username="vieja", ip="192.0.2.1", failures=2, window_start=old),
            # Bloqueo caducado: se purga.
            LoginAttempt(
                username="caducada",
                ip="192.0.2.2",
                failures=5,
                window_start=old,
                locked_until=now - timedelta(minutes=1),
            ),
            # Bloqueo vigente: se queda aunque la ventana sea antigua.
            LoginAttempt(
                username="bloqueada",
                ip="192.0.2.3",
                failures=5,
                window_start=old,
                locked_until=now + timedelta(minutes=5),
            ),
            # Ventana vigente: se queda.
            LoginAttempt(username="reciente", ip="192.0.2.4", failures=1, window_start=now),
        ]
    )
    db.commit()
    client.post("/auth/token", data={"username": "otra", "password": "mala-contrasena-x"})
    db.expire_all()
    left = {row.username for row in db.scalars(select(LoginAttempt))}
    assert left == {"bloqueada", "reciente", "otra"}


def test_purge_keeps_the_pair_being_registered(settings: Settings, db: Session) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(minutes=settings.login_window_minutes + 1)
    db.add(LoginAttempt(username="ana", ip="192.0.2.9", failures=3, window_start=old))
    db.commit()
    assert login_guard.locked_for(db, "ana", "192.0.2.9") is None  # carga la fila
    assert login_guard.register_failure(db, settings, "ana", "192.0.2.9") is False
    db.commit()
    row = db.get(LoginAttempt, ("ana", "192.0.2.9"))
    assert row is not None and row.failures == 1  # ventana reiniciada, no borrada
