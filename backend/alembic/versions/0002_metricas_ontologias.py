"""Métricas OWL y consistencia de cada versión de ontología.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ontology_metrics",
        sa.Column("version_iri", sa.String(length=512), nullable=False),
        sa.Column("ontology_iri", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("consistency", sa.JSON(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_iri", name=op.f("pk_ontology_metrics")),
    )
    with op.batch_alter_table("ontology_metrics", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ontology_metrics_ontology_iri"), ["ontology_iri"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("ontology_metrics", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ontology_metrics_ontology_iri"))
    op.drop_table("ontology_metrics")
