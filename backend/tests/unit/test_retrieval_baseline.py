"""T5-09 versioned retrieval baseline contract and metric caveats."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.retrieval_baseline import BaselineCorpus, evaluate_baseline
from tests.traceability import req

FIXTURE = Path(__file__).parents[1] / "fixtures" / "retrieval_baseline_v1.json"


def _corpus() -> BaselineCorpus:
    return BaselineCorpus.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


@req("FR-404")
def test_fr404_versioned_baseline_records_labels_versions_and_metric_caveats() -> None:
    corpus = _corpus()

    assert corpus.corpus_version == "mechanics-synthetic-v1"
    assert corpus.label_version == "mechanics-labels-v1"
    assert corpus.chunker_version == "agora-whitespace-v1"
    assert {source.status for source in corpus.sources} == {"READY", "RETRACTED"}
    assert {source.namespace for source in corpus.sources} == {"AUTHORIZED", "UNAUTHORIZED"}
    assert len(corpus.caveats) == 5
    assert any("not scientific correctness" in caveat for caveat in corpus.caveats)
    assert any("Phase 16" in caveat for caveat in corpus.caveats)


@req("FR-404")
def test_fr404_baseline_reports_macro_recall_proxy_and_precision_at_k() -> None:
    corpus = _corpus()
    retrieved = {
        query.id: (query.relevant_chunk_ids[0], UUID(int=index + 1))
        for index, query in enumerate(corpus.queries)
    }

    result = evaluate_baseline(corpus, retrieved)

    assert result.recall_proxy == 1.0
    assert result.precision_at_k == 0.5
    assert all(query.recall_proxy == 1.0 for query in result.query_results)


@req("FR-404")
def test_fr404_baseline_rejects_missing_query_results_and_duplicate_hits() -> None:
    corpus = _corpus()

    with pytest.raises(ValueError, match="exactly match"):
        evaluate_baseline(corpus, {})
    duplicate = corpus.queries[0].relevant_chunk_ids[0]
    retrieved = {query.id: query.relevant_chunk_ids for query in corpus.queries}
    retrieved[corpus.queries[0].id] = (duplicate, duplicate)
    with pytest.raises(ValueError, match="must be unique"):
        evaluate_baseline(corpus, retrieved)


@req("FR-404")
def test_fr404_baseline_contract_rejects_unversioned_or_blank_caveat_data() -> None:
    values = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del values["label_version"]
    with pytest.raises(ValidationError):
        BaselineCorpus.model_validate_json(json.dumps(values))

    values = json.loads(FIXTURE.read_text(encoding="utf-8"))
    values["caveats"] = [" "]
    with pytest.raises(ValidationError, match="must not be blank"):
        BaselineCorpus.model_validate_json(json.dumps(values))
