"""Load all kit-owned tables into independent SQLAlchemy metadata."""

from sqlalchemy import MetaData

from notify_kit.db.base import Base
from notify_kit.db.models.batch_record import BatchRecord
from notify_kit.db.models.completion_record import CompletionRecord
from notify_kit.db.models.delivery_record import DeliveryRecord
from notify_kit.db.models.provider_generation_record import ProviderGenerationRecord
from notify_kit.db.models.schema_state_record import SchemaStateRecord
from notify_kit.db.models.template_provider_record import TemplateProviderRecord
from notify_kit.db.models.template_record import TemplateRecord


def metadata() -> MetaData:
    """Return metadata with every kit model registered, without opening a database."""
    # Explicit references document the complete schema registry.
    _ = (
        BatchRecord,
        ProviderGenerationRecord,
        CompletionRecord,
        DeliveryRecord,
        TemplateProviderRecord,
        TemplateRecord,
        SchemaStateRecord,
    )
    return Base.metadata
