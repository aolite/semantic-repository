"""La dependencia ``require_role`` que reutilizarán las fases siguientes."""

from collections.abc import Callable, Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import get_db
from app.deps import OptionalUser, require_role
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
