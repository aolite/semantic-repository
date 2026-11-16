import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditAction, AuditEvent, Role, User
from tests.conftest import DEFAULT_PASSWORD

NEW_PASSWORD = "otra-contrasena-de-prueba"


def _audit(session_factory: sessionmaker[Session], action: AuditAction) -> list[AuditEvent]:
    with session_factory() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
            )
        )


@pytest.fixture
def admin_headers(
    make_user: Callable[..., User], login: Callable[..., dict[str, str]]
) -> dict[str, str]:
    make_user("admin1", Role.ADMIN)
    return login("admin1")


# --- Autorización por rol ------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/users", None),
        ("POST", "/users", {"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro"}),
        ("PATCH", f"/users/{uuid.uuid4()}", {"role": "editor"}),
    ],
)
def test_anonymous_is_unauthorized(
    client: TestClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize("role", [Role.MIEMBRO, Role.EDITOR])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/users", None),
        ("POST", "/users", {"username": "nuevo", "password": NEW_PASSWORD, "role": "admin"}),
        ("PATCH", f"/users/{uuid.uuid4()}", {"role": "admin"}),
    ],
)
def test_non_admin_is_forbidden(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
    role: Role,
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    make_user("usuario", role)
    response = client.request(method, path, json=body, headers=login("usuario"))
    assert response.status_code == 403
    assert _audit(session_factory, AuditAction.USER_CREATED) == []


# --- Listado y alta ------------------------------------------------------------------


def test_admin_lists_users(
    client: TestClient, make_user: Callable[..., User], admin_headers: dict[str, str]
) -> None:
    make_user("bea", Role.EDITOR)
    response = client.get("/users", headers=admin_headers)
    assert response.status_code == 200
    users = response.json()
    assert [u["username"] for u in users] == ["admin1", "bea"]
    assert all("password_hash" not in u for u in users)


def test_admin_creates_user(
    client: TestClient,
    admin_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/users",
        json={"username": "nuevo.miembro", "password": NEW_PASSWORD, "role": "miembro"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "nuevo.miembro"
    assert body["role"] == "miembro"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body

    events = _audit(session_factory, AuditAction.USER_CREATED)
    assert len(events) == 1
    assert events[0].actor_username == "admin1"
    assert events[0].target_username == "nuevo.miembro"
    assert events[0].details == {"role": "miembro", "via": "api"}

    # El nuevo usuario puede hacer login.
    login_response = client.post(
        "/auth/token", data={"username": "nuevo.miembro", "password": NEW_PASSWORD}
    )
    assert login_response.status_code == 200
    assert login_response.json()["role"] == "miembro"


def test_create_duplicate_username(client: TestClient, admin_headers: dict[str, str]) -> None:
    payload = {"username": "admin1", "password": NEW_PASSWORD, "role": "editor"}
    response = client.post("/users", json=payload, headers=admin_headers)
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "corta", "password": "corta", "role": "miembro"},
        {"username": "Mayusculas", "password": NEW_PASSWORD, "role": "miembro"},
        {"username": "ab", "password": NEW_PASSWORD, "role": "miembro"},
        {"username": "lector1", "password": NEW_PASSWORD, "role": "lector"},
        {"username": "superuser", "password": NEW_PASSWORD, "role": "root"},
        {"username": "extra", "password": NEW_PASSWORD, "role": "miembro", "is_active": False},
        {"username": "sinrol", "password": NEW_PASSWORD},
    ],
)
def test_create_user_validation(
    client: TestClient, admin_headers: dict[str, str], payload: dict[str, object]
) -> None:
    assert client.post("/users", json=payload, headers=admin_headers).status_code == 422


# --- Cambios de rol y de estado --------------------------------------------------------


