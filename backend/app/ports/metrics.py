"""`MetricPlugin` port and metric value objects — PORTS.md §10.

A `MetricDefinition` is an admission-checked, versioned catalogue entry stating the six
fields METRICS.md §2 requires.  A `MetricValue` either carries a finite JSON scalar plus
its mandatory metadata, or is `NOT_APPLICABLE` with a reason — never `0`
(METRICS.md M-4).  No plugin may emit a single aggregate "quality score"
(METRICS.md §1, FR-901).

Nothing here may import an infrastructure SDK, and nothing here may import
`app.adapters` or `app.domain` — enforced by `tests/test_layering.py`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "MetricContext",
    "MetricDefinition",
    "MetricDimension",
    "MetricDirection",
    "MetricInputSpec",
    "MetricPlugin",
    "MetricRange",
    "MetricRangeKind",
    "MetricSubjectKind",
    "MetricValue",
    "MetricValueStatus",
]

_METRIC_ID_RE = re.compile(r"^(?P<dim>[a-z]{2})-(?P<num>[0-9]{2})$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _metric_id(value: str) -> str:
    if not _METRIC_ID_RE.fullmatch(value):
        raise ValueError("metric id must match <dimension>-<nn>")
    return value


def _identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError("identifier must be lowercase ASCII and version-stable")
    return value


def _version(value: str) -> str:
    if not _VERSION_RE.fullmatch(value):
        raise ValueError("version must be stable ASCII")
    return value


def _digest(value: str) -> str:
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError("digest must be a sha256 content hash in project format")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _closed_json(value: Any, *, _depth: int = 0) -> None:
    if _depth > 64:
        raise ValueError("closed JSON document is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _closed_json(item, _depth=_depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _closed_json(item, _depth=_depth + 1)
        return
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise TypeError(f"unsupported non-JSON value: {type(value).__name__}")


def _scalar(value: Any) -> None:
    """A metric value is a single finite JSON number, string, or boolean."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise TypeError("metric value must be a finite JSON scalar")


class MetricDimension(StrEnum):
    """The eight profile dimensions — METRICS.md §3."""

    EVIDENCE = "EP"
    RIGOUR = "RR"
    DISAGREEMENT = "DH"
    CONSENSUS = "CQ"
    ROBUSTNESS = "RB"
    COST = "CE"
    OVERSIGHT = "HO"
    CALIBRATION = "CA"


class MetricDirection(StrEnum):
    """How a value should be read; descriptive only (METRICS.md §2)."""

    HIGHER_BETTER = "HIGHER_BETTER"
    LOWER_BETTER = "LOWER_BETTER"
    NO_DIRECTION = "NO_DIRECTION"


class MetricSubjectKind(StrEnum):
    """What a `MetricValue` is measured over — METRICS.md §6."""

    SESSION = "SESSION"
    AGENT = "AGENT"
    ALTERNATIVE = "ALTERNATIVE"
    CLAIM = "CLAIM"


class MetricRangeKind(StrEnum):
    INTERVAL = "INTERVAL"
    ENUM = "ENUM"


