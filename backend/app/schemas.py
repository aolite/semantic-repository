"""Esquemas Pydantic de entrada y salida de la API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Role
from app.security import PASSWORD_MIN_LENGTH

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - tipo OAuth2, no es un secreto
    expires_in: int = Field(description="Validez del token en segundos")
    role: Role


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        pattern=USERNAME_PATTERN,
        description="De 3 a 64 caracteres: minúsculas, dígitos, punto, guion y guion bajo",
    )
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None


class ComponentStatus(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthStatus(BaseModel):
    status: Literal["ok"]


class ReadinessStatus(BaseModel):
    status: Literal["ok", "error"]
    checks: dict[str, ComponentStatus]
