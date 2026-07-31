from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel


class LinearModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PageInfo(LinearModel):
    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")


class Connection[NodeT](LinearModel):
    page_info: PageInfo = Field(alias="pageInfo")
    nodes: list[NodeT]


class NodeList[NodeT](LinearModel):
    nodes: list[NodeT]


class ResponsePayload(RootModel[dict[str, object]]):
    root: dict[str, object]