class MetricRange(_Frozen):
    """Declared numeric or enumerated range plus the meaning of its bounds."""

    kind: MetricRangeKind
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    bounds_meaning: str

    @field_validator("bounds_meaning")
    @classmethod
    def _meaning(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("bounds_meaning must not be blank")
        return value

    @model_validator(mode="after")
    def consistent(self) -> MetricRange:
        if self.kind is MetricRangeKind.ENUM:
            if self.lower is not None or self.upper is not None or self.unit is not None:
                raise ValueError("enum range must not carry numeric bounds or a unit")
            return self
        if self.lower is None and self.upper is None:
            raise ValueError("interval range needs at least one bound")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("interval lower bound exceeds its upper bound")
        return self


class MetricInputSpec(_Frozen):
    """One named artifact set a definition consumes, with the fields it reads."""

    name: str
    kind: str
    version: str
    fields: tuple[str, ...]
    description: str

    _name = field_validator("name")(_identifier)
    _kind = field_validator("kind")(_identifier)
    _version = field_validator("version")(_version)

    @field_validator("fields")
    @classmethod
    def _fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("inputs must name the fields consumed")
        return tuple(dict.fromkeys(values))

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input description must not be blank")
        return value


class MetricDefinition(_Frozen):
    """An admissible, versioned metric with all six admission fields (FR-902)."""

    metric_id: str
    metric_version: str
    dimension: MetricDimension
    label: str
    formula: str
    inputs: tuple[MetricInputSpec, ...]
    range: MetricRange
    direction: MetricDirection
    interpretation: str
    caveats: tuple[str, ...]
    deprecated: bool = False
    successor_metric_id: str | None = None

    _metric_id = field_validator("metric_id")(_metric_id)
    _metric_version = field_validator("metric_version")(_version)

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, values: tuple[MetricInputSpec, ...]) -> tuple[MetricInputSpec, ...]:
        if not values:
            raise ValueError("a metric must state at least one input")
        return values

    @field_validator("caveats")
    @classmethod
    def _caveats(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or any((not item.strip()) for item in values):
            raise ValueError("a metric needs at least one non-blank caveat")
        return values

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value

    @field_validator("formula")
    @classmethod
    def _formula(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("formula must state a computable expression")
        return value

    @field_validator("interpretation")
    @classmethod
    def _interpretation(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("interpretation must not be blank")
        return value

    @model_validator(mode="after")
    def identity_consistent(self) -> MetricDefinition:
        match = _METRIC_ID_RE.fullmatch(self.metric_id)
        if match is None or match.group("dim") != self.dimension.value.lower():
            raise ValueError("metric id prefix must match its dimension")
        return self

    @model_validator(mode="after")
    def successor_consistent(self) -> MetricDefinition:
        if self.deprecated and self.successor_metric_id is None:
            raise ValueError("deprecated definition requires a successor metric id")
        if not self.deprecated and self.successor_metric_id is not None:
            raise ValueError("only deprecated definitions may name a successor")
        return self


class MetricContext(_Frozen):
    """Immutable inputs a plugin computes against; closed JSON, content-hashed."""

    schema_version: Literal[1] = 1
    workspace_id: UUID
    session_id: UUID
    round_index: int = Field(ge=0)
    subject: MetricSubjectKind = MetricSubjectKind.SESSION
    subject_id: UUID | None = None
    inputs: Any
    inputs_hash: str

    _inputs_hash = field_validator("inputs_hash")(_digest)

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, value: Any) -> Any:
        _closed_json(value)
        return value


class MetricValueStatus(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MetricValue(_Frozen):
    """One measured value with the metadata required before it may be rendered (M-2)."""

    schema_version: Literal[1] = 1
    metric_id: str
    metric_version: str
    subject: MetricSubjectKind
    subject_id: UUID | None = None
    value: Any
    interval_low: float | None = None
    interval_high: float | None = None
    sample_size: int = Field(ge=0)
    inputs_hash: str
    code_version: str
    status: MetricValueStatus = MetricValueStatus.IMPLEMENTED
    not_applicable_reason: str | None = None
    computation_trace: tuple[str, ...]

    _metric_id = field_validator("metric_id")(_metric_id)
    _metric_version = field_validator("metric_version")(_version)
    _inputs_hash = field_validator("inputs_hash")(_digest)
    _code_version = field_validator("code_version")(_version)

    @field_validator("computation_trace")
    @classmethod
    def _trace(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or any((not item.strip()) for item in values):
            raise ValueError("computation_trace must record at least one step")
        return values

    @model_validator(mode="after")
    def status_consistent(self) -> MetricValue:
        if self.status is MetricValueStatus.NOT_APPLICABLE:
            if self.value is not None:
                raise ValueError("not-applicable value must be None")
            if not self.not_applicable_reason or not self.not_applicable_reason.strip():
                raise ValueError("not-applicable value requires a reason")
        else:
            if self.value is None:
                raise ValueError("implemented value must be a finite JSON scalar")
            if self.not_applicable_reason is not None:
                raise ValueError("implemented value must not carry a not-applicable reason")
            _scalar(self.value)
        if (
            self.interval_low is not None
            and self.interval_high is not None
            and self.interval_low > self.interval_high
        ):
            raise ValueError("interval lower bound exceeds its upper bound")
        return self


@runtime_checkable
class MetricPlugin(Protocol):
    """PORTS.md §10 — `name` is a catalogue `metric_id`, `version` its definition version."""

    name: str
    version: str

    def definition(self) -> MetricDefinition: ...
    async def compute(self, context: MetricContext) -> MetricValue: ...
