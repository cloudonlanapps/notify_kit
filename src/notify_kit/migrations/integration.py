from collections.abc import Mapping

from sqlalchemy import MetaData, Table
from sqlalchemy.schema import SchemaItem

from notify_kit.db.schema import metadata
from notify_kit.migrations.constants import TABLE_PREFIX


def migration_metadata() -> MetaData:
    """Return all kit metadata for composition with an application's Alembic metadata."""
    return metadata()


def exclude_kit_names(
    name: str | None, type_: str, parent_names: Mapping[str, str | None]
) -> bool:
    """Exclude reflected kit tables from application-owned autogeneration.

    Compose with the application's existing include_name filter using AND.
    Explicit packaged upgrade/downgrade operations are unaffected by this filter.
    """
    return not (type_ == "table" and name is not None and name.startswith(TABLE_PREFIX))


def exclude_kit_objects(
    object_: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Exclude both reflected and model-side kit objects from application revisions.

    Compose with the application's existing include_object filter using AND.
    Kit revisions are shipped by the package, never generated in the caller.
    """
    table = object_ if type_ == "table" else getattr(object_, "table", None)
    return not isinstance(table, Table) or not table.name.startswith(TABLE_PREFIX)
