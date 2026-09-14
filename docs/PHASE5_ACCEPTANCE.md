# Phase 5 Acceptance Evidence

**As of:** 2026-09-06 · **Status:** local exit candidate; exact-SHA CI pending

<!-- trace: FR-402, FR-404, FR-409 -->
## Baseline contract

`backend/tests/fixtures/retrieval_baseline_v1.json` is the committed source of truth for synthetic
sources, documents, chunks, lifecycle states, authorization partition, deterministic vector axes,
queries, reviewed relevance labels, exact expected output, component versions, and caveats. It uses
only domain-neutral rotational-mechanics examples and makes no Phase 16 domain choice.

The live PostgreSQL gate uses production candidate search, deterministic RRF, no-op reranking,
UUID-backed pgvector rows, provenance hydration, and append-only retrieval audit. It proves:

- exact lexical, vector/paraphrase, table/heading, duplicate, retracted, and unauthorized cases;
- every hit resolves stored chunk and source SHA-256 digests;
- retracted and unauthorized chunks never appear;
- denied namespace access fails closed and persists a text-free `DENIED` audit;
- expected-match zero results persist `RAG_FAILED` and raise the stable retryable error;
- exact retrieved chunk order matches the versioned fixture.

## Baseline values and caveats

| Metric | Local value | Interpretation |
| --- | ---: | --- |
| reviewed-label recall proxy | 1.0 | all committed relevant labels retrieved; not open-world ground-truth recall |
| precision at 2 | 0.5 | fixed denominator; unfilled slots count non-relevant |
| focused PostgreSQL gate | 5.44 s | host-specific test duration, not latency SLO |

Quality values establish comparison baseline only. They are not scientific correctness, benchmark
leadership, or hard quality thresholds. Provenance resolution, exact deterministic output, isolation,
and explicit failure behavior are blocking gates.

<!-- trace: FR-403, FR-405, FR-406, FR-407, FR-408 -->
## FR-401–409 disposition

| Requirement | Phase 5 evidence | Status |
| --- | --- | --- |
| FR-401 | deterministic parsers and structure-aware chunking for all eight formats; unsupported media fails explicitly | implemented |
| FR-402 | hydrated source/document/chunk/locator/hash/trust chain; live digest resolution | implemented |
| FR-403 | retrieved data stays unverified evidence; agent-owned facts remain rejected | implemented |
| FR-404 | PostgreSQL lexical/vector candidates grant/ACL-filtered before scoring; RRF and strict reranker port; versioned baseline | implemented |
| FR-405 | six explicit namespace tiers and PostgreSQL-validated grants | implemented |
| FR-406 | semantic promotion requires active human validation, evidence, caveats, and lifecycle history | implemented |
| FR-407 | manual evidence citation requires active human attribution and exact stored provenance | implemented |
| FR-408 | Phase 5 preserves irreversible retraction and citation dependency facts; Phase 10 now adds complete/incomplete workspace-wide impact reports and atomic `SOURCE_RETRACTED` outbox publication | implemented across Phases 5 and 10 |
| FR-409 | expected-match intent and infrastructure failures produce durable `RAG_FAILED`, never silent empty success | implemented |

## Observed local gates

- Ruff format: 204 files formatted; Ruff lint green.
- Strict mypy: 204 source files green.
- Focused retrieval unit tests: 16 passed.
- Focused migration lifecycle plus PostgreSQL baseline: 2 passed in 34.16 s.
- Full offline backend suite: 370 passed, 40 integrations deselected.
- Full live Compose-backed suite: 40 passed with no skips; PostgreSQL, Redis, MinIO, NATS and Temporal
  test settings were configured against the healthy running stack.
- Frontend: lint and strict typecheck green; 19 tests passed; production build and generated-client
  contract drift check green after regenerating `frontend/src/api/types.ts`.
- Authored contracts: 16 paths and 15 error codes valid. Traceability: 47 rows, all 8 Phase 5 mappings
  plus the FR-408 dependency valid. Links: 87 Markdown files valid. `git diff --check`: green.
- Windows `npm run format` still reports the 36 pre-existing checkout CRLF/style mismatches; no
  T5-09-specific whitespace error is present, and the Linux exact-SHA CI format job remains authoritative.

## Pending exit gates

T5-09 remains open for exact-SHA GitHub Actions, including the authoritative Linux Prettier gate. No
exact-SHA remote run can exist before an owner-requested commit and push; this local evidence tree remains
intentionally uncommitted and unpushed.