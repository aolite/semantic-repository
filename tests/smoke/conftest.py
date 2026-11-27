"""Fixtures de la prueba de humo. No escribe nada salvo con ``SMOKE_ALLOW_WRITE=1``."""

from __future__ import annotations

import pytest
from smokelib import WARNINGS, Config, Response, load_config, request


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if WARNINGS:
        terminalreporter.section("AVISOS de la prueba de humo (no son fallos)")
        for message in dict.fromkeys(WARNINGS):
            terminalreporter.write_line(f"  * {message}")


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config()


@pytest.fixture(scope="session")
def get(cfg: Config):
    def _get(path: str, **kwargs: object) -> Response:
        url = path if path.startswith("http") else f"{cfg.api}{path}"
        return request(cfg, "GET", url, **kwargs)  # type: ignore[arg-type]

    return _get


@pytest.fixture(scope="session")
def datasets(get) -> list[dict]:
    response = get("/datasets")
    assert response.status == 200, response.text[:300]
    return response.json()["items"]  # type: ignore[index,return-value]


@pytest.fixture(scope="session")
def vocabularies(get) -> list[dict]:
    response = get("/vocabularies")
    assert response.status == 200, response.text[:300]
    return response.json()["items"]  # type: ignore[index,return-value]


def _login(cfg: Config, user: str, password: str) -> Response:
    return request(
        cfg,
        "POST",
        f"{cfg.api}/auth/token",
        form={"username": user, "password": password},
    )


@pytest.fixture(scope="session")
def editor_token(cfg: Config) -> str:
    if not (cfg.editor_user and cfg.editor_password):
        pytest.skip("sin SMOKE_EDITOR_USER y SMOKE_EDITOR_PASSWORD")
    response = _login(cfg, cfg.editor_user, cfg.editor_password)
    assert response.status == 200, f"login del editor: {response.status}"
    return response.json()["access_token"]  # type: ignore[index]


@pytest.fixture(scope="session")
def member_token(cfg: Config) -> str:
    if not (cfg.member_user and cfg.member_password):
        pytest.skip("sin SMOKE_MEMBER_USER y SMOKE_MEMBER_PASSWORD")
    response = _login(cfg, cfg.member_user, cfg.member_password)
    assert response.status == 200, f"login del miembro: {response.status}"
    return response.json()["access_token"]  # type: ignore[index]
