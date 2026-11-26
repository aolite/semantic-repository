"""Decisión 51: prefijo VANN de cada versión de una ontología externa.

- ``external_version_prefixes``: el prefijo con el que se publicó cada versión
  ``{BASE_URI}onto/externas/{slug}/{n}``. El que una sustitución posterior deja de usar
  queda reservado para esa externa (regla 7 de ``semantic/uris.md``).

Las acciones nuevas de auditoría no necesitan migración: ``audit_events.action`` es texto.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_version_prefixes",
        sa.Column("version_uri", sa.String(length=1024), nullable=False),
        sa.Column("ontology_iri", sa.String(length=1024), nullable=False),
        sa.Column("prefix", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_uri", name=op.f("pk_external_version_prefixes")),
    )
    with op.batch_alter_table("external_version_prefixes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_external_version_prefixes_ontology_iri"), ["ontology_iri"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_external_version_prefixes_prefix"), ["prefix"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("external_version_prefixes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_external_version_prefixes_prefix"))
        batch_op.drop_index(batch_op.f("ix_external_version_prefixes_ontology_iri"))
    op.drop_table("external_version_prefixes")
