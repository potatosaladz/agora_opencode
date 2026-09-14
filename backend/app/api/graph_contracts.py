"""Authored request contract for the bounded reasoning-graph read boundary."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.reasoning import GraphEdgeType


class GraphSubgraphRequest(BaseModel):
    """One exact, cursor-bound subgraph query using public identifiers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: Annotated[str, Field(min_length=1)]
    root_ids: Annotated[list[str], Field(min_length=1, max_length=200)]
    max_depth: Annotated[int, Field(ge=0, le=5)] = 2
    edge_types: list[str] | None = None
    page_size: Annotated[int, Field(ge=1, le=200)] = 100
    cursor: str | None = None

    @field_validator("root_ids")
    @classmethod
    def roots_are_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("root_ids must be unique")
        return value

    @field_validator("edge_types")
    @classmethod
    def edge_types_are_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("edge_types must be unique")
        if value is not None:
            allowed = {item.value for item in GraphEdgeType}
            if any(item not in allowed for item in value):
                raise ValueError("edge_types contains an unknown relationship")
        return value
