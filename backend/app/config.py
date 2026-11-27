"""Configuración de la aplicación, leída siempre de variables de entorno.

Ningún valor secreto tiene valor por defecto: ``JWT_SECRET`` y ``DATABASE_URL``
son obligatorias y la aplicación no arranca sin ellas.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"

# Carpeta ``backend/``. Las rutas relativas de ``SEMANTIC_DIR`` se resuelven contra ella.
BACKEND_DIR = Path(__file__).resolve().parent.parent

JwtAlgorithm = Literal["HS256", "HS384", "HS512"]

# Longitud mínima del secreto HMAC en bytes: el tamaño de salida de cada función hash
# (RFC 7518, sección 3.2).
JWT_SECRET_MIN_BYTES: dict[str, int] = {"HS256": 32, "HS384": 48, "HS512": 64}


class Settings(BaseSettings):
    """Variables de entorno del backend (ver ``backend/README.md``)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # URIs persistentes: todas se construyen a partir de esta base.
    base_uri: str = DEFAULT_BASE_URI

    # PostgreSQL (usuarios y auditoría). Obligatoria.
    database_url: str = Field(min_length=1, repr=False)

    # Triplestore. Las consultas van a ``/query`` sin credenciales; las escrituras, a
    # ``/data`` (Graph Store Protocol) con autenticación Basic. Las credenciales son
    # opcionales al arrancar: sin ellas la lectura funciona y la ingesta falla con un
    # error claro.
    fuseki_url: str = "http://fuseki:3030"
    fuseki_dataset: str = "itot"
    fuseki_user: str | None = Field(default=None, repr=False)
    fuseki_password: str | None = Field(default=None, repr=False)
    fuseki_timeout_seconds: float = Field(default=10.0, gt=0, le=300)

    # Carpeta ``semantic/`` (formas SHACL y datos). En el contenedor se monta en
    # ``/semantic``; en desarrollo, ``../semantic`` relativo a ``backend/``.
    semantic_dir: Path = BACKEND_DIR.parent / "semantic"

    # Tamaño máximo del RDF que acepta ``POST /datasets``.
    ingest_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # Límites de la ingesta (QA-G3-03 y QA-G3-10): tripletas por petición y tiempo y
    # memoria del proceso de validación SHACL.
    ingest_max_triples: int = Field(default=100_000, gt=0, le=10_000_000)
    shacl_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    shacl_memory_mb: int = Field(default=2048, ge=256, le=65536)

    # Razonador de la ingesta de ontologías (Pellet, que se ejecuta en Java).
    reasoner_timeout_seconds: float = Field(default=120.0, gt=0, le=3600)

    # Espera máxima del bloqueo de escritura del catálogo (QA-49-03, app.write_lock): si
    # otra escritura no termina antes, la API responde 503.
    catalog_lock_timeout_seconds: float = Field(default=30.0, gt=0, le=3600)
    reasoner_java_memory_mb: int = Field(default=1024, ge=256, le=65536)

    # Frontend al que redirigen (303) las URIs persistentes cuando se pide HTML.
    frontend_base_url: str = "http://localhost:5173"

    # JWT. El secreto es obligatorio y no tiene valor por defecto. El algoritmo se declara
    # antes que el secreto porque la longitud mínima del secreto depende de él.
    jwt_algorithm: JwtAlgorithm = "HS256"
    jwt_secret: str = Field(repr=False)
    jwt_expire_minutes: int = Field(default=60, gt=0)

    # Orígenes CORS separados por comas.
    cors_origins: str = ""

    # Almacenamiento de distribuciones (interfaz en ``app.storage``).
    storage_backend: Literal["disk", "r2"] = "disk"
    storage_disk_path: str = "/data/distributions"
    max_upload_mb: int = Field(default=512, gt=0, le=1024 * 1024)
    download_link_ttl_seconds: int = Field(default=60, gt=0, le=3600)

    # Evaluador FAIR (F-UJI). Las credenciales son opcionales al arrancar: sin ellas la
    # evaluación queda ``failed`` con un motivo claro, pero la API funciona.
    fuji_url: str = "http://fuji:1071/fuji/api/v1"
    fuji_username: str | None = Field(default=None, repr=False)
    fuji_password: str | None = Field(default=None, repr=False)
    fuji_timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    # URL base que se pasa a F-UJI en lugar de BASE_URI (vacío = BASE_URI).
    fair_target_base_url: str = ""
    # Intervalo del trabajador que recoge las evaluaciones pendientes (0 = desactivado).
    fair_worker_poll_seconds: float = Field(default=10.0, ge=0, le=3600)

    # SPARQL público (decisión 42).
    sparql_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    sparql_max_rows: int = Field(default=10_000, gt=0, le=1_000_000)
    sparql_rate_anon_per_min: int = Field(default=30, gt=0, le=100_000)
    sparql_rate_auth_per_min: int = Field(default=60, gt=0, le=100_000)
    saved_queries_max_per_user: int = Field(default=50, gt=0, le=10_000)

    # Login (decisión 18).
    login_max_failures: int = Field(default=5, gt=0, le=1000)
    login_window_minutes: int = Field(default=15, gt=0, le=24 * 60)
    login_lockout_minutes: int = Field(default=15, gt=0, le=24 * 60)

    # Commit desplegado, que publica ``GET /health``. Lo fija quien despliega (p. ej.
    # ``git rev-parse --short HEAD``); vacío o ausente = ``null``.
    app_commit: str | None = Field(default=None, pattern=r"^[0-9A-Za-z._+-]{1,64}$")

    @field_validator("app_commit", mode="before")
    @classmethod
    def _commit_empty_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("base_uri")
    @classmethod
    def _base_uri_with_trailing_slash(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("BASE_URI debe ser una URI http(s)")
        return value if value.endswith(("/", "#")) else f"{value}/"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: str, info: ValidationInfo) -> str:
        algorithm = info.data.get("jwt_algorithm")
        if algorithm is None:  # algoritmo no válido: ya se informa de ese error
            return value
        minimum = JWT_SECRET_MIN_BYTES[algorithm]
        if len(value.encode("utf-8")) < minimum:
            # El mensaje no incluye el valor del secreto.
            raise ValueError(f"debe tener al menos {minimum} bytes con {algorithm}")
        return value

    @field_validator("fuseki_url", "frontend_base_url", "fuji_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("fuseki_user", "fuseki_password", "fuji_username", "fuji_password")
    @classmethod
    def _empty_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("fair_target_base_url")
    @classmethod
    def _target_base(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            raise ValueError("FAIR_TARGET_BASE_URL debe ser una URL http(s)")
        return value if value.endswith("/") else f"{value}/"

    @field_validator("semantic_dir")
    @classmethod
    def _resolve_semantic_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def fuseki_write_credentials(self) -> tuple[str, str] | None:
        if self.fuseki_user and self.fuseki_password:
            return (self.fuseki_user, self.fuseki_password)
        return None

    @property
    def fuji_credentials(self) -> tuple[str, str] | None:
        if self.fuji_username and self.fuji_password:
            return (self.fuji_username, self.fuji_password)
        return None

    @property
    def fair_base_url(self) -> str:
        """URL base con la que F-UJI alcanza las URIs persistentes."""
        return self.fair_target_base_url or self.base_uri

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class ConfigurationError(RuntimeError):
    """Falta una variable de entorno obligatoria o tiene un valor no válido."""


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (cacheada). Falla si falta una variable obligatoria.

    El mensaje de error solo nombra las variables afectadas: nunca incluye sus valores,
    que pueden contener credenciales (p. ej. la contraseña dentro de ``DATABASE_URL``).
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        problems = sorted(
            {
                f"{str(error['loc'][0]).upper()} ({error['type']})"
                for error in exc.errors(include_input=False, include_url=False)
                if error["loc"]
            }
        )
        raise ConfigurationError(
            "Configuración no válida; revisa estas variables de entorno: " + ", ".join(problems)
        ) from None
