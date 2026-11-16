"""Hash de contraseñas (argon2id) y emisión/validación de JWT."""

import unicodedata
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


def has_control_chars(value: str) -> bool:
    """True si contiene NUL u otro carácter de control (categoría Unicode ``Cc``)."""
    return any(unicodedata.category(char) == "Cc" for char in value)


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
    # Instante de emisión con precisión de microsegundos (``iat_us``; si falta, ``iat``).
    issued_at_us: int


def to_microseconds(moment: datetime) -> int:
    """Microsegundos desde la época Unix (UTC), sin pérdidas de coma flotante."""
    delta = moment.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def token_revoked(claims_issued_at_us: int, tokens_valid_after: datetime | None) -> bool:
    """Un token emitido antes de ``users.tokens_valid_after`` ya no vale (decisión 18)."""
    if tokens_valid_after is None:
        return False
    if tokens_valid_after.tzinfo is None:  # SQLite devuelve fechas sin zona horaria
        tokens_valid_after = tokens_valid_after.replace(tzinfo=UTC)
    return claims_issued_at_us < to_microseconds(tokens_valid_after)


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
        # ``iat`` va en segundos enteros (RFC 7519); la revocación necesita más precisión
        # para distinguir un token emitido justo antes o justo después de una baja.
        "iat_us": to_microseconds(issued_at),
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
        precise = payload.get("iat_us")
        issued_at_us = (
            precise
            if isinstance(precise, int) and not isinstance(precise, bool)
            else int(payload["iat"]) * 1_000_000
        )
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            username=str(payload.get("username", "")),
            role=Role(payload["role"]),
            issued_at_us=issued_at_us,
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc


# --- Enlaces de descarga firmados (sección 5.3) -------------------------------------------
# Token HMAC con JWT_SECRET, distinto del de acceso: lleva ``aud`` (el de acceso no), así
# que ninguno de los dos vale en lugar del otro. Ligado a ``storage_key`` y al usuario,
# con caducidad corta y un ``jti`` que se marca como usado (un solo uso).

DOWNLOAD_AUDIENCE = "itot-download"


@dataclass(frozen=True)
class DownloadClaims:
    user_id: uuid.UUID
    storage_key: str
    jti: str
    issued_at_us: int
    expires_at: datetime


def create_download_token(
    settings: Settings, *, user_id: uuid.UUID, storage_key: str, now: datetime | None = None
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(UTC)
    # ``exp`` se codifica en segundos enteros: se devuelve el mismo instante.
    expires_at = (issued_at + timedelta(seconds=settings.download_link_ttl_seconds)).replace(
        microsecond=0
    )
    payload = {
        "aud": DOWNLOAD_AUDIENCE,
        "sub": str(user_id),
        "key": storage_key,
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "iat_us": to_microseconds(issued_at),
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_download_token(settings: Settings, token: str) -> DownloadClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=DOWNLOAD_AUDIENCE,
            options={"require": ["aud", "sub", "key", "jti", "iat", "exp"]},
        )
        key, jti, precise = payload["key"], payload["jti"], payload.get("iat_us")
        if not isinstance(key, str) or not isinstance(jti, str) or len(jti) > 64:
            raise ValueError("token de descarga mal formado")
        return DownloadClaims(
            user_id=uuid.UUID(payload["sub"]),
            storage_key=key,
            jti=jti,
            issued_at_us=precise if isinstance(precise, int) else int(payload["iat"]) * 10**6,
            expires_at=datetime.fromtimestamp(int(payload["exp"]), UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc
