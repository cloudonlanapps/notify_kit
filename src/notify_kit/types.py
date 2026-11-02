"""JSON-compatible values shared by provider and storage contracts."""

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type Payload = dict[str, JsonValue]
