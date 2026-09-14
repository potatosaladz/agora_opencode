# Phase 3 Acceptance Evidence

**Verified:** 2026-09-06 · **Task:** T3-09 complete · **Scope:** FR-101…103, FR-301…312
**Remote evidence:** GitHub Actions run
[`33989090448`](https://github.com/potatosaladz/agora/actions/runs/33989090448) passed all six jobs for exact
exit SHA `7aaf1aabdc74a8cdba283d4524759eb1db6a0d03`.

## User walkthrough

1. Open `#/` and enter bearer token, natural-language problem, pinned agent definition, primary objective,
   optional hard constraint, and bounded resource budget.
2. Submit **Open reasoning session**. UI sends typed, idempotent `POST /api/v1/sessions` request.
3. UI commits structured `PROPOSITION` preserving original plus normalized statement.
4. UI commits hypothesis as typed `CLAIM` with explicit empty supporting/opposing evidence arrays.
5. Result renders committed `DRAFT` binding and prominent `UNSUPPORTED / NO EVIDENCE` state.

Automated walkthrough and WCAG A/AA scan:
`frontend/src/features/reasoning/reasoning-page.test.tsx`.

## Verification layers

| Layer | Evidence |
| --- | --- |
| Unit | complete session binding, all 14 artifact kinds, epistemic invariants, revision/withdrawal behavior |
| Property | 49 revision versions preserve logical identity; all 6 uncertainty types accept all 4 representations |
| Contract | generated OpenAPI types drive UI requests; authored schema and generated client have zero drift |
| UI | full FR-101/FR-305 walkthrough; accessibility scan; unsupported state visible without inference |
| Live PostgreSQL | clean migration, forced RLS, tenant-safe FKs, atomic commit, gapless concurrent ledger, tamper detection, immutable/no-delete artifacts |

Per-requirement code and test node IDs live in
[`../project/TRACEABILITY.csv`](../project/TRACEABILITY.csv). `scripts/check_traceability.py` requires
all 15 Phase 3 rows to be `implemented`, phase 3, and populated with resolvable code/test evidence.

## Observed gates

- Backend: Ruff format/lint green; strict mypy green over 126 files; 226 offline tests passed.
- Live stack: disposable `docker compose down --volumes --remove-orphans` followed by
  `docker compose up --build --wait` exited 0. All six long-running services were healthy, both init jobs
  exited 0, `/ready` returned all five components `ok`, the frontend returned HTTP 200, and PostgreSQL's
  `alembic_version` was `20260905_0008` (`head`).
- Integration: 26 tests passed with no skips, including the complete PostgreSQL reasoning-persistence and
  migration suite plus Redis, MinIO, and NATS acceptance.
- Frontend: ESLint and strict TypeScript green; 9 tests passed; production build passed.
- Contracts/docs: OpenAPI valid, generated TypeScript has no drift, 41 trace rows and all 15 Phase 3
  mappings valid, 85 Markdown files link-clean, whitespace check clean.

## Schema-document comparison

[`DATA_MODEL.md §13.1`](DATA_MODEL.md#131-phase-3-schema-drift-manifest) now contains the machine-readable
table, column-order, PostgreSQL-type and nullability contract for all 10 tables introduced by revisions
`20260905_0005` through `20260905_0008`.
`test_phase3_database_schema_matches_documented_manifest` loads that documentation block and compares it
with `information_schema.columns` after a clean migration. The migration lifecycle test separately proves
that exactly those tables, and no undocumented Phase 3 tables, appear above the Phase 2 revision. Both
tests passed in the 26-test live suite.

## Anti-pattern review

All 34 entries in [`ANTI_PATTERNS.md`](ANTI_PATTERNS.md) were reviewed against the Phase 3 diff. “Deferred”
below means the feature does not exist in Phase 3, not that the prohibition was waived.

| Entries | Result | Phase 3 evidence |
| --- | --- | --- |
| AP-1…AP-4 | Pass | no aggregate/averaging field or consensus outcome was added; confidence carries kind, meaning and basis; evidence remains typed and provenanced; unsupported claims are not labelled false |
| AP-5…AP-10 | Pass | agent/LLM-owned `FACT` is rejected; no memory promotion, transcript or chain-of-thought field exists; no retrieval result is interpreted as refutation; proposition modality and constraint class remain explicit; formalization may remain unavailable rather than being invented |
| AP-11…AP-18 | Pass | application services compose ports while caller transactions own commit; import boundaries pass; Redis is not durable truth; lifecycle, graph and ledger writes are atomic; no workflow/gateway or prompt behavior was added; all schema changes use Alembic; the locked per-session head serializes ledger append |
| AP-19…AP-24 | Pass | all 15 Phase 3 requirements have implemented trace rows; this document distinguishes implemented evidence from later-phase design; no phase skipping, benchmark, experiment or metric-targeting behavior was added |
| AP-25…AP-29 | Pass / deferred | dissent, solver-result trends and explanation views remain later-phase work; Phase 3 does not claim them. The implemented unsupported state uses the visible text `UNSUPPORTED / NO EVIDENCE`, not color alone |
| AP-30…AP-34 | Deferred | Phase 3 adds no experiment execution or reporting path, so no metric shopping, version pooling, failed-session filtering, narrative-first report or hidden null result is introduced |

Evidence captured during the local gate is under `backend/.artifacts/t3-09/` (ignored local build evidence,
not a source of truth). T3-09 does not claim Phase 4 execution, automatic LLM decomposition, Phase 10 graph
traversal, or any later-phase behavior.