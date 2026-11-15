"""La dependencia ``require_role`` que reutilizarán las fases siguientes."""

from collections.abc import Callable, Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import get_db
from app.deps import ROLE_INHERITS, OptionalUser, effective_roles, require_role
from app.models import Role, User
from app.routers import auth
from tests.conftest import DEFAULT_PASSWORD


@pytest.fixture
def mini_client(settings: Settings, session_factory: sessionmaker[Session]) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/publicar")
    def publicar(user: Annotated[User, Depends(require_role(Role.EDITOR, Role.ADMIN))]) -> str:
        return user.username

    @app.get("/publico")
    def publico(user: OptionalUser) -> str:
        return user.username if user else "lector"

    def _get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _login(client: TestClient, username: str) -> dict[str, str]:
    token = client.post(
        "/auth/token", data={"username": username, "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.MIEMBRO, 403), (Role.EDITOR, 200), (Role.ADMIN, 200)],
)
def test_require_role_allows_listed_roles(
    mini_client: TestClient, make_user: Callable[..., User], role: Role, expected: int
) -> None:
    make_user("u", role)
    response = mini_client.get("/publicar", headers=_login(mini_client, "u"))
    assert response.status_code == expected


def test_require_role_anonymous(mini_client: TestClient) -> None:
    assert mini_client.get("/publicar").status_code == 401


def test_optional_user_is_lector_without_token(
    mini_client: TestClient, make_user: Callable[..., User]
) -> None:
    assert mini_client.get("/publico").json() == "lector"
    make_user("ana")
    assert mini_client.get("/publico", headers=_login(mini_client, "ana")).json() == "ana"


def test_optional_user_rejects_invalid_token(mini_client: TestClient) -> None:
    response = mini_client.get("/publico", headers={"Authorization": "Bearer basura"})
    assert response.status_code == 401


def test_require_role_needs_roles() -> None:
    with pytest.raises(ValueError, match="al menos un rol"):
        require_role()


# --- Herencia admin -> editor (decisión del responsable, 2026-11-14) -------------------


@pytest.fixture
def roles_client(settings: Settings, session_factory: sessionmaker[Session]) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/solo-editor")
    def solo_editor(user: Annotated[User, Depends(require_role(Role.EDITOR))]) -> str:
        return user.username

    @app.get("/solo-miembro")
    def solo_miembro(user: Annotated[User, Depends(require_role(Role.MIEMBRO))]) -> str:
        return user.username

    @app.get("/solo-admin")
    def solo_admin(user: Annotated[User, Depends(require_role(Role.ADMIN))]) -> str:
        return user.username

    def _get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


@pytest.mark.parametrize(
    ("path", "role", "expected"),
    [
        # admin hereda los permisos de editor
        ("/solo-editor", Role.EDITOR, 200),
        ("/solo-editor", Role.ADMIN, 200),
        ("/solo-editor", Role.MIEMBRO, 403),
        # ninguna otra herencia: ni editor ni admin heredan de miembro
        ("/solo-miembro", Role.MIEMBRO, 200),
        ("/solo-miembro", Role.EDITOR, 403),
        ("/solo-miembro", Role.ADMIN, 403),
        # editor no hereda de admin
        ("/solo-admin", Role.ADMIN, 200),
        ("/solo-admin", Role.EDITOR, 403),
        ("/solo-admin", Role.MIEMBRO, 403),
    ],
)
def test_role_inheritance_is_only_admin_to_editor(
    roles_client: TestClient,
    make_user: Callable[..., User],
    path: str,
    role: Role,
    expected: int,
) -> None:
    make_user("u", role)
    assert roles_client.get(path, headers=_login(roles_client, "u")).status_code == expected


def test_effective_roles_table() -> None:
    assert effective_roles(Role.ADMIN) == {Role.ADMIN, Role.EDITOR}
    assert effective_roles(Role.EDITOR) == {Role.EDITOR}
    assert effective_roles(Role.MIEMBRO) == {Role.MIEMBRO}
    assert {Role.ADMIN: {Role.EDITOR}} == ROLE_INHERITS
