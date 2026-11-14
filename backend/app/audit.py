"""Registro de auditoría en PostgreSQL."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditAction, AuditEvent, User


def record(
    session: Session,
    action: AuditAction,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    target: User | None = None,
    target_username: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Añade un evento a la sesión. El commit lo hace quien llama."""
    event = AuditEvent(
        action=action.value,
        actor_id=actor.id if actor else None,
        actor_username=actor.username if actor else actor_username,
        target_user_id=target.id if target else None,
        target_username=target.username if target else target_username,
        details=details or {},
    )
    session.add(event)
    return event
