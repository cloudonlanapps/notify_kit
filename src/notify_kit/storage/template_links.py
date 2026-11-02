from uuid import uuid4

from notify_kit.db.database import Database
from notify_kit.db.models.template_provider_record import TemplateProviderRecord
from notify_kit.db.template_guards import (
    locked_template,
    require_idle,
    require_no_active_jobs,
)
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.template import Template
from notify_kit.types import Payload


class TemplateLinks:
    """Persist many template links per provider, with revision and lifecycle guards."""

    def __init__(self, database: Database) -> None:
        """Attach the instance-owned database session factory."""
        self._database = database

    async def get(
        self, provider: str, template: str, *, require_current: bool = False
    ) -> Payload | None:
        """Read opaque metadata; optionally reject a busy or outdated registration."""
        async with self._database.session() as session:
            parent = await locked_template(session, template)
            if require_current:
                require_idle(parent)
            row = await session.get(TemplateProviderRecord, (template, provider))
            if (
                row is not None
                and require_current
                and row.template_revision != parent.revision
            ):
                raise NotifierError(
                    ErrorCode.TEMPLATE_CHANGED,
                    "Update the provider template to the current revision",
                    provider=provider,
                )
            return None if row is None else row.provider_metadata

    async def begin(self, template: Template) -> str:
        """Persist a gate around a remote mutation without holding a network transaction."""
        async with self._database.session(write=True) as session:
            parent = await locked_template(session, template.label)
            require_idle(parent)
            if parent.revision != template.revision:
                raise NotifierError(
                    ErrorCode.TEMPLATE_CHANGED, "Template changed; retry"
                )
            await require_no_active_jobs(session, template.label)
            token = uuid4().hex
            parent.operation_token = token
            return token

    async def end(self, template: str, token: str) -> None:
        """Release only the operation gate owned by this invocation."""
        async with self._database.session(write=True) as session:
            parent = await locked_template(session, template)
            if parent.operation_token == token:
                parent.operation_token = None

    async def save(
        self,
        provider: str,
        template: Template,
        metadata: Payload,
        *,
        token: str | None = None,
    ) -> None:
        """Save metadata for a checked revision; lifecycle callers supply their gate token."""
        async with self._database.session(write=True) as session:
            parent = await locked_template(session, template.label)
            require_idle(parent, token)
            if parent.revision != template.revision:
                raise NotifierError(
                    ErrorCode.TEMPLATE_CHANGED,
                    "Template changed during provider operation; retry",
                )
            row = await session.get(TemplateProviderRecord, (template.label, provider))
            if row is None:
                session.add(
                    TemplateProviderRecord(
                        template_label=template.label,
                        provider=provider,
                        provider_metadata=metadata,
                        template_revision=template.revision,
                    )
                )
            else:
                row.provider_metadata = metadata
                row.template_revision = template.revision

    async def remove(self, provider: str, template: str, *, token: str) -> None:
        """Remove linkage only after the provider confirms removal."""
        async with self._database.session(write=True) as session:
            parent = await locked_template(session, template)
            require_idle(parent, token)
            row = await session.get(TemplateProviderRecord, (template, provider))
            if row is not None:
                await session.delete(row)
                parent.lifecycle_identity = uuid4().hex

    async def release_interrupted(
        self, template: str, *, confirmed_stopped: bool
    ) -> None:
        """Explicitly release a gate only after the caller confirms its owner stopped."""
        if not confirmed_stopped:
            raise NotifierError(
                ErrorCode.INVALID_REQUEST,
                "Confirm the interrupted operation is no longer running before recovery",
            )
        async with self._database.session(write=True) as session:
            parent = await locked_template(session, template)
            await require_no_active_jobs(session, template)
            parent.operation_token = None

    async def operation_identity(self, template: str, *, token: str) -> str:
        """Identify this resource generation, stable on retries but renewed after removal."""
        async with self._database.session() as session:
            parent = await locked_template(session, template)
            require_idle(parent, token)
            return parent.lifecycle_identity