def test_admin_changes_role(
    client: TestClient,
    make_user: Callable[..., User],
    admin_headers: dict[str, str],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    target = make_user("carla", Role.MIEMBRO)
    response = client.patch(f"/users/{target.id}", json={"role": "editor"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "editor"

    events = _audit(session_factory, AuditAction.ROLE_CHANGED)
    assert len(events) == 1
    assert events[0].actor_username == "admin1"
    assert events[0].target_user_id == target.id
    assert events[0].details == {"from": "miembro", "to": "editor"}

    assert client.get("/auth/me", headers=login("carla")).json()["role"] == "editor"


def test_same_role_is_not_audited(
    client: TestClient,
    make_user: Callable[..., User],
    admin_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    target = make_user("dani", Role.EDITOR)
    response = client.patch(f"/users/{target.id}", json={"role": "editor"}, headers=admin_headers)
    assert response.status_code == 200
    assert _audit(session_factory, AuditAction.ROLE_CHANGED) == []


def test_role_change_applies_to_existing_tokens(
    client: TestClient,
    make_user: Callable[..., User],
    admin_headers: dict[str, str],
    login: Callable[..., dict[str, str]],
) -> None:
    """Degradar a un admin le quita el acceso al momento. Desde la fase 4 (decisión 18),
    el cambio de rol invalida los tokens emitidos antes (401); con uno nuevo, 403."""
    other = make_user("admin2", Role.ADMIN)
    other_headers = login("admin2")
    assert client.get("/users", headers=other_headers).status_code == 200

    client.patch(f"/users/{other.id}", json={"role": "miembro"}, headers=admin_headers)
    assert client.get("/users", headers=other_headers).status_code == 401
    assert client.get("/users", headers=login("admin2")).status_code == 403


def test_deactivate_and_reactivate(
    client: TestClient,
    make_user: Callable[..., User],
    admin_headers: dict[str, str],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    target = make_user("eva", Role.MIEMBRO)
    eva_headers = login("eva")

    response = client.patch(f"/users/{target.id}", json={"is_active": False}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    # La baja invalida los tokens ya emitidos y bloquea el login.
    assert client.get("/auth/me", headers=eva_headers).status_code == 401
    login_response = client.post(
        "/auth/token", data={"username": "eva", "password": DEFAULT_PASSWORD}
    )
    assert login_response.status_code == 401

    response = client.patch(f"/users/{target.id}", json={"is_active": True}, headers=admin_headers)
    assert response.json()["is_active"] is True

    deactivated = _audit(session_factory, AuditAction.USER_DEACTIVATED)
    reactivated = _audit(session_factory, AuditAction.USER_REACTIVATED)
    assert [e.target_username for e in deactivated] == ["eva"]
    assert [e.target_username for e in reactivated] == ["eva"]
    assert deactivated[0].actor_username == "admin1"


@pytest.mark.parametrize("payload", [{"role": "editor"}, {"is_active": False}])
def test_admin_cannot_lock_themselves_out(
    client: TestClient,
    admin_headers: dict[str, str],
    session_factory: sessionmaker[Session],
    payload: dict[str, object],
) -> None:
    with session_factory() as session:
        admin = session.scalars(select(User).where(User.username == "admin1")).one()
    response = client.patch(f"/users/{admin.id}", json=payload, headers=admin_headers)
    assert response.status_code == 409


def test_patch_unknown_user(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.patch(
        f"/users/{uuid.uuid4()}", json={"role": "editor"}, headers=admin_headers
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload", [{"role": "lector"}, {"password": NEW_PASSWORD}, {"username": "otro"}]
)
def test_patch_validation(
    client: TestClient,
    make_user: Callable[..., User],
    admin_headers: dict[str, str],
    payload: dict[str, object],
) -> None:
    target = make_user("fran")
    response = client.patch(f"/users/{target.id}", json=payload, headers=admin_headers)
    assert response.status_code == 422


# --- Entradas con caracteres de control y respuestas 422 ---------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "nuevo\x00x", "password": NEW_PASSWORD, "role": "miembro"},
        {"username": "\x00", "password": NEW_PASSWORD, "role": "miembro"},
        {"username": "nuevo", "password": NEW_PASSWORD + "\x00", "role": "miembro"},
        {"username": "nuevo", "password": NEW_PASSWORD + "\x1b", "role": "miembro"},
    ],
)
def test_create_user_with_control_chars_is_rejected(
    client: TestClient,
    admin_headers: dict[str, str],
    session_factory: sessionmaker[Session],
    payload: dict[str, str],
) -> None:
    response = client.post("/users", json=payload, headers=admin_headers)
    assert response.status_code == 422
    assert _audit(session_factory, AuditAction.USER_CREATED) == []
    with session_factory() as session:
        assert session.scalars(select(User).where(User.username != "admin1")).all() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "corta", "password": "secreto-1", "role": "miembro"},
        {"username": "Mayusculas", "password": "secreto-que-no-debe-volver", "role": "miembro"},
        {"username": "nulo\x00", "password": "secreto-que-no-debe-volver", "role": "root"},
    ],
)
def test_validation_errors_never_echo_input(
    client: TestClient, admin_headers: dict[str, str], payload: dict[str, str]
) -> None:
    response = client.post("/users", json=payload, headers=admin_headers)
    assert response.status_code == 422
    body = response.json()
    assert body["detail"], body
    for error in body["detail"]:
        assert set(error) == {"type", "loc", "msg"}
    assert "secreto" not in response.text
