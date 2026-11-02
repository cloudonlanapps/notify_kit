from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from notify_kit.db.base import Base
from notify_kit.migrations.constants import SCHEMA_STATE_TABLE


class SchemaStateRecord(Base):
    """Runtime compatibility marker; Alembic still owns the shared version history."""

    __tablename__ = SCHEMA_STATE_TABLE

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[str] = mapped_column(Text, nullable=False)
