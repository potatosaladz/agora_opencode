"""Immutable ordered metric catalogue with exact versioned lookup.

The catalogue is the T13-01 shipped registry: every admissible `MetricDefinition` is
validated at construction, ordering is deterministic by dimension, and lookup is exact
(`metric_id` + `metric_version`) — there is deliberately no "latest" fallback, because a
value without its exact definition version cannot be rendered honestly (NFR-019).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.ports.metrics import MetricDefinition, MetricDimension

__all__ = [
    "MetricCatalogue",
    "MetricCatalogueError",
    "UnknownMetricIdError",
    "UnknownMetricVersionError",
]


class MetricCatalogueError(ValueError):
    """Base class for catalogue construction and lookup failures."""


class UnknownMetricIdError(MetricCatalogueError):
    def __init__(self, metric_id: str) -> None:
        super().__init__(f"unknown metric id: {metric_id}")
        self.metric_id = metric_id


class UnknownMetricVersionError(MetricCatalogueError):
    def __init__(self, metric_id: str, metric_version: str) -> None:
        super().__init__(f"unknown metric version {metric_version!r} for {metric_id}")
        self.metric_id = metric_id
        self.metric_version = metric_version


# trace: FR-902, NFR-019
class MetricCatalogue:
    """An immutable, deterministically ordered registry of metric definitions."""

    __slots__ = ("_definitions", "_index")

    def __init__(self, definitions: Sequence[MetricDefinition]) -> None:
        registered: list[MetricDefinition] = []
        ids: set[str] = set()
        keys: set[tuple[str, str]] = set()
        for definition in definitions:
            if definition.metric_id in ids:
                raise MetricCatalogueError(f"duplicate metric id: {definition.metric_id}")
            key = (definition.metric_id, definition.metric_version)
            if key in keys:
                raise MetricCatalogueError(f"duplicate metric version: {key}")
            ids.add(definition.metric_id)
            keys.add(key)
            registered.append(definition)
        if not registered:
            raise MetricCatalogueError("catalogue cannot be empty")
        self._definitions = tuple(
            sorted(
                registered,
                key=lambda item: (
                    item.dimension.value,
                    item.metric_id,
                    item.metric_version,
                ),
            )
        )
        self._index = {(item.metric_id, item.metric_version): item for item in self._definitions}

    def all(self) -> tuple[MetricDefinition, ...]:
        """Every registered definition, ordered deterministically by dimension."""
        return self._definitions

    def active(self) -> tuple[MetricDefinition, ...]:
        """Every non-deprecated definition (retirement is explicit, METRICS.md §8)."""
        return tuple(item for item in self._definitions if not item.deprecated)

    def definitions_for(self, dimension: MetricDimension) -> tuple[MetricDefinition, ...]:
        """Every definition in one profile dimension, in catalogue order."""
        return tuple(item for item in self._definitions if item.dimension is dimension)

    def dimensions(self) -> tuple[MetricDimension, ...]:
        """The dimension order of the profile; never a derived single score."""
        return tuple(dict.fromkeys(item.dimension for item in self._definitions))

    def get(self, metric_id: str, metric_version: str) -> MetricDefinition:
        """Exact versioned lookup; no metric version may be omitted."""
        known = {item.metric_id for item in self._definitions}
        if metric_id not in known:
            raise UnknownMetricIdError(metric_id)
        definition = self._index.get((metric_id, metric_version))
        if definition is None:
            raise UnknownMetricVersionError(metric_id, metric_version)
        return definition

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, metric_id: str) -> bool:
        return metric_id in {item.metric_id for item in self._definitions}
