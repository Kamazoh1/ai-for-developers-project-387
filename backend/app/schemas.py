from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base for API payloads: camelCase on the wire, as in the contract."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
