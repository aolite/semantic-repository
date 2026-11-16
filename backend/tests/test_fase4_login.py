"""Fase 4: bloqueo de login y revocación de tokens (decisión 18)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditAction, AuditEvent, LoginAttempt, Role, User
from tests.conftest import DEFAULT_PASSWORD


def _login(client: TestClient, username: str, password: str, ip_header: dict | None = None):
    return client.post(
        "/auth/token", data={"username": username, "password": password}, headers=ip_header or {}
    )


@pytest.fixture
def admin(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("jefa", Role.ADMIN)
    return login("jefa")


def test_lockout_after_max_failures(
    client: TestClient, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures):
        assert _login(client, "ana", "mala-contrasena-x").status_code == 401
    response = _login(client, "ana", DEFAULT_PASSWORD)  # correcta, pero bloqueada
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= settings.login_lockout_minutes * 60
    # X-Forwarded-For no cambia la IP de la conexión.
    spoofed = _login(client, "ana", DEFAULT_PASSWORD, {"X-Forwarded-For": "198.51.100.7"})
    assert spoofed.status_code == 429
    actions = [e.action for e in db.scalars(select(AuditEvent))]
    assert actions.count(AuditAction.LOGIN_LOCKED.value) == 1


def test_lockout_is_per_normalized_username(
    client: TestClient, make_user: Callable[..., User], settings: Settings
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures):
        _login(client, "ANA ", "mala-contrasena-x")
    assert _login(client, "ana", DEFAULT_PASSWORD).status_code == 429


def test_lockout_expires(
    client: TestClient, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures):
        _login(client, "ana", "mala-contrasena-x")
    row = db.scalars(select(LoginAttempt)).one()
    row.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert _login(client, "ana", DEFAULT_PASSWORD).status_code == 200


def test_success_resets_counter(
    client: TestClient, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures - 1):
        _login(client, "ana", "mala-contrasena-x")
    assert _login(client, "ana", DEFAULT_PASSWORD).status_code == 200
    assert db.scalars(select(LoginAttempt)).all() == []
    assert _login(client, "ana", "mala-contrasena-x").status_code == 401


def test_old_failures_outside_window_do_not_count(
    client: TestClient, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures - 1):
        _login(client, "ana", "mala-contrasena-x")
    row = db.scalars(select(LoginAttempt)).one()
    row.window_start = datetime.now(UTC) - timedelta(minutes=settings.login_window_minutes + 1)
    db.commit()
    assert _login(client, "ana", "mala-contrasena-x").status_code == 401
    assert _login(client, "ana", DEFAULT_PASSWORD).status_code == 200


def test_failure_audit_keeps_sanitized_username(client: TestClient, db: Session) -> None:
    _login(client, "nadie\x07" + "x" * 100, "mala-contrasena-x")
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.LOGIN_FAILURE.value)
    ).one()
    assert event.target_username == ("nadie" + "x" * 100)[:64]


# --- Revocación ---------------------------------------------------------------------------


def _user_id(db: Session, username: str):
    return db.scalars(select(User.id).where(User.username == username)).one()


def test_deactivation_revokes_tokens_and_reactivation_does_not_revive(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    admin,
    db: Session,
) -> None:
    make_user("ana")
    old = login("ana")
    uid = _user_id(db, "ana")
    assert (
        client.patch(f"/users/{uid}", json={"is_active": False}, headers=admin).status_code == 200
    )
    assert client.patch(f"/users/{uid}", json={"is_active": True}, headers=admin).status_code == 200
    assert client.get("/auth/me", headers=old).status_code == 401
    fresh = login("ana")  # justo después, en el mismo segundo: vale
    assert client.get("/auth/me", headers=fresh).status_code == 200


def test_role_change_revokes_tokens(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    admin,
    db: Session,
) -> None:
    make_user("ana", Role.EDITOR)
    old = login("ana")
    uid = _user_id(db, "ana")
    assert client.patch(f"/users/{uid}", json={"role": "miembro"}, headers=admin).status_code == 200
    assert client.get("/auth/me", headers=old).status_code == 401
    assert client.get("/auth/me", headers=login("ana")).status_code == 200
