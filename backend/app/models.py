"""Modelos SQLAlchemy: cuentas de usuario, registro de auditoría y métricas OWL.

El rol ``lector`` es anónimo y no tiene cuenta: en la base de datos solo se guardan
cuentas de ``miembro``, ``editor`` y ``admin``.
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
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
    DISTRIBUTION_UPLOADED = "distribution_uploaded"
    DISTRIBUTION_DOWNLOADED = "distribution_downloaded"
    FAIR_EVALUATED = "fair_evaluated"
    SAVED_QUERY_CREATED = "saved_query_created"
    SAVED_QUERY_DELETED = "saved_query_deleted"
    LOGIN_LOCKED = "login_locked"
    # Decisión 49: CRUD de catálogos y datasets. Quién dio de baja algo va aquí, no al RDF.
    CATALOG_CREATED = "catalog_created"
    CATALOG_UPDATED = "catalog_updated"
    CATALOG_WITHDRAWN = "catalog_withdrawn"
    DATASET_CREATED = "dataset_created"
    DATASET_UPDATED = "dataset_updated"
    DATASET_WITHDRAWN = "dataset_withdrawn"


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
    # Decisión 18: los JWT emitidos antes de este instante dejan de valer (baja, cambio
    # de rol o de contraseña). Reactivar la cuenta no lo borra.
    tokens_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class DistributionFile(Base):
    """Fichero de una distribución (decisiones 40 y 41).

    El RDF publicado no cambia al subir un fichero: tamaño y SHA-256 viven aquí.
    ``storage_key`` es ``{slug}/{version}/{dist}``, igual en disco y en R2.
    """

    __tablename__ = "distribution_files"

    storage_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    distribution_uri: Mapped[str] = mapped_column(String(1024), index=True)
    media_type: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsedDownloadToken(Base):
    """Enlaces de descarga firmados ya usados (son de un solo uso)."""

    __tablename__ = "used_download_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FairEvaluation(Base):
    """Evaluación FAIR de una versión de dataset con F-UJI. Se conserva el historial."""

    __tablename__ = "fair_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_uri: Mapped[str] = mapped_column(String(1024), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    score_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_f: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_i: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    maturity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evaluated_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavedQuery(Base):
    """Consulta SPARQL personal (decisión 43). Se guarda el texto, no se ejecuta."""

    __tablename__ = "saved_queries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    query: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LoginAttempt(Base):
    """Fallos de login por (usuario normalizado, IP) (decisión 18)."""

    __tablename__ = "login_attempts"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RateLimitCounter(Base):
    """Contador de ventana fija (un minuto) del límite de frecuencia del SPARQL público.

    En la base de datos para que valga con varios workers o réplicas del backend.
    """

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
