from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.db.base import Base


class BatchRecord(Base):
    """Persist submission identity and its canonical idempotency request."""

    __tablename__ = "notify_kit_batches"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    request: Mapped[str] = mapped_column(Text)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
