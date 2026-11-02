from sqlalchemy import JSON, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.constants import INITIAL_TEMPLATE_REVISION
from notify_kit.db.base import Base
from notify_kit.types import Payload


class TemplateRecord(Base):
    """Persist a uniquely labelled template definition."""

    __tablename__ = "notify_kit_templates"

    label: Mapped[str] = mapped_column(Text, primary_key=True)
    definition: Mapped[Payload] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=INITIAL_TEMPLATE_REVISION)
    operation_token: Mapped[str | None] = mapped_column(Text)
    lifecycle_identity: Mapped[str] = mapped_column(Text)
