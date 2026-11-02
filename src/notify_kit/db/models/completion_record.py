from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.db.base import Base


class CompletionRecord(Base):
    """Transactional outbox with independent callback attempts and leases."""

    __tablename__ = "notify_kit_completions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(
        Text, ForeignKey("notify_kit_deliveries.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float)
    next_attempt_at: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[float | None] = mapped_column(Float)
