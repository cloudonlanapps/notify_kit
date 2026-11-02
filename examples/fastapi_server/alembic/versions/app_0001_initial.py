"""Start the example application's independent revision lineage.

Revision ID: app_0001
Revises: None
The example currently owns no tables outside notify_kit.
"""

revision = "app_0001"
down_revision = None
branch_labels = ("app",)
depends_on = None


def upgrade() -> None:
    """Establish the application branch without creating kit tables."""


def downgrade() -> None:
    """Remove the empty application baseline without touching kit data."""
