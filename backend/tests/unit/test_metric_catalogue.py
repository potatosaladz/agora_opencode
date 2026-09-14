"""Focused T13-01 acceptance tests for the shipped metric catalogue."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.metrics import build_metric_catalogue, metric_catalogue
from app.domain.metrics import (
    MetricCatalogue,
    MetricCatalogueError,
    UnknownMetricIdError,
    UnknownMetricVersionError,
)
from app.ports.metrics import (
    MetricDefinition,
    MetricDimension,
    MetricDirection,
    MetricSubjectKind,
    MetricValue,
    MetricValueStatus,
)
from tests.traceability import req

WORKSPACE = UUID("00000000-0000-0000-0000-000000000001")
SESSION = UUID("00000000-0000-0000-0000-000000000002")
_SAMPLE_HASH = "sha256:" + "0" * 64

# Transcribed from docs/METRICS.md §4: (label, direction, kind, lower, upper, unit).
EXPECTED_CATALOGUE = {
    "ep-01": ("evidence coverage", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "ep-02": ("provenance completeness", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "ep-03": ("verified evidence ratio", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "ep-04": ("source independence", "HIGHER_BETTER", "INTERVAL", 0.0, None, None),
    "ep-05": ("hallucinated source rate", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "ep-06": ("evidence gap count", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "rr-01": ("unsupported claim ratio", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "rr-02": ("assumption depth", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "rr-03": ("inference validity rate", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "rr-04": ("contradiction density", "NO_DIRECTION", "INTERVAL", 0.0, 1.0, None),
    "rr-05": ("formalization rate", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "rr-06": ("feasibility pass rate", "NO_DIRECTION", "INTERVAL", 0.0, 1.0, None),
    "rr-07": ("solver unknown rate", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "dh-01": ("initial disagreement", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "dh-02": ("disagreement retention", "NO_DIRECTION", "INTERVAL", 0.0, 1.0, None),
    "dh-03": ("attack coverage", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "dh-04": ("critique resolution rate", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "dh-05": ("herding index", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "dh-06": ("revision quality", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "dh-07": ("minority report substance", "NO_DIRECTION", "INTERVAL", 1.0, None, None),
    "cq-01": ("support margin", "HIGHER_BETTER", "INTERVAL", 0.0, None, None),
    "cq-02": ("outcome class", "NO_DIRECTION", "ENUM", None, None, None),
    "cq-03": ("flip distance", "HIGHER_BETTER", "INTERVAL", 0.0, None, None),
    "cq-04": ("abstention rate", "NO_DIRECTION", "INTERVAL", 0.0, 1.0, None),
    "cq-05": ("blocking critique carry-over", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "cq-06": ("strategy divergence", "NO_DIRECTION", "INTERVAL", -1.0, 1.0, None),
    "rb-01": ("ranking stability", "HIGHER_BETTER", "INTERVAL", -1.0, 1.0, None),
    "rb-02": ("assumption sensitivity", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "rb-03": ("model divergence", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "rb-04": ("retrieval robustness", "HIGHER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "rb-05": ("degraded-state frequency", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "ce-01": ("tokens per committed artifact", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "ce-02": ("rounds to terminal", "NO_DIRECTION", "INTERVAL", 1.0, None, None),
    "ce-03": ("cost per session", "LOWER_BETTER", "INTERVAL", 0.0, None, None),
    "ce-04": ("p95 read latency", "LOWER_BETTER", "INTERVAL", 0.0, None, "ms"),
    "ce-05": ("event delivery lag", "LOWER_BETTER", "INTERVAL", 0.0, None, "ms"),
    "ho-01": ("intervention rate", "NO_DIRECTION", "INTERVAL", 0.0, 1.0, None),
    "ho-02": ("override rate", "NO_DIRECTION", "INTERVAL", 0.0, 1.0, None),
    "ho-03": ("explanation engagement", "NO_DIRECTION", "INTERVAL", 0.0, None, None),
    "ho-04": ("unexamined acceptance", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
    "ca-01": ("calibration error", "LOWER_BETTER", "INTERVAL", -1.0, 1.0, None),
    "ca-02": ("Brier score", "LOWER_BETTER", "INTERVAL", 0.0, 2.0, None),
    "ca-03": ("overreach rate", "LOWER_BETTER", "INTERVAL", 0.0, 1.0, None),
}
EXPECTED_DIMENSION_COUNTS = {
    MetricDimension.EVIDENCE: 6,
    MetricDimension.RIGOUR: 7,
    MetricDimension.DISAGREEMENT: 7,
    MetricDimension.CONSENSUS: 6,
    MetricDimension.ROBUSTNESS: 5,
    MetricDimension.COST: 5,
    MetricDimension.OVERSIGHT: 4,
    MetricDimension.CALIBRATION: 3,
}
EXPECTED_PINS = {
    "ep-02": MetricDirection.HIGHER_BETTER,
    "dh-03": MetricDirection.HIGHER_BETTER,
    "dh-02": MetricDirection.NO_DIRECTION,
    "cq-03": MetricDirection.HIGHER_BETTER,
    "ce-03": MetricDirection.LOWER_BETTER,
}


@req("FR-902", "NFR-019")
def test_catalogue_ships_43_active_metric_definitions() -> None:
    catalogue = build_metric_catalogue()
    assert len(catalogue) == 43
    assert len(catalogue.all()) == 43
    assert len(catalogue.active()) == 43
    assert metric_catalogue().all() == catalogue.all()


@req("FR-902", "NFR-019")
def test_dimension_counts_match_the_metrICS_document() -> None:
    catalogue = build_metric_catalogue()
    assert set(catalogue.dimensions()) == set(EXPECTED_DIMENSION_COUNTS)
    assert tuple(catalogue.dimensions()) == tuple(
        sorted(EXPECTED_DIMENSION_COUNTS, key=lambda item: item.value)
    )
    for dimension, expected in EXPECTED_DIMENSION_COUNTS.items():
        assert len(catalogue.definitions_for(dimension)) == expected


@req("FR-902")
def test_every_definition_states_all_six_admission_fields() -> None:
    for definition in build_metric_catalogue().all():
        assert definition.metric_version
        assert definition.label.strip()
        assert definition.formula.strip()
        assert definition.inputs
        assert all(spec.fields for spec in definition.inputs)
        assert definition.range.bounds_meaning.strip()
        assert definition.direction in MetricDirection
        assert definition.interpretation.strip()
        assert len(definition.caveats) >= 1
        assert all(item.strip() for item in definition.caveats)


@req("FR-902", "NFR-019")
def test_registration_order_is_deterministic_and_ids_are_unique() -> None:
    first = build_metric_catalogue()
    second = build_metric_catalogue()
    assert first.all() == second.all()
    ids = [definition.metric_id for definition in first.all()]
    assert len(ids) == len(set(ids)) == 43
    assert sorted(ids) == ids


@req("FR-902")
def test_every_id_prefix_matches_its_dimension() -> None:
    for definition in build_metric_catalogue().all():
        prefix, _, _ = definition.metric_id.partition("-")
        assert prefix == definition.dimension.value.lower()


@req("FR-902")
def test_transcription_matches_the_metrICS_document() -> None:
    catalogue = build_metric_catalogue()
    by_id = {definition.metric_id: definition for definition in catalogue.all()}
    assert set(by_id) == set(EXPECTED_CATALOGUE)
    for metric_id, expected in EXPECTED_CATALOGUE.items():
        definition = by_id[metric_id]
        label, direction, range_kind, lower, upper, unit = expected
        assert definition.label == label
        assert definition.direction.value == direction
        assert definition.range.kind.value == range_kind
        assert definition.range.lower == lower
        assert definition.range.upper == upper
        assert definition.range.unit == unit


@req("FR-902", "NFR-019")
def test_phase_12_reward_pins_resolve_at_version_1() -> None:
    catalogue = build_metric_catalogue()
    for metric_id, direction in EXPECTED_PINS.items():
        definition = catalogue.get(metric_id, "1")
        assert definition.direction is direction
        assert definition.metric_version == "1"
        assert not definition.deprecated


@req("NFR-019")
def test_exact_lookup_has_no_latest_fallback_and_fails_closed() -> None:
    catalogue = build_metric_catalogue()
    assert catalogue.get("ep-01", "1").label == "evidence coverage"
    with pytest.raises(UnknownMetricVersionError):
        catalogue.get("ep-01", "2")
    with pytest.raises(UnknownMetricIdError):
        catalogue.get("zz-01", "1")
    with pytest.raises(UnknownMetricIdError):
        catalogue.get("spe-01", "1")


@req("NFR-019")
def test_duplicate_and_empty_registrations_are_rejected() -> None:
    definition = build_metric_catalogue().get("ep-01", "1")
    with pytest.raises(MetricCatalogueError):
        MetricCatalogue((definition, definition))
    with pytest.raises(MetricCatalogueError):
        MetricCatalogue(())


@req("FR-901", "FR-902")
def test_catalogue_is_a_profile_with_no_aggregate_score() -> None:
    catalogue = build_metric_catalogue()
    assert len(catalogue.dimensions()) == 8
    assert all(len(catalogue.definitions_for(d)) >= 3 for d in catalogue.dimensions())
    assert all(definition.dimension in MetricDimension for definition in catalogue.all())
    assert not any(definition.deprecated for definition in catalogue.all())
    metric_ids = {definition.metric_id for definition in catalogue.all()}
    for definition in catalogue.all():
        referenced = metric_ids.intersection(definition.formula.split())
        assert not referenced, f"{definition.metric_id} composes {referenced}"


@req("NFR-019")
def test_metric_value_carries_m2_metadata() -> None:
    value = MetricValue(
        metric_id="ep-01",
        metric_version="1",
        subject=MetricSubjectKind.SESSION,
        value=0.75,
        sample_size=12,
        inputs_hash=_SAMPLE_HASH,
        code_version="1",
        computation_trace=("counted_supports", "divided_by_total"),
    )
    assert value.value == 0.75
    assert value.sample_size == 12
    assert value.status is MetricValueStatus.IMPLEMENTED
    with pytest.raises(ValidationError):
        MetricValue(
            metric_id="ep-01",
            metric_version="1",
            subject=MetricSubjectKind.SESSION,
            value=0.75,
            sample_size=12,
            inputs_hash="not-a-digest",
            code_version="1",
            computation_trace=("counted_supports",),
        )
    with pytest.raises(ValidationError):
        MetricValue(
            metric_id="ep-01",
            metric_version="1",
            subject=MetricSubjectKind.SESSION,
            value=0.75,
            sample_size=12,
            inputs_hash=_SAMPLE_HASH,
            code_version="1",
            computation_trace=("counted_supports",),
            interval_low=0.9,
            interval_high=0.1,
        )
    with pytest.raises(ValidationError):
        MetricValue(
            metric_id="ep-01",
            metric_version="1",
            subject=MetricSubjectKind.SESSION,
            value=0.75,
            sample_size=12,
            inputs_hash=_SAMPLE_HASH,
            code_version="1",
            computation_trace=(),
        )


@req("NFR-019")
def test_not_applicable_is_a_reasoned_value_never_zero() -> None:
    missing = MetricValue(
        metric_id="ca-01",
        metric_version="1",
        subject=MetricSubjectKind.SESSION,
        value=None,
        sample_size=0,
        inputs_hash=_SAMPLE_HASH,
        code_version="1",
        status=MetricValueStatus.NOT_APPLICABLE,
        not_applicable_reason="no checkable outcomes in this session",
        computation_trace=("no_checkable_outcomes",),
    )
    assert missing.status is MetricValueStatus.NOT_APPLICABLE
    assert missing.not_applicable_reason
    with pytest.raises(ValidationError):
        MetricValue(
            metric_id="ca-01",
            metric_version="1",
            subject=MetricSubjectKind.SESSION,
            value=0.0,
            sample_size=0,
            inputs_hash=_SAMPLE_HASH,
            code_version="1",
            status=MetricValueStatus.NOT_APPLICABLE,
            not_applicable_reason="no checkable outcomes in this session",
            computation_trace=("no_checkable_outcomes",),
        )
    with pytest.raises(ValidationError):
        MetricValue(
            metric_id="ca-01",
            metric_version="1",
            subject=MetricSubjectKind.SESSION,
            value=None,
            sample_size=0,
            inputs_hash=_SAMPLE_HASH,
            code_version="1",
            status=MetricValueStatus.NOT_APPLICABLE,
            computation_trace=("no_checkable_outcomes",),
        )
    with pytest.raises(ValidationError):
        MetricValue(
            metric_id="ep-01",
            metric_version="1",
            subject=MetricSubjectKind.SESSION,
            value=None,
            sample_size=0,
            inputs_hash=_SAMPLE_HASH,
            code_version="1",
            computation_trace=("counted_supports",),
        )


@req("FR-902")
def test_retirement_requires_an_explicit_successor() -> None:
    base = build_metric_catalogue().get("ep-01", "1")
    payload = {
        **base.model_dump(),
        "deprecated": True,
        "successor_metric_id": "ep-02",
    }
    retired = MetricDefinition(**payload)
    assert retired.deprecated
    assert retired.successor_metric_id == "ep-02"
    with pytest.raises(ValidationError):
        MetricDefinition(**{**payload, "successor_metric_id": None})
    with pytest.raises(ValidationError):
        MetricDefinition(**{**base.model_dump(), "deprecated": True, "successor_metric_id": None})
    with pytest.raises(ValidationError):
        MetricDefinition(**{**base.model_dump(), "successor_metric_id": "ep-02"})
