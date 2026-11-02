import hashlib

from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.template_operation import TemplateOperation
from notify_kit.provider import NotifyProvider
from notify_kit.services.provider_calls import provider_call
from notify_kit.services.serialization import snapshot_payload
from notify_kit.storage.database_storage import DatabaseStorage
from notify_kit.types import Payload


class TemplateLifecycle:
    """Coordinate explicit registration, update and removal per template/provider link."""

    def __init__(self, storage: DatabaseStorage) -> None:
        """Attach kit storage without owning application provider instances."""
        self._storage = storage

    async def mutate(
        self,
        name: str,
        provider: NotifyProvider,
        label: str,
        operation: TemplateOperation,
    ) -> Payload | None:
        """Guard changes against active jobs and persist only confirmed provider results."""
        template = await self._storage.templates.get(label)
        token = await self._storage.links.begin(template)
        try:
            metadata = await self._storage.links.get(name, label)
            identity = await self._storage.links.operation_identity(
                name, label, token=token
            )
            key = hashlib.sha256(
                f"{operation}\0{name}\0{label}\0{template.revision}\0{identity}".encode()
            ).hexdigest()
            if operation == TemplateOperation.REGISTER:
                if metadata is not None:
                    raise NotifierError(
                        ErrorCode.ALREADY_EXISTS,
                        "Template is already linked; use template_update",
                        provider=name,
                    )
                result = await provider_call(
                    name,
                    operation,
                    lambda: provider.register_template(
                        template=template, idempotency_key=key
                    ),
                )
            elif metadata is None:
                raise NotifierError(
                    ErrorCode.TEMPLATE_NOT_REGISTERED,
                    "Template has no linkage for this provider",
                    provider=name,
                )
            elif operation == TemplateOperation.UPDATE:
                result = await provider_call(
                    name,
                    operation,
                    lambda: provider.update_template(
                        template=template, metadata=metadata, idempotency_key=key
                    ),
                )
            else:
                await provider_call(
                    name,
                    operation,
                    lambda: provider.unregister_template(
                        template=template, metadata=metadata, idempotency_key=key
                    ),
                )
                await self._storage.links.remove(name, label, token=token)
                return None
            result = snapshot_payload(result)
            await self._storage.links.save(name, template, result, token=token)
            return result
        finally:
            await self._storage.links.end(label, token)
