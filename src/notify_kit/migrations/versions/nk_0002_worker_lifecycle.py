"""Durable worker leases, terminal state and completion outbox.

Revision ID: nk_0002
Revises: nk_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "nk_0002"
down_revision = "nk_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve existing jobs; legacy processing jobs reconcile instead of resend."""
    with op.batch_alter_table("notify_kit_templates") as batch:
        batch.add_column(
            sa.Column(
                "lifecycle_identity", sa.Text(), nullable=False, server_default=""
            )
        )
    op.execute("UPDATE notify_kit_templates SET lifecycle_identity = label")
    with op.batch_alter_table("notify_kit_batches") as batch:
        batch.add_column(
            sa.Column(
                "recipient_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
    op.execute(
        "UPDATE notify_kit_batches SET recipient_count = (SELECT count(*) FROM notify_kit_deliveries WHERE batch_id = notify_kit_batches.id)"
    )
    with op.batch_alter_table("notify_kit_deliveries") as batch:
        batch.add_column(
            sa.Column(
                "terminal", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(sa.Column("completed_at", sa.Float(), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.Float(), nullable=True))
    with op.batch_alter_table("notify_kit_deliveries") as batch:
        batch.add_column(
            sa.Column(
                "content_cleared",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute(
        "UPDATE notify_kit_deliveries SET terminal = true, completed_at = updated_at WHERE status IN ('delivered', 'failed', 'skipped')"
    )
    op.execute(
        "UPDATE notify_kit_deliveries SET lease_expires_at = 0 WHERE status = 'processing'"
    )
    op.execute(
        "UPDATE notify_kit_deliveries SET next_attempt_at = updated_at WHERE status IN ('accepted', 'unknown')"
    )
    op.create_table(
        "notify_kit_completions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "delivery_id",
            sa.Text(),
            sa.ForeignKey("notify_kit_deliveries.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.Float(), nullable=True),
    )
    # Historical completions are already handled; upgrading must not replay callbacks.
    op.execute(
        "INSERT INTO notify_kit_completions (id, delivery_id, status, attempts, created_at, next_attempt_at) SELECT id, id, 'handled', 0, completed_at, NULL FROM notify_kit_deliveries WHERE terminal = true"
    )
    op.execute(
        "UPDATE notify_kit_schema_state SET revision = 'nk_0002' WHERE key = 'schema'"
    )


def downgrade() -> None:
    """Remove outbox/leases while preserving delivery records."""
    op.drop_table("notify_kit_completions")
    with op.batch_alter_table("notify_kit_templates") as batch:
        batch.drop_column("lifecycle_identity")
    with op.batch_alter_table("notify_kit_batches") as batch:
        batch.drop_column("recipient_count")
    with op.batch_alter_table("notify_kit_deliveries") as batch:
        for name in (
            "content_cleared",
            "lease_expires_at",
            "lease_token",
            "completed_at",
            "terminal",
        ):
            batch.drop_column(name)
    op.execute(
        "UPDATE notify_kit_schema_state SET revision = 'nk_0001' WHERE key = 'schema'"
    )
