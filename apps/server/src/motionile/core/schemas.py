from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class StrictModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


class ResponseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        from_attributes=True,
        frozen=True,
    )


class CursorPage[ItemT](ResponseModel):
    items: list[ItemT]
    next_cursor: str | None = Field(default=None, description="Opaque cursor for the next page; null on the last page")


class PageQuery(StrictModel):
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
