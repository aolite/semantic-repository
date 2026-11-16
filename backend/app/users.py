"""Operaciones sobre cuentas compartidas por la API y la CLI. Todas dejan rastro en auditoría."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.models import AuditAction, Role, User
from app.security import hash_password


class UsernameTakenError(Exception):
    """Ya existe una cuenta con ese nombre de usuario."""


def get_by_username(session: Session, username: str) -> User | None:
    return session.scalars(select(User).where(User.username == username)).one_or_none()


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: Role,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
) -> User:
    """Crea la cuenta y su evento de auditoría en la misma transacción."""
    if get_by_username(session, username) is not None:
        raise UsernameTakenError(username)
    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:  # carrera con otra alta del mismo nombre
        session.rollback()
        raise UsernameTakenError(username) from exc
    audit.record(
        session,
        AuditAction.USER_CREATED,
        actor=actor,
        actor_username=actor_username,
        target=user,
        details={"role": role.value, "via": via},
    )
    session.commit()
    return user


def update_user(
    session: Session,
    user: User,
    *,
    actor: User,
    role: Role | None = None,
    is_active: bool | None = None,
) -> User:
    """Cambia rol y/o estado activo. Solo registra en auditoría los cambios reales."""
    if role is not None and role != user.role:
        previous = user.role
        user.role = role
        user.tokens_valid_after = datetime.now(UTC)  # decisión 18
        audit.record(
            session,
            AuditAction.ROLE_CHANGED,
            actor=actor,
            target=user,
            details={"from": previous.value, "to": role.value},
        )
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        if not is_active:
            # Decisión 18: la baja invalida los tokens emitidos antes. Reactivar no los
            # revive (no se toca la marca).
            user.tokens_valid_after = datetime.now(UTC)
        audit.record(
            session,
            AuditAction.USER_REACTIVATED if is_active else AuditAction.USER_DEACTIVATED,
            actor=actor,
            target=user,
        )
    session.commit()
    session.refresh(user)
    return user
