from sqlalchemy.engine import URL

from notify_kit.db.database import Database
from notify_kit.storage.completion_store import CompletionStore
from notify_kit.storage.delivery_store import DeliveryStore
from notify_kit.storage.template_links import TemplateLinks
from notify_kit.storage.template_store import TemplateStore


class DatabaseStorage:
    """SQLAlchemy stores sharing one instance-owned database engine."""

    def __init__(self, *, url: str | URL) -> None:
        """Accept an explicit async database URL; the database must already exist."""
        self._database = Database(url)
        self.templates = TemplateStore(self._database)
        self.links = TemplateLinks(self._database)
        self.deliveries = DeliveryStore(self._database)
        self.completions = CompletionStore(self._database)

    async def initialize(self) -> None:
        """Check schema compatibility after application-owned Alembic upgrades."""
        await self._database.initialize()

    async def aclose(self) -> None:
        """Release this storage instance's engine resources."""
        await self._database.aclose()
