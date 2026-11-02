from sqlalchemy import JSON, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.db.base import Base
from notify_kit.types import Payload


class TemplateProviderRecord(Base):
    """Link a template to opaque provider metadata without interpreting it."""

    __tablename__ = "notify_kit_template_provider"

    template_label: Mapped[str] = mapped_column(
        Text,
        ForeignKey("notify_kit_templates.label", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_metadata: Mapped[Payload] = mapped_column("metadata", JSON, nullable=False)
    template_revision: Mapped[int] = mapped_column(Integer)

    generation: Mapped[str] = mapped_column(Text, server_default="legacy")
