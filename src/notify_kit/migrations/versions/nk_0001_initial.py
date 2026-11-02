"""Initial versioned notify_kit schema.

Revision ID: nk_0001
Revises: None
Branch: notify_kit

This immutable definition intentionally does not import current ORM models.
Pre-Alembic draft databases require explicit reconciliation before adoption.
"""

import sqlalchemy as sa
from alembic import op

revision = "nk_0001"
down_revision = None
branch_labels = ("notify_kit",)
depends_on = None


def upgrade() -> None:
    """Create only kit-owned tables and record runtime compatibility."""
    op.create_table(
        "notify_kit_templates",
        sa.Column("label", sa.Text(), primary_key=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("operation_token", sa.Text(), nullable=True),
    )
    op.create_table(
        "notify_kit_template_provider",
        sa.Column(
            "template_label",
            sa.Text(),
            sa.ForeignKey("notify_kit_templates.label", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("template_revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "notify_kit_batches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "notify_kit_deliveries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Text(),
            sa.ForeignKey("notify_kit_batches.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("template_label", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("prepared", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=True),
        sa.Column("acknowledged_at", sa.Float(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "batch_id", "position", name="uq_notify_kit_delivery_position"
        ),
    )
    op.create_index(
        "ix_notify_kit_delivery_due",
        "notify_kit_deliveries",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_notify_kit_deliveries_batch_id", "notify_kit_deliveries", ["batch_id"]
    )
    state = op.create_table(
        "notify_kit_schema_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("revision", sa.Text(), nullable=False),
    )
    op.bulk_insert(state, [{"key": "schema", "revision": "nk_0001"}])


def downgrade() -> None:
    """Remove all kit tables; the caller must explicitly authorize this data loss."""
    op.drop_table("notify_kit_schema_state")
    op.drop_index(
        "ix_notify_kit_deliveries_batch_id", table_name="notify_kit_deliveries"
    )
    op.drop_index("ix_notify_kit_delivery_due", table_name="notify_kit_deliveries")
    op.drop_table("notify_kit_deliveries")
    op.drop_table("notify_kit_batches")
    op.drop_table("notify_kit_template_provider")
    op.drop_table("notify_kit_templates")
