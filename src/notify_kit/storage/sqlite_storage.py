from pathlib import Path

from sqlalchemy.engine import URL

from notify_kit.storage.database_storage import DatabaseStorage


class SQLiteStorage(DatabaseStorage):
    """Convenient file-path configuration for the shared SQLAlchemy storage."""

    def __init__(self, path: str | Path) -> None:
        """Create an async SQLite storage configuration from a file path."""
        super().__init__(url=URL.create("sqlite+aiosqlite", database=str(path)))
