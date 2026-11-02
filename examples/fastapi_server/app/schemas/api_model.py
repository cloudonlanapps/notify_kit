from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Strict-field API schema with support for package dataclass responses."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, allow_inf_nan=False)
