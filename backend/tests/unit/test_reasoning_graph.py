"""Phase 3 reasoning-graph domain and SQLAlchemy adapter tests."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reasoning_graph import GraphEdgeRow, GraphNodeRow
from app.db.reasoning_graph import SqlAlchemyReasoningGraphStore, _query_fingerprint
from app.domain import (
    ActorClass,
    ArtifactKind,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    TraversalResult,
)
from tests.traceability import req

U1 = UUID("018f0000-0000-7000-8000-000000000001")
U2 = UUID("018f0000-0000-7000-8000-000000000002")
U3 = UUID("018f0000-0000-7000-8000-000000000003")
U4 = UUID("018f0000-0000-7000-8000-000000000004")
U5 = UUID("018f0000-0000-7000-8000-000000000005")


def node(**changes: object) -> GraphNode:
    values: dict[str, object] = {
        "id": U1,
        "workspace_id": U2,
        "session_id": U3,
        "kind": ArtifactKind.CLAIM,
        "ref_id": U4,
        "label": "A claim",
        "attrs": {"review": "PROPOSED"},
    }
    values.update(changes)
    return GraphNode.model_validate(values)


def edge(**changes: object) -> GraphEdge:
    values: dict[str, object] = {
        "id": U5,
        "workspace_id": U2,
        "session_id": U3,
        "from_node": U1,
        "to_node": U4,
        "edge_type": GraphEdgeType.SUPPORTS,
        "weight": 0.75,
        "qualifier": {"strength": "MODERATE"},
        "actor_class": ActorClass.AGENT,
        "actor_id": U5,
    }
    values.update(changes)
    return GraphEdge.model_validate(values)


@req("NFR-016")
@pytest.mark.parametrize("label", ["", "   "])
def test_graph_node_rejects_blank_labels(label: str) -> None:
    with pytest.raises(ValidationError, match="label"):
        node(label=label)


@req("NFR-016")
@pytest.mark.parametrize("field", ["attrs", "qualifier"])
def test_graph_values_reject_non_json_values(field: str) -> None:
    with pytest.raises((TypeError, ValidationError)):
        (node if field == "attrs" else edge)(**{field: {"invalid": object()}})


@req("NFR-016")
@pytest.mark.parametrize("weight", [-0.01, 1.01])
def test_graph_edge_rejects_out_of_range_weight(weight: float) -> None:
    with pytest.raises(ValidationError, match="weight"):
        edge(weight=weight)


@req("NFR-016")
def test_graph_edge_rejects_self_loop() -> None:
    with pytest.raises(ValidationError, match="self-loops"):
        edge(to_node=U1)


@req("NFR-016")
async def test_adapter_maps_node_and_flushes_without_committing() -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    await store.add_node(node())

    row = session.add.call_args.args[0]
    assert isinstance(row, GraphNodeRow)
    assert (row.id, row.kind, row.attrs) == (U1, "CLAIM", {"review": "PROPOSED"})
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_called()


@req("NFR-016")
async def test_adapter_maps_edge_and_flushes_without_committing() -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    await store.add_edge(edge())

    row = session.add.call_args.args[0]
    assert isinstance(row, GraphEdgeRow)
    assert str(row.weight) == "0.75"
    assert (row.edge_type, row.actor_class) == ("SUPPORTS", "AGENT")
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_called()


@req("NFR-016")
@pytest.mark.parametrize("max_depth", [-1, 13])
async def test_trace_backward_rejects_out_of_range_depth(max_depth: int) -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    with pytest.raises(ValueError, match="max_depth"):
        await store.trace_backward(U2, U3, U1, max_depth=max_depth)

    session.execute.assert_not_called()


@req("NFR-016")
@pytest.mark.parametrize("max_depth", [-1, 6])
async def test_subgraph_rejects_out_of_range_depth(max_depth: int) -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    with pytest.raises(ValueError, match="max_depth"):
        await store.subgraph(U2, U3, (U1,), max_depth=max_depth)

    session.execute.assert_not_called()


@req("NFR-016")
async def test_subgraph_rejects_empty_root_ids() -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    with pytest.raises(ValueError, match="at least one root id"):
        await store.subgraph(U2, U3, ())


@req("NFR-016")
async def test_trace_backward_returns_empty_result_without_node_query_when_walk_finds_nothing() -> (
    None
):
    session = MagicMock(spec=AsyncSession)
    walk_result = MagicMock()
    walk_result.all = MagicMock(return_value=[])

    async def _execute(*_args: object, **_kwargs: object) -> MagicMock:
        return walk_result

    session.execute = _execute
    store = SqlAlchemyReasoningGraphStore(session)

    result = await store.trace_backward(U2, U3, U1)

    assert result == TraversalResult(nodes=(), edges=(), truncated=False)


@req("NFR-016")
@pytest.mark.parametrize("page_size", [0, 201])
async def test_traversal_rejects_out_of_range_page_size(page_size: int) -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    with pytest.raises(ValueError, match="page_size"):
        await store.trace_forward(U2, U3, U1, page_size=page_size)

    session.execute.assert_not_called()


@req("NFR-016")
def test_cursor_fingerprint_distinguishes_no_filter_from_empty_filter() -> None:
    unfiltered = _query_fingerprint("forward", U2, U3, (U1,), 12, None)
    empty_filter = _query_fingerprint("forward", U2, U3, (U1,), 12, frozenset())

    assert unfiltered != empty_filter


@req("NFR-016")
@pytest.mark.parametrize("cursor", ["not-base64!", "e30"])
async def test_traversal_rejects_malformed_cursor(cursor: str) -> None:
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyReasoningGraphStore(session)

    with pytest.raises(ValueError, match="invalid traversal cursor"):
        await store.trace_forward(U2, U3, U1, cursor=cursor)

    session.execute.assert_not_called()
