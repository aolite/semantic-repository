"""Decisión 50: prefijos VANN de los esquemas y ontologías dados de baja.

- ``withdrawn_prefixes``: el prefijo (``vann:preferredNamespacePrefix``) de un esquema SKOS
  o una ontología propia dados de baja no se reutiliza, y la lápida no lo guarda.

Las acciones nuevas de auditoría no necesitan migración: ``audit_events.action`` es texto.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "withdrawn_prefixes",
        sa.Column("prefix", sa.String(length=200), nullable=False),
        sa.Column("resource_uri", sa.String(length=1024), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("prefix", name=op.f("pk_withdrawn_prefixes")),
    )
    with op.batch_alter_table("withdrawn_prefixes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_withdrawn_prefixes_resource_uri"), ["resource_uri"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("withdrawn_prefixes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_withdrawn_prefixes_resource_uri"))
    op.drop_table("withdrawn_prefixes")
