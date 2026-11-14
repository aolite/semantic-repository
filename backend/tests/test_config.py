from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_BASE_URI, ConfigurationError, Settings, get_settings
from app.main import create_app

VALID_SECRET = "x" * 32


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_jwt_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_jwt_secret_too_short_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="jwt_secret"):
        _settings(monkeypatch, JWT_SECRET="corto")


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        _settings(monkeypatch, JWT_SECRET=VALID_SECRET)


def test_only_hmac_algorithms_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="jwt_algorithm"):
        _settings(monkeypatch, JWT_SECRET=VALID_SECRET, JWT_ALGORITHM="none")


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("BASE_URI", "JWT_ALGORITHM", "JWT_EXPIRE_MINUTES", "STORAGE_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET)
    assert settings.base_uri == DEFAULT_BASE_URI
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes == 60
    assert settings.storage_backend == "disk"
    assert settings.storage_disk_path == "/data/distributions"


def test_base_uri_gets_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch, JWT_SECRET=VALID_SECRET, BASE_URI="https://semantic.example.org/itot"
    )
    assert settings.base_uri == "https://semantic.example.org/itot/"


def test_base_uri_must_be_http(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="base_uri"):
        _settings(monkeypatch, JWT_SECRET=VALID_SECRET, BASE_URI="urn:itot:")


def test_cors_origins_are_split_by_comma(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        JWT_SECRET=VALID_SECRET,
        CORS_ORIGINS="http://localhost:5173, http://localhost:4173 ,",
    )
    assert settings.cors_origins_list == ["http://localhost:5173", "http://localhost:4173"]


def test_get_settings_error_does_not_leak_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://itot:valor-ficticio@db:5432/itot")
    monkeypatch.chdir(tmp_path)  # directorio sin .env
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError, match="JWT_SECRET") as exc_info:
            get_settings()
        assert "valor-ficticio" not in str(exc_info.value)
    finally:
        get_settings.cache_clear()


def test_app_does_not_start_without_jwt_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError, match="JWT_SECRET"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_secret_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET)
    assert VALID_SECRET not in repr(settings)
