from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A page of a list endpoint. Pass `next_cursor` back as `cursor` to get the next page."""

    items: list[T]
    next_cursor: str | None = None
