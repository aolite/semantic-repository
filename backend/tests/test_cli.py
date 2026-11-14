"""Comando ``create-admin`` para dar de alta el primer admin."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli as cli_module
from app.models import AuditAction, AuditEvent, Role, User

PASSWORD = "contrasena-admin-de-prueba"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _cli_uses_test_db(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)


def _users(session_factory: sessionmaker[Session]) -> list[User]:
    with session_factory() as session:
        return list(session.scalars(select(User)))


def test_create_admin_from_stdin(session_factory: sessionmaker[Session]) -> None:
    result = runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "jefa", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert "Admin 'jefa' creado." in result.output
    assert PASSWORD not in result.output

    users = _users(session_factory)
    assert len(users) == 1
    assert users[0].username == "jefa"
    assert users[0].role is Role.ADMIN
    assert users[0].is_active is True
    assert users[0].password_hash.startswith("$argon2id$")

    with session_factory() as session:
        event = session.scalars(select(AuditEvent)).one()
    assert event.action == AuditAction.USER_CREATED
    assert event.actor_id is None
    assert event.actor_username == "cli"
    assert event.target_username == "jefa"
    assert event.details == {"role": "admin", "via": "cli"}


def test_create_admin_interactive_prompt(session_factory: sessionmaker[Session]) -> None:
    result = runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "jefa"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert PASSWORD not in result.output  # la entrada es oculta
    assert [u.username for u in _users(session_factory)] == ["jefa"]


def test_create_admin_prompt_confirmation_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    result = runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "jefa"],
        input=f"{PASSWORD}\notra-cosa-distinta\n",
    )
    assert result.exit_code != 0
    assert _users(session_factory) == []


def test_create_admin_rejects_short_password(session_factory: sessionmaker[Session]) -> None:
    result = runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "jefa", "--password-stdin"],
        input="corta\n",
    )
    assert result.exit_code == 2
    assert _users(session_factory) == []


def test_create_admin_rejects_invalid_username(session_factory: sessionmaker[Session]) -> None:
    result = runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "Jefa Mayor", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    assert result.exit_code == 2
    assert _users(session_factory) == []


def test_create_admin_duplicate(
    make_user: Callable[..., User], session_factory: sessionmaker[Session]
) -> None:
    make_user("jefa", Role.EDITOR)
    result = runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "jefa", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    assert result.exit_code == 1
    users = _users(session_factory)
    assert len(users) == 1
    assert users[0].role is Role.EDITOR


def test_created_admin_can_manage_users(client: TestClient) -> None:
    runner.invoke(
        cli_module.cli,
        ["create-admin", "--username", "jefa", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    token = client.post("/auth/token", data={"username": "jefa", "password": PASSWORD}).json()
    assert token["role"] == "admin"
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    response = client.post(
        "/users",
        json={"username": "miembro1", "password": "contrasena-miembro-1", "role": "miembro"},
        headers=headers,
    )
    assert response.status_code == 201
