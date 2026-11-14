import base64
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import AuditAction, AuditEvent, Role, User
from app.security import create_access_token, decode_access_token
from tests.conftest import DEFAULT_PASSWORD


def _audit(session_factory: sessionmaker[Session]) -> list[AuditEvent]:
    with session_factory() as session:
        return list(session.scalars(select(AuditEvent).order_by(AuditEvent.id)))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Login ---------------------------------------------------------------------------


def test_login_success_returns_jwt_with_role(
    client: TestClient,
    settings: Settings,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
) -> None:
    user = make_user("editora", Role.EDITOR)
    response = client.post(
        "/auth/token", data={"username": "editora", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "editor"
    assert body["expires_in"] == settings.jwt_expire_minutes * 60

    claims = jwt.decode(body["access_token"], settings.jwt_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["role"] == "editor"
    assert claims["username"] == "editora"
    assert claims["exp"] - claims["iat"] == settings.jwt_expire_minutes * 60

    events = _audit(session_factory)
    assert [e.action for e in events] == [AuditAction.LOGIN_SUCCESS]
    assert events[0].actor_id == user.id
    assert events[0].actor_username == "editora"


@pytest.mark.parametrize(
    ("username", "password", "reason"),
    [
        ("miembro1", "contrasena-incorrecta", "bad_password"),
        ("no-existe", DEFAULT_PASSWORD, "unknown_user"),
    ],
)
def test_login_failure(
    client: TestClient,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
    username: str,
    password: str,
    reason: str,
) -> None:
    make_user("miembro1")
    response = client.post("/auth/token", data={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña incorrectos"
    assert response.headers["www-authenticate"] == "Bearer"
    assert "access_token" not in response.json()

    events = _audit(session_factory)
    assert len(events) == 1
    assert events[0].action == AuditAction.LOGIN_FAILURE
    assert events[0].actor_id is None
    assert events[0].target_username == username
    assert events[0].details == {"reason": reason}
    # La contraseña probada nunca se guarda.
    assert password not in json.dumps(events[0].details)


def test_login_inactive_user_fails(
    client: TestClient,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
) -> None:
    make_user("baja", is_active=False)
    response = client.post("/auth/token", data={"username": "baja", "password": DEFAULT_PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña incorrectos"
    assert _audit(session_factory)[0].details == {"reason": "inactive_user"}


def test_login_requires_form_fields(client: TestClient) -> None:
    assert client.post("/auth/token", data={"username": "x"}).status_code == 422


def test_password_is_stored_hashed(make_user: Callable[..., User]) -> None:
    user = make_user("hash")
    assert DEFAULT_PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


# --- /auth/me y validación del token ------------------------------------------------------


def test_me_returns_current_user(
    client: TestClient, make_user: Callable[..., User], login: Callable[..., dict[str, str]]
) -> None:
    user = make_user("yo", Role.MIEMBRO)
    response = client.get("/auth/me", headers=login("yo"))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["username"] == "yo"
    assert body["role"] == "miembro"
    assert body["is_active"] is True
    assert "password_hash" not in body


def test_me_without_token(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_token_is_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User]
) -> None:
    user = make_user("caducado")
    past = datetime.now(UTC) - timedelta(minutes=settings.jwt_expire_minutes + 1)
    token, _ = create_access_token(
        settings, user_id=user.id, username=user.username, role=user.role, now=past
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_tampered_payload_is_rejected(
    client: TestClient,
    settings: Settings,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    """Un miembro que cambia su rol a admin en el payload invalida la firma."""
    make_user("tramposo", Role.MIEMBRO)
    token = login("tramposo")["Authorization"].removeprefix("Bearer ")
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["role"] = "admin"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    tampered = f"{header}.{forged}.{signature}"

    assert client.get("/auth/me", headers=_bearer(tampered)).status_code == 401
    assert client.get("/users", headers=_bearer(tampered)).status_code == 401


def test_token_signed_with_other_secret_is_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    user = make_user("otro")
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user.id), "role": "admin", "iat": now, "exp": now + timedelta(minutes=5)},
        "otro-secreto-distinto-del-configurado-000000",
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_unsigned_token_is_rejected(client: TestClient, make_user: Callable[..., User]) -> None:
    user = make_user("sinfirma")
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user.id), "role": "admin", "iat": now, "exp": now + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("token", ["", "basura", "a.b.c"])
def test_malformed_token_is_rejected(client: TestClient, token: str) -> None:
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_token_without_exp_is_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User]
) -> None:
    user = make_user("sinexp")
    token = jwt.encode(
        {"sub": str(user.id), "role": "miembro", "iat": datetime.now(UTC)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_token_for_unknown_user_is_rejected(client: TestClient, settings: Settings) -> None:
    token, _ = create_access_token(
        settings, user_id=uuid.uuid4(), username="fantasma", role=Role.ADMIN
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_token_with_invalid_sub_is_rejected(client: TestClient, settings: Settings) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "no-es-uuid", "role": "admin", "iat": now, "exp": now + timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_decode_roundtrip(settings: Settings) -> None:
    user_id = uuid.uuid4()
    token, _ = create_access_token(settings, user_id=user_id, username="u", role=Role.EDITOR)
    claims = decode_access_token(settings, token)
    assert claims.user_id == user_id
    assert claims.role is Role.EDITOR


# --- Entradas con caracteres de control ------------------------------------------------


@pytest.mark.parametrize("username", ["admin\x00x", "\x00", "admin\x1b[0m", "admin\x7f", "a\x85b"])
def test_login_with_control_chars_is_rejected_and_audited(
    client: TestClient,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
    username: str,
) -> None:
    """NUL rompía la consulta en PostgreSQL (500). Ahora es el 401 genérico, auditado."""
    make_user("admin", Role.ADMIN)
    response = client.post("/auth/token", data={"username": username, "password": DEFAULT_PASSWORD})
    assert response.status_code == 401
    assert response.json() == {"detail": "Usuario o contraseña incorrectos"}
    assert response.headers["www-authenticate"] == "Bearer"

    events = _audit(session_factory)
    assert len(events) == 1
    assert events[0].action == AuditAction.LOGIN_FAILURE
    assert events[0].details == {"reason": "invalid_username"}
    # No se guarda el valor bruto ni se asocia a ninguna cuenta.
    assert events[0].target_username is None
    assert events[0].target_user_id is None
    assert events[0].actor_id is None


def test_login_with_control_chars_in_password_fails_cleanly(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user("admin", Role.ADMIN)
    response = client.post("/auth/token", data={"username": "admin", "password": "x\x00y"})
    assert response.status_code == 401
