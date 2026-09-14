"""Workspace-wide source-impact analysis and transactional retraction service."""

from __future__ import annotations

from collections import defaultdict, deque
from uuid import UUID

from app.domain.citations import SourceRetractionCommand
from app.domain.reasoning_graph import DEFAULT_MAX_DEPTH, MAX_PAGE_SIZE, GraphEdge, GraphNode
from app.domain.source_impact import (
    ImpactAnalysisResult,
    ImpactAnalysisStatus,
    ImpactDependency,
    SourceImpactReport,
    SourceImpactRepository,
)

__all__ = ["SourceImpactService"]


# trace: FR-408
class SourceImpactService:
    """Compose canonical citation roots with exhaustive T10-01 forward traversals."""

    def __init__(self, repository: SourceImpactRepository) -> None:
        self._repository = repository

    async def impact_of(self, workspace_id: UUID, source_id: UUID) -> ImpactAnalysisResult:
        await self._repository.lock_source_for_analysis(workspace_id, source_id)
        citations = await self._repository.citation_roots(workspace_id, source_id)
        roots = sorted(
            {(item.session_id, item.evidence_artifact_id) for item in citations},
            key=lambda item: (str(item[0]), str(item[1])),
        )
        aggregate: dict[tuple[UUID, UUID, UUID], tuple[GraphNode, UUID, int, int]] = {}
        truncated = False
        dependencies: tuple[ImpactDependency, ...] = ()
        try:
            for session_id, evidence_id in roots:
                root = await self._repository.graph.node_for_artifact(
                    workspace_id, session_id, evidence_id
                )
                if root is None:
                    truncated = True
                    continue
                queue: deque[GraphNode] = deque([root])
                expanded: set[UUID] = set()
                root_nodes: dict[UUID, GraphNode] = {}
                root_edges: dict[UUID, GraphEdge] = {}
                while queue:
                    frontier = queue.popleft()
                    if frontier.id in expanded:
                        continue
                    expanded.add(frontier.id)
                    cursor: str | None = None
                    nodes: dict[UUID, GraphNode] = {}
                    edges: dict[UUID, GraphEdge] = {}
                    segment_truncated = False
                    while True:
                        page = await self._repository.graph.trace_forward(
                            workspace_id,
                            session_id,
                            frontier.id,
                            max_depth=DEFAULT_MAX_DEPTH,
                            page_size=MAX_PAGE_SIZE,
                            cursor=cursor,
                        )
                        nodes.update((node.id, node) for node in page.nodes)
                        edges.update((edge.id, edge) for edge in page.edges)
                        segment_truncated = segment_truncated or page.truncated
                        cursor = page.next_cursor
                        if cursor is None:
                            break
                    root_nodes.update(nodes)
                    root_edges.update(edges)
                    if segment_truncated:
                        continuation = [node for node in nodes.values() if node.id not in expanded]
                        if not continuation:
                            truncated = True
                        queue.extend(sorted(continuation, key=lambda item: str(item.id)))
                edge_values = tuple(root_edges.values())
                for node in root_nodes.values():
                    depth = self._shortest_depth(root, node, edge_values)
                    paths = self._path_count(root, node, edge_values)
                    aggregate[(node.ref_id, node.session_id, evidence_id)] = (
                        node,
                        evidence_id,
                        depth,
                        paths,
                    )

            artifacts = await self._repository.artifact_dependencies(
                workspace_id,
                tuple(
                    sorted(
                        aggregate.values(),
                        key=lambda item: (item[2], str(item[0].ref_id), str(item[1])),
                    )
                ),
            )
            if len(artifacts) != len(aggregate):
                truncated = True
            downstream = await self._repository.downstream_records(workspace_id, artifacts)
            dependencies = tuple(sorted((*artifacts, *downstream), key=_dependency_key))
        except Exception as exc:
            return ImpactAnalysisResult(
                status=ImpactAnalysisStatus.INCOMPLETE,
                complete=False,
                truncated=True,
                dependencies=dependencies,
                error=str(exc),
            )
        return ImpactAnalysisResult(
            status=ImpactAnalysisStatus.INCOMPLETE if truncated else ImpactAnalysisStatus.COMPLETE,
            complete=not truncated,
            truncated=truncated,
            dependencies=dependencies,
        )

    async def retract_source(
        self,
        command: SourceRetractionCommand,
        *,
        report_id: UUID,
        event_id: UUID,
        correlation_id: UUID,
    ) -> SourceImpactReport:
        analysis = await self.impact_of(command.workspace_id, command.source_id)
        return await self._repository.retract_and_report(
            command,
            report_id=report_id,
            event_id=event_id,
            correlation_id=correlation_id,
            analysis=analysis,
        )

    async def get_report(self, workspace_id: UUID, report_id: UUID) -> SourceImpactReport | None:
        return await self._repository.get_report(workspace_id, report_id)

    @staticmethod
    def _shortest_depth(root: GraphNode, target: GraphNode, edges: tuple[GraphEdge, ...]) -> int:
        if root.id == target.id:
            return 0
        adjacency: dict[UUID, list[UUID]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.from_node].append(edge.to_node)
        queue: deque[tuple[UUID, int]] = deque([(root.id, 0)])
        visited = {root.id}
        while queue:
            node_id, depth = queue.popleft()
            for child in adjacency[node_id]:
                if child == target.id:
                    return depth + 1
                if child not in visited:
                    visited.add(child)
                    queue.append((child, depth + 1))
        return DEFAULT_MAX_DEPTH

    @staticmethod
    def _path_count(root: GraphNode, target: GraphNode, edges: tuple[GraphEdge, ...]) -> int:
        if root.id == target.id:
            return 1
        adjacency: dict[UUID, list[UUID]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.from_node].append(edge.to_node)
        count = 0
        stack: list[tuple[UUID, frozenset[UUID]]] = [(root.id, frozenset({root.id}))]
        while stack:
            node_id, visited = stack.pop()
            for child in adjacency[node_id]:
                if child == target.id:
                    count += 1
                elif child not in visited:
                    stack.append((child, visited | {child}))
        return max(1, count)


def _dependency_key(item: ImpactDependency) -> tuple[str, int, str]:
    return item.dependency_type.value, item.min_depth, str(item.dependent_id)
