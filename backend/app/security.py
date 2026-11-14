"""Hash de contraseñas (argon2id) y emisión/validación de JWT."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import Settings
from app.models import Role

_password_hash = PasswordHash((Argon2Hasher(),))

# Hash de referencia para igualar el tiempo de respuesta cuando el usuario no existe.
_DUMMY_HASH = _password_hash.hash(uuid.uuid4().hex)

PASSWORD_MIN_LENGTH = 12


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verifica la contraseña. Con ``password_hash=None`` gasta el mismo tiempo y falla."""
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    return _password_hash.verify(password, password_hash)


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    username: str
    role: Role


class InvalidTokenError(Exception):
    """El token falta, está caducado, manipulado o mal formado."""


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    username: str,
    role: Role,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Devuelve el JWT firmado y su validez en segundos."""
    issued_at = now or datetime.now(UTC)
    expires_in = settings.jwt_expire_minutes * 60
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role.value,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(settings: Settings, token: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "role"]},
        )
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            username=str(payload.get("username", "")),
            role=Role(payload["role"]),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc
