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

    # Almacenamiento de distribuciones (la interfaz llega en la fase 4).
    storage_backend: Literal["disk", "r2"] = "disk"
    storage_disk_path: str = "/data/distributions"

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

    @field_validator("fuseki_url", "frontend_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("fuseki_user", "fuseki_password")
    @classmethod
    def _empty_is_none(cls, value: str | None) -> str | None:
        return value or None

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
