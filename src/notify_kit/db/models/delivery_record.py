from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.db.base import Base
from notify_kit.types import Payload


class DeliveryRecord(Base):
    """Persist one recipient's prepared request and delivery lifecycle."""

    __tablename__ = "notify_kit_deliveries"
    __table_args__ = (
        Index("ix_notify_kit_delivery_due", "status", "next_attempt_at"),
        UniqueConstraint(
            "batch_id", "position", name="uq_notify_kit_delivery_position"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("notify_kit_batches.id"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(Text)
    template_label: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    prepared: Mapped[Payload] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    message_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
    next_attempt_at: Mapped[float | None] = mapped_column(Float)
    acknowledged_at: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(Text)
    terminal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    completed_at: Mapped[float | None] = mapped_column(Float)
    lease_token: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[float | None] = mapped_column(Float)
    content_cleared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
