from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class AiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )
