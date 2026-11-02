from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from notify_kit.constants import INITIAL_TEMPLATE_REVISION
from notify_kit.db.database import Database
from notify_kit.db.models.template_provider_record import TemplateProviderRecord
from notify_kit.db.models.template_record import TemplateRecord
from notify_kit.db.template_guards import (
    locked_template,
    require_idle,
    require_no_active_jobs,
)
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.template import Template
from notify_kit.types import Payload


class TemplateStore:
    """Transactional CRUD for uniquely labelled templates on either database."""

    def __init__(self, database: Database) -> None:
        """Attach the instance-owned database session factory."""
        self._database = database

    async def create(self, *, label: str, definition: Payload) -> Template:
        """Create a unique template; reject an existing label."""
        if not label.strip():
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "Template label must not be empty"
            )
        try:
            async with self._database.session(write=True) as session:
                row = TemplateRecord(
                    label=label,
                    definition=definition,
                    revision=INITIAL_TEMPLATE_REVISION,
                    lifecycle_identity=uuid4().hex,
                )
                session.add(row)
                await session.flush()
                result = self._template(row)
        except IntegrityError:
            raise NotifierError(
                ErrorCode.ALREADY_EXISTS, f"Template already exists: {label}"
            ) from None
        return result

    @staticmethod
    def _template(row: TemplateRecord) -> Template:
        return Template(row.label, row.definition, row.revision)

    async def get(self, label: str) -> Template:
        """Retrieve a template by label or raise a not-found NotifierError."""
        async with self._database.session() as session:
            row = await session.get(TemplateRecord, label)
            if row is None:
                raise NotifierError(ErrorCode.NOT_FOUND, f"Template not found: {label}")
            return self._template(row)

    async def list(self) -> tuple[Template, ...]:
        """Return all templates ordered by label."""
        async with self._database.session() as session:
            rows = await session.scalars(
                select(TemplateRecord).order_by(TemplateRecord.label)
            )
            return tuple(self._template(row) for row in rows)

    async def update(self, *, label: str, definition: Payload) -> Template:
        """Edit an idle definition; linked provider revisions must be updated explicitly."""
        async with self._database.session(write=True) as session:
            row = await locked_template(session, label)
            require_idle(row)
            await require_no_active_jobs(session, label)
            row.definition = definition
            row.revision += 1
            return self._template(row)

    async def delete(self, label: str) -> None:
        """Require all providers to be unregistered and all deliveries finished."""
        async with self._database.session(write=True) as session:
            row = await locked_template(session, label)
            require_idle(row)
            await require_no_active_jobs(session, label)
            linked = await session.scalar(
                select(TemplateProviderRecord.provider)
                .where(
                    TemplateProviderRecord.template_label == label,
                )
                .limit(1)
            )
            if linked is not None:
                raise NotifierError(
                    ErrorCode.TEMPLATE_HAS_LINKS,
                    "Unregister provider links before deleting the template",
                )
            await session.delete(row)
