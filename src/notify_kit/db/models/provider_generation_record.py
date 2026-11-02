from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.db.base import Base


class ProviderGenerationRecord(Base):
    """Keep provider-specific operation identity even while a link is absent."""

    __tablename__ = "notify_kit_provider_generations"

    template_label: Mapped[str] = mapped_column(
        Text,
        ForeignKey("notify_kit_templates.label", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    identity: Mapped[str] = mapped_column(Text)
