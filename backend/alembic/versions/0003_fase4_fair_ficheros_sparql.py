"""Fase 4: ficheros de distribución, evaluaciones FAIR, consultas guardadas, login y SPARQL.

- ``users.tokens_valid_after`` (revocación de tokens, decisión 18).
- ``distribution_files`` y ``used_download_tokens`` (decisiones 40 y 41).
- ``fair_evaluations`` (F-UJI).
- ``saved_queries`` (decisión 43).
- ``login_attempts`` (decisión 18) y ``rate_limit_counters`` (decisión 42).

Las acciones nuevas de auditoría no necesitan migración: ``audit_events.action`` es texto.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tokens_valid_after", sa.DateTime(timezone=True)))

    op.create_table(
        "distribution_files",
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("distribution_uri", sa.String(length=1024), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_distribution_files_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("storage_key", name=op.f("pk_distribution_files")),
    )
    with op.batch_alter_table("distribution_files", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_distribution_files_distribution_uri"), ["distribution_uri"]
        )

    op.create_table(
        "used_download_tokens",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_used_download_tokens")),
    )
    with op.batch_alter_table("used_download_tokens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_used_download_tokens_expires_at"), ["expires_at"])

    op.create_table(
        "fair_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_uri", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("score_total", sa.Float(), nullable=True),
        sa.Column("score_f", sa.Float(), nullable=True),
        sa.Column("score_a", sa.Float(), nullable=True),
        sa.Column("score_i", sa.Float(), nullable=True),
        sa.Column("score_r", sa.Float(), nullable=True),
        sa.Column("maturity", sa.String(length=64), nullable=True),
        sa.Column("evaluator", sa.String(length=255), nullable=True),
        sa.Column("evaluated_url", sa.String(length=1024), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_fair_evaluations_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fair_evaluations")),
    )
    with op.batch_alter_table("fair_evaluations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_fair_evaluations_version_uri"), ["version_uri"])
        batch_op.create_index(batch_op.f("ix_fair_evaluations_status"), ["status"])

    op.create_table(
        "saved_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("hint", sa.String(length=200), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_saved_queries_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_queries")),
    )
    with op.batch_alter_table("saved_queries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_saved_queries_owner_id"), ["owner_id"])

    op.create_table(
        "login_attempts",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("username", "ip", name=op.f("pk_login_attempts")),
    )

    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("window", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window", name=op.f("pk_rate_limit_counters")),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_counters")
    op.drop_table("login_attempts")
    with op.batch_alter_table("saved_queries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_saved_queries_owner_id"))
    op.drop_table("saved_queries")
    with op.batch_alter_table("fair_evaluations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_fair_evaluations_status"))
        batch_op.drop_index(batch_op.f("ix_fair_evaluations_version_uri"))
    op.drop_table("fair_evaluations")
    with op.batch_alter_table("used_download_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_used_download_tokens_expires_at"))
    op.drop_table("used_download_tokens")
    with op.batch_alter_table("distribution_files", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_distribution_files_distribution_uri"))
    op.drop_table("distribution_files")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("tokens_valid_after")
