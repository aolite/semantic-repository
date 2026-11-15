"""Modelos SQLAlchemy: cuentas de usuario, registro de auditoría y métricas OWL.

El rol ``lector`` es anónimo y no tiene cuenta: en la base de datos solo se guardan
cuentas de ``miembro``, ``editor`` y ``admin``.
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(enum.StrEnum):
    """Roles con cuenta. ``lector`` (anónimo) no se guarda en la base de datos."""

    MIEMBRO = "miembro"
    EDITOR = "editor"
    ADMIN = "admin"


class AuditAction(enum.StrEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    USER_CREATED = "user_created"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"
    ROLE_CHANGED = "role_changed"
    DATASET_PUBLISHED = "dataset_published"
    ONTOLOGY_PUBLISHED = "ontology_published"
    SCHEME_PUBLISHED = "scheme_published"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditEvent(Base):
    """Quién hizo qué, cuándo y sobre quién.

    ``actor_username`` y ``target_username`` se copian para que el registro siga siendo
    legible aunque la cuenta cambie. ``actor_id`` es nulo cuando la acción no tiene un
    usuario autenticado (login fallido o alta por CLI).
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OntologyMetricsRecord(Base):
    """Métricas OWL y consistencia de una versión de ontología, calculadas en la ingesta.

    Se guardan aquí, y no en el triplestore, porque son datos derivados que calcula el
    backend (no forman parte del RDF versionado en Git) y no hay un vocabulario decidido
    para describirlos en RDF. ``content_hash`` es el SHA-256 del grafo canónico de la
    versión: si el RDF de la versión no cambia, no se recalculan.
    """

    __tablename__ = "ontology_metrics"

    version_iri: Mapped[str] = mapped_column(String(512), primary_key=True)
    ontology_iri: Mapped[str] = mapped_column(String(512), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    consistency: Mapped[dict[str, Any]] = mapped_column(JSON)
    tool: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
