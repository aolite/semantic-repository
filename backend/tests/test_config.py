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


@pytest.mark.parametrize(("algorithm", "minimum"), [("HS256", 32), ("HS384", 48), ("HS512", 64)])
def test_jwt_secret_minimum_depends_on_algorithm(
    monkeypatch: pytest.MonkeyPatch, algorithm: str, minimum: int
) -> None:
    with pytest.raises(ValidationError, match=f"al menos {minimum} bytes"):
        _settings(monkeypatch, JWT_ALGORITHM=algorithm, JWT_SECRET="x" * (minimum - 1))
    settings = _settings(monkeypatch, JWT_ALGORITHM=algorithm, JWT_SECRET="x" * minimum)
    assert settings.jwt_algorithm == algorithm


def test_jwt_secret_length_is_measured_in_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    # 16 caracteres de 2 bytes = 32 bytes: suficiente para HS256.
    _settings(monkeypatch, JWT_ALGORITHM="HS256", JWT_SECRET="ñ" * 16)
    with pytest.raises(ValidationError, match="jwt_secret"):
        _settings(monkeypatch, JWT_ALGORITHM="HS256", JWT_SECRET="ñ" * 15)


def test_short_secret_error_names_variable_without_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "y" * 40  # válido para HS256, corto para HS512
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError, match="JWT_SECRET") as exc_info:
            get_settings()
        assert secret not in str(exc_info.value)
    finally:
        get_settings.cache_clear()


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


# --- Fase 2: Fuseki, SEMANTIC_DIR y FRONTEND_BASE_URL ---------------------------------


def test_fuseki_credentials_are_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FUSEKI_USER", raising=False)
    monkeypatch.delenv("FUSEKI_PASSWORD", raising=False)
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET)
    assert settings.fuseki_write_credentials is None
    # Vacías equivalen a no definidas; con solo una tampoco hay credenciales.
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET, FUSEKI_USER="u", FUSEKI_PASSWORD="")
    assert settings.fuseki_write_credentials is None


def test_fuseki_password_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        JWT_SECRET=VALID_SECRET,
        FUSEKI_USER="backend",
        FUSEKI_PASSWORD="clave-ficticia-de-fuseki",
    )
    assert settings.fuseki_write_credentials == ("backend", "clave-ficticia-de-fuseki")
    assert "clave-ficticia-de-fuseki" not in repr(settings)


def test_semantic_dir_default_and_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEMANTIC_DIR", raising=False)
    backend_dir = Path(__file__).resolve().parent.parent
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET)
    assert settings.semantic_dir == backend_dir.parent / "semantic"
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET, SEMANTIC_DIR="../semantic")
    assert settings.semantic_dir == (backend_dir / ".." / "semantic").resolve()
    settings = _settings(monkeypatch, JWT_SECRET=VALID_SECRET, SEMANTIC_DIR="/semantic")
    assert settings.semantic_dir == Path("/semantic")


def test_frontend_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)
    assert _settings(monkeypatch, JWT_SECRET=VALID_SECRET).frontend_base_url == (
        "http://localhost:5173"
    )
    settings = _settings(
        monkeypatch, JWT_SECRET=VALID_SECRET, FRONTEND_BASE_URL="https://web.example.org/"
    )
    assert settings.frontend_base_url == "https://web.example.org"
