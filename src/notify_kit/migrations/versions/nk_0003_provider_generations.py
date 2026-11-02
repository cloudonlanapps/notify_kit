"""Provider-specific generations and bounded empty batch retention.

Revision ID: nk_0003
Revises: nk_0002
"""

import time

import sqlalchemy as sa
from alembic import op

revision = "nk_0003"
down_revision = "nk_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve links and seed identities without replaying provider operations."""
    op.create_table(
        "notify_kit_provider_generations",
        sa.Column(
            "template_label",
            sa.Text(),
            sa.ForeignKey("notify_kit_templates.label", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("identity", sa.Text(), nullable=False),
    )
    # Preserve the old identity for existing links so interrupted updates recover.
    op.execute(
        "INSERT INTO notify_kit_provider_generations (template_label,provider,identity) "
        "SELECT p.template_label,p.provider,t.lifecycle_identity "
        "FROM notify_kit_template_provider p JOIN notify_kit_templates t ON t.label=p.template_label"
    )
    with op.batch_alter_table("notify_kit_template_provider") as batch:
        batch.add_column(
            sa.Column("generation", sa.Text(), nullable=False, server_default="legacy")
        )
    with op.batch_alter_table("notify_kit_batches") as batch:
        batch.add_column(
            sa.Column("created_at", sa.Float(), nullable=False, server_default="0")
        )
    op.create_index(
        "ix_notify_kit_batches_created_at", "notify_kit_batches", ["created_at"]
    )
    batches = sa.table("notify_kit_batches", sa.column("created_at", sa.Float()))
    op.execute(batches.update().values(created_at=time.time()))
    op.execute(
        "UPDATE notify_kit_schema_state SET revision = 'nk_0003' WHERE key = 'schema'"
    )


def downgrade() -> None:
    """Remove generation guards without deleting templates or deliveries."""
    op.drop_index("ix_notify_kit_batches_created_at", table_name="notify_kit_batches")
    with op.batch_alter_table("notify_kit_batches") as batch:
        batch.drop_column("created_at")
    with op.batch_alter_table("notify_kit_template_provider") as batch:
        batch.drop_column("generation")
    op.drop_table("notify_kit_provider_generations")
    op.execute(
        "UPDATE notify_kit_schema_state SET revision = 'nk_0002' WHERE key = 'schema'"
    )
