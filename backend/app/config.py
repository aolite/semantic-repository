"""Configuración de la aplicación, leída siempre de variables de entorno.

Ningún valor secreto tiene valor por defecto: ``JWT_SECRET`` y ``DATABASE_URL``
son obligatorias y la aplicación no arranca sin ellas.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"

# Longitud mínima del secreto HMAC (32 bytes = 256 bits, el tamaño de salida de HS256).
JWT_SECRET_MIN_LENGTH = 32


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

    # Triplestore. En la fase 1 solo se usa para el health check de disponibilidad.
    fuseki_url: str = "http://fuseki:3030"
    fuseki_dataset: str = "itot"

    # JWT. El secreto es obligatorio y no tiene valor por defecto.
    jwt_secret: str = Field(min_length=JWT_SECRET_MIN_LENGTH, repr=False)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
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

    @field_validator("fuseki_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

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
