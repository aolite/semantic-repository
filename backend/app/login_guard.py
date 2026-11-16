"""Bloqueo de login por fallos repetidos (decisión 18).

Los fallos se cuentan por (usuario normalizado, IP) en PostgreSQL (``login_attempts``), así
que el recuento vale con varios workers. Con ``LOGIN_MAX_FAILURES`` fallos dentro de
``LOGIN_WINDOW_MINUTES``, ese par queda bloqueado ``LOGIN_LOCKOUT_MINUTES``: cualquier
intento responde 429 con ``Retry-After``, aunque la contraseña sea correcta. Un login
correcto pone el contador de ese par a cero. La IP es la de la conexión, no
``X-Forwarded-For``.
"""

import math
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import LoginAttempt

MAX_USERNAME = 64


def sanitize_username(value: str) -> str:
    """Sin caracteres de control y truncado a 64 (lo que se guarda en auditoría)."""
    return "".join(c for c in value if unicodedata.category(c) != "Cc")[:MAX_USERNAME]


def normalize_username(value: str) -> str:
    return sanitize_username(value).strip().casefold()[:MAX_USERNAME]


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def locked_for(session: Session, username: str, ip: str, now: datetime | None = None) -> int | None:
    """Segundos de bloqueo que quedan para el par, o ``None`` si no está bloqueado."""
    now = now or datetime.now(UTC)
    row = session.get(LoginAttempt, (normalize_username(username), ip[:64]))
    until = _aware(row.locked_until) if row else None
    if until is None or until <= now:
        return None
    return max(1, math.ceil((until - now).total_seconds()))


def purge_expired(
    session: Session, settings: Settings, keep: tuple[str, str], now: datetime | None = None
) -> None:
    """Borra los pares que ya no cuentan: sin bloqueo vigente y con la ventana caducada.

    Se llama al registrar cada fallo (una sola sentencia ``DELETE``), así que
    ``login_attempts`` no crece sin límite con usuarios o IPs que no vuelven. ``keep`` es el
    par que se está registrando: su fila puede estar ya en la sesión y se reinicia aparte.
    Sin commit.
    """
    now = now or datetime.now(UTC)
    window = now - timedelta(minutes=settings.login_window_minutes)
    session.execute(
        delete(LoginAttempt)
        .where(LoginAttempt.window_start < window)
        .where(or_(LoginAttempt.locked_until.is_(None), LoginAttempt.locked_until <= now))
        .where(or_(LoginAttempt.username != keep[0], LoginAttempt.ip != keep[1]))
        .execution_options(synchronize_session=False)
    )


def register_failure(
    session: Session, settings: Settings, username: str, ip: str, now: datetime | None = None
) -> bool:
    """Cuenta un fallo. Devuelve ``True`` si este fallo deja el par bloqueado. Sin commit."""
    now = now or datetime.now(UTC)
    key = (normalize_username(username), ip[:64])
    purge_expired(session, settings, key, now)
    row = session.get(LoginAttempt, key)
    if row is None:
        row = LoginAttempt(username=key[0], ip=key[1], failures=0, window_start=now)
        session.add(row)
        try:
            session.flush()
        except IntegrityError:  # otro worker lo ha creado a la vez
            session.rollback()
            row = session.get(LoginAttempt, key)
            if row is None:  # pragma: no cover - carrera muy improbable
                return False
    window_start = _aware(row.window_start) or now
    locked_until = _aware(row.locked_until)
    if locked_until is not None and locked_until <= now:
        row.locked_until = None
        row.failures, row.window_start = 0, now
    elif window_start < now - timedelta(minutes=settings.login_window_minutes):
        row.failures, row.window_start = 0, now
    row.failures += 1
    if row.failures >= settings.login_max_failures and row.locked_until is None:
        row.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
        return True
    return False


def reset(session: Session, username: str, ip: str) -> None:
    row = session.get(LoginAttempt, (normalize_username(username), ip[:64]))
    if row is not None:
        session.delete(row)
