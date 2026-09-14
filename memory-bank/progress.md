# Progress

**Overall completion:** Phases 0–13 complete; Phase 5 remote
evidence remains separate. Phase-0 architecture baseline: **approved by the project owner (D-13)**.

---

## Phase status board

| Phase | Title | Status | Exit evidence |
| --- | --- | --- | --- |
| 0 | Requirements & architecture | **Complete and approved** | D-13 records project-owner approval on 2026-09-04 |
| 1 | Project foundation | **Complete** | T1-00…15 complete; GitHub Actions run `33923240340` green; healthy full stack, 70 offline + 6 integration backend tests, and 6 frontend tests green |
| 2 | LLM & agent registry | **Complete** | one definition ran through two OpenAI-compatible endpoints and the mock; 95 offline and 7 live integration tests green; migration/repository/RLS/immutability proof green; run `33952091288` green |
| 3 | Structured reasoning model | **Complete** | local schema/anti-pattern/inherited/clean-stack gates green; exact-SHA CI run `33989090448` passed all six jobs |
| 4 | Durable orchestration | **Complete** | exact-SHA `d9efa51cbb2fee52b6d32bf47e3346b31d7d392b`; GitHub Actions run `34031523362` passed all six jobs |
| 5 | RAG & memory | **In progress** | all local T5-09 gates green: 370 offline and 40 Compose-backed tests; exact-SHA CI pending |
| 6 | Domain expert reasoning | **Complete** | final exact SHA `6d671acffe7abd3e5b587042457f300e0c442adc`; GitHub Actions run `34148649503` passed all six jobs, including 479 offline and 42 live tests |
| 7 | Critic & revision loop | **Complete** | T7-00…08 complete; 82 focused, 677 offline and 52 live tests green; exact SHA `25914b48e1c5140279720d1a4dfb66483cf744a3` passed all six jobs in run `34667037521` |
| 8 | Simulation | **Complete** | T8-00…05 merged to master `77dbf01`: domain types, ports, orchestrator, sensitivity, migration, 36 contract tests (76 total) |
| 9 | Baseline consensus engine | **Complete** | T9-01…06 merged to master `b95f24b`: `weighted`/`evidence_weighted`/`constraint_aware` strategies, shared feasibility gate, `StrategyRegistry`, `ConsensusOrchestrator`, 13 unit tests with worked examples verbatim from formalism docs; 620 total tests, Ruff/mypy clean |
| 10 | Reasoning graph & traceability | Not started | — |
| 11 | Neuro-symbolic | **Complete** | T11-01…04 complete: immutable formalisation lifecycle, bounded Z3, exact-revision evidence, and conservative `UNKNOWN → DEFER` consensus policy |
| 12 | MARL environment | **Complete** | T12-01…05: exact trajectory domain, reward/credit accounting, canonical export, hermetic replay, in-memory/PostgreSQL stores and migration 0024 |
| 13 | Trustworthiness | **Complete** | T13-01 catalogue; T13-02 audit records + eight queries; T13-03 replay modes; T13-04 canonical durable pinned run manifests |
| 14 | Full UI | In progress | T14-01…05 complete; T14-06 open; scripted usability fixture remains unpassed |
| 15 | MCP | Not started | — |
| 16 | Research extensions | Not started | — |
| 17 | Swarm & hardening | Not started | — |

---

## Detailed log

### 2026-09-14 — Phase 14 T14-05 Replay Controls

- Added authenticated exact finalized-manifest reads and STRICT/TOLERANT/LIVE replay requests delegating to
  the existing persisted replay source and session replay service, with public IDs, role policy, hidden
  tenant scope and explicit LIVE confirmation.
- Added code-split accessible responsive controls preserving STRICT verification/no-provider semantics,
  TOLERANT MATCHED/DIFFERENT ordered diffs, and LIVE fresh-lineage or typed unavailable states.
- Added no migration or persistence; Alembic remains `20260914_0026`. Focused API/service/PostgreSQL and
  frontend tests plus contract, static, docs and Compose gates pass. T14-06 remains open.

### 2026-09-14 — Phase 14 T14-04 Explanation Panel

- Added an authenticated unfiltered read composing the latest persisted consensus explanation,
  recommendations, alternatives, evidence/provenance, assumptions, dissent, critiques, risks, symbolic
  feasibility, conditions and authored counterfactuals without recomputation or generated prose.
- Added code-split executive, expert, formal and exact machine-readable views with explicit empty reasons,
  deterministic weakest-evidence facts, cross-view links, keyboard navigation and responsive accessibility.
- Added no migration or persistence; Alembic remains `20260914_0026`. Focused, live PostgreSQL, full local,
  contract/docs and isolated Compose gates pass.

### 2026-09-14 — Phase 14 T14-03 Assumption Register

- Added authenticated, deterministic session reads for all assumption, constraint and uncertainty revisions,
  retaining lifecycle, origin, evidence relations, graph dependencies, recommendations, critiques,
  provenance and exact symbolic facts.
- Added a code-split accessible Assumption Register with explicit concept/status distinctions, safe
  `UNKNOWN → DEFER`, missing-analysis states, Graph/provenance/Dissent navigation and responsive layouts.
- Added no migration or persistence; Alembic remains `20260914_0026`. Focused, live PostgreSQL, full local,
  contract/docs and isolated Compose gates pass.

### 2026-09-14 — Phase 14 T14-02 Dissent View

- Added authenticated, unfiltered session dissent reads over persisted consensus explanations, Critique
  handoff, artifacts, provenance and graph nodes. Public responses distinguish selected context, supporting,
  opposing and qualifying evidence, minority positions and open/unresolved/disputed critiques.
- Added a code-split accessible Dissent View with keyboard selection, explicit lifecycle/missing-data/empty
  states, Graph View and provenance navigation, and responsive desktop/mobile layouts. No scores are
  calculated or presented.
- Added no migration or persistence; Alembic remains `20260914_0026`. Focused backend/frontend tests, live
  HTTP/PostgreSQL acceptance, inherited local gates and isolated Compose deployment pass.

### 2026-09-14 — Phase 14 T14-01 Graph View

- Added authenticated `POST /api/v1/graph/subgraph` as a public-ID boundary over the existing
  `ReasoningTransaction.graph.subgraph()` traversal with fail-closed root/session scope and exact cursor
  binding. No repository, traversal implementation, persistence or migration was added.
- Added a code-split responsive Graph View with TanStack Query server state, labelled visual edge semantics,
  keyboard node selection, textual equivalence and explicit loading/error/empty/pagination/truncation states.
- Validation: 50 focused backend graph/API/provenance tests, one live PostgreSQL HTTP fixture, 807 offline
  backend tests, 30 frontend tests, backend/frontend static and build gates, OpenAPI/client drift,
  traceability and links pass. Isolated Compose is healthy at Alembic `20260914_0026`; `/ready` and frontend
  return 200.

### 2026-09-14 — Phase 14 acceptance contract

- Froze T14-01 Graph View, T14-02 Dissent View, T14-03 Assumption Register, T14-04 Explanation Panel,
  T14-05 Replay Controls and T14-06 Audit Search in the existing deliverable order.
- Preserved earlier-phase requirement and persistence ownership; Phase 14 owns authenticated exposure and
  accessible UI presentation only. No runtime code, API route, frontend component or migration changed.
- Defined the scripted usability fixture for identifying minority position and weakest evidence; it remains
  unpassed until the implementation tasks complete.

### 2026-09-14 — Phase 13 T13-04 run manifests with pinning

- Added typed canonical version-1 run manifests covering only supported authoritative pins: code/images,
  schema, configuration/protocol/budget/consensus, agents/prompts/inference, retrieval/index, metrics,
  symbolic, simulation, MARL, content and scoped randomness.
- Added `RunManifestService` creation/finalization and `PersistedReplaySource`; canonical JSON is stored
  under its SHA-256 object key and T13-03 resolves only exact finalized manifest id/version/hash values.
- Migration `20260914_0026` adds one forced-RLS manifest per tenant/session, optional source-session
  lineage, tenant-safe FKs and a lifecycle trigger allowing only one `CREATED → FINALIZED` transition.
- No API, experiment tables or metric-value tables were added.
- Validation: 16 focused tests, 792 non-integration tests, 57 PostgreSQL integration tests with 8
  unrelated service-gated skips, Ruff/format, strict mypy over 314 files, compileall, one Alembic head
  `20260914_0026` with no drift, offline SQL, traceability, links and whitespace. The rebuilt Compose
  stack reached healthy, migration exited 0 at `0026`, `/ready` and frontend returned 200, and deployed
  manifest/STRICT replay integration passed.

### 2026-09-14 — Phase 13 T13-03 replay modes

- Added `backend/app/domain/replay.py`: closed `REPLAY_STRICT`, `REPLAY_TOLERANT`, `REPLAY_LIVE`
  enum plus immutable exact manifest/implementation identities, historical steps, requests, executions,
  first mismatches, structured diffs, live launch and result contracts.
- Added `backend/app/application/replay.py`: exact-version `ReplayImplementationRegistry` and
  exhaustive `SessionReplayService`. Every mode validates caller-scoped source/manifest identity,
  verifies the PostgreSQL-authoritative ledger chain and exact event sequence, and can nest the existing
  Phase 12 MARL `verify_bundle()` without altering its semantics.
- STRICT permits recorded reconstruction and deterministic non-external implementations only; missing or
  substituted versions fail closed, external implementations are rejected before invocation, and the first
  output/status mismatch terminates verification. TOLERANT re-executes only explicitly permitted steps and
  emits deterministic implementation/provider/model/configuration/output/status/timing-sensitive diffs;
  it returns MATCHED/DIFFERENT, never VERIFIED. LIVE delegates new execution and rejects any reuse of the
  source session, manifest, event or result identities.
- Added 11 focused tests for mode closure, strict success/integrity/unavailable/mismatch/no-external/no-
  mutation behavior, tolerant structured differences and no false VERIFIED result, LIVE fresh linked
  identities, cross-workspace denial, and recorded-step reconstruction.
- No migration or API was added. T13-04 remains the owner of durable run-manifest creation/finalization and
  database-backed live replay lineage.

### 2026-09-14 — Phase 13 T13-02 audit persistence + the eight audit queries

- Migration `backend/alembic/versions/20260912_0025_audit_tables.py` (down `20260912_0024`, expand,
  single head) adds forced-RLS (`app.workspace_id` policy), caller-append-only `access_log` and
  `audit_anchors`: `BEFORE UPDATE OR DELETE` trigger `reject_audit_mutation` raises sqlstate 27000,
  `REVOKE UPDATE, DELETE` from PUBLIC, composite `(workspace_id, session_id)` FK to `sessions`,
  CHECKs (principal class, action=READ, result enum, sha256 hash shapes, day head_seq). Upgrade and
  downgrade both pass live; `alembic check` reports no drift.
- `backend/app/db/models/audit.py` + `models/__init__.py` export the two rows; `app/domain/audit.py`
  provides `AccessLogEntry`, `LedgerVerificationSummary`, `AuditAppendReport`, `ChainIntegrityReport`,
  `AuditAnchor`/`AuditAnchorVerification` and the `AuditAnchorRepository` protocol, with `publish`
  over the shared pure `_anchor_facts(actor, day, head_seq, head_hash, prev_head_hash, anchored_at,
  session_id)` so reproduction and detection use the same hash.
- `app/db/audit.py`: `SqlAlchemyAccessLogRepository` (cursor pagination), `SqlAlchemyAuditAnchorRepository`
  (publish/latest/`chain_integrity` recomputing day-heads from a bounded `ledger.read` +
  `_last_event_at_or_before`), `SqlAlchemySessionParticipantReader`; `app/db/consensus.py` gains
  `ConsensusResultStore.get_round_result`.
- `app/application/audit.py` answers Q1–Q8 as typed services: `AuditQueryService`
  (artifacts_rationale/claimed_objectives/agent_round_context settlement/dissent/termination/strategy
  provenance), `AccessAuditService` (Q7 strictly before `recommendations.created_at`, cursor
  pagination, `why_incomplete`), `ChainVerificationService` (chain_integrity + ledger verify). No HTTP
  (Phase 14). `app/composition/container.py` wires the new adapters.
- Tests: 21 unit (`tests/unit/test_audit_queries.py`) and 7 live PostgreSQL acceptance
  (`tests/integration/test_audit_persistence.py`) covering append-only (27000), forced-RLS cross-tenant
  42501, unknown-session FK 23503, Q7 complete-timeline + before-acceptance bound, same-day anchor
  conflict, two-day chain with genesis prev-hash, and tamper detection (disabled trigger). Census test
  `test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` extended with `_PHASE_13_TABLES`.
- Docs: AUDITABILITY.md v1.4 (storage header, implemented access-log schema paragraph, Q2/Q3/Q5 paths
  reflect real durable facts; nightly job + WORM anchor noted as follow-up) and DATA_MODEL.md §11.1
  (implemented DDL, `audit_records` supersede note, ER relationships). Traceability FR-807/NFR-006 →
  implemented (`local-phase13-2026-09-14`), 104 generated rows no drift.
- Validation: unit `698 passed`; PostgreSQL integration green after the census fix (`55 passed, 8
  skipped` infra-gated); strict mypy 305 files; ruff
  check clean (ruff format applied to the four new/touched source files; historical migration 0021 left
  as-is as a pre-existing format waiver); `alembic heads` = single `20260912_0025`; links green 90
  files; `git diff --check` clean; Compose config valid; backend image builds. `check_contracts.py` still
  reports the pre-existing `POST /api/v1/formalizations` route drift (out of Phase 13 scope).

### 2026-09-14 — Phase 13 T13-01 metric catalogue + Compose isolation

- Added `backend/app/ports/metrics.py`: `_Frozen` value objects, `MetricDimension`/`MetricDirection`/
  `MetricSubjectKind`/`MetricRangeKind`/`MetricRange`/`MetricInputSpec`, the six-admission-field
  `MetricDefinition` (profile/dimension, label, direction, range kind/bounds, unit, ID) with
  retirement-with-successor rules, `MetricValueStatus`/`MetricValue` (M-2/M-4 metadata, no
  `NOT_APPLICABLE → 0`), and the `@runtime_checkable` `MetricPlugin` port.
- Added `backend/app/domain/metrics.py`: immutable `MetricCatalogue` rejecting duplicates/empties,
  deterministic ordering, and exact `get(metric_id, metric_version)` with no "latest" fallback.
- Added `backend/app/application/metrics.py`: all 43 shipped definitions transcribed from METRICS.md
  (EP-01…06, RR-01…07, DH-01…07, CQ-01…06, RB-01…05, CE-01…05, HO-01…04, CA-01…03).
- Added 13 tests in `backend/tests/unit/test_metric_catalogue.py` (FR-901/FR-902/NFR-019) covering the
  full transcription gate, deterministic order, FR-901 profile/no-composite rule, fail-closed exact
  lookup, details from the Phase 12 reward pins (`ep-02`, `dh-03`, `dh-02`, `cq-03`, `ce-03` at "1").
- Traceability: FR-901 partial, FR-902 implemented (`local-phase13-2026-09-14`), NFR-019 partial;
  METRICS.md §1/§2 annotated; generated TRACEABILITY.csv = 104 rows, no drift.
- Validation: ruff/mypy/compileall clean; 13 focused tests and full non-integration suite
  `755 passed, 56 deselected` (fresh `--basetemp`; see ERRORS.md environment note on the Windows
  pytest-current junction teardown).
- Compose isolation: project `agora_opencode`, env-parameterized loopback host ports (POSTGRES 15432,
  REDIS 16379, MINIO 19000/19001, NATS 14222/18222, TEMPORAL 17233/18080/15433, BACKEND 18000,
  FRONTEND 13000), dedicated volumes/networks, `agora_opencode/`-prefixed images, `scripts/run-integration.ps1`
  TEST_* ports, frontend vite proxy env, `.env.example`/README/DEPLOYMENT updates.
- Integration gate: `docker compose up -d --build --wait` on the isolated stack, `/ready` all six
  components ok, frontend 200, `scripts/run-integration.ps1` green `56 passed` (755 deselected). The
  gate surfaced two pre-existing Phase 12 alembic-chain defects, fixed and recorded as E-21 (ORM
  metadata omitted `ck_marl_episodes_status_shape`) and E-22 (head acceptance kept the Phase 10 literal
  and table census); ORM + acceptance now align to head `20260912_0024` with no new migration.

### 2026-09-10 — Phase 9 consensus engine (T9-01…T9-06)

- Added `weighted`, `evidence_weighted` and `constraint_aware` `ConsensusStrategy` implementations in
  `backend/app/application/consensus.py`, each matching its worked example in
  `docs/consensus-formalism/` verbatim.
- Added a shared feasibility gate (`feasibility_gate`) in `backend/app/domain/consensus.py`, implemented
  once and reused by every strategy so infeasible alternatives can never be ranked (FR-602, FR-603).
- Added `StrategyRegistry`, refusing an unregistered or undocumented strategy (FR-608, S-1) and rejecting
  duplicate name/version pairs.
- Added `ConsensusOrchestrator`, resolving a strategy, evaluating it, and persisting the result plus a
  complete `ConsensusExplanation` with every outcome (FR-605).
- Outcome classification covers all eight classes from FR-604: `FULL_CONSENSUS`, `PARTIAL_CONSENSUS`,
  `CONDITIONAL_CONSENSUS`, `PARETO_SET`, `NO_CONSENSUS`, `DEADLOCK`, `INSUFFICIENT_EVIDENCE`,
  `INFEASIBLE`. A session with no verified evidence returns `INSUFFICIENT_EVIDENCE` rather than a
  ranking; conflicting objectives yield `PARETO_SET` rather than a forced single winner (FR-607).
- Minority and dissenting positions are preserved in every `ConsensusExplanation.minority_report`
  and cannot be suppressed through the API (FR-505, FR-506).
- Added `backend/app/ports/consensus.py`: `ConsensusContext`, `ConsensusResult`, `ConsensusExplanation`
  and all supporting value objects behind the `ConsensusStrategy`/`ConvergenceStrategy` protocols.
- Added 13 new unit tests in `backend/tests/unit/test_consensus.py` covering worked examples for all
  three strategies, registry rejection paths, and orchestrator persistence. Ruff and mypy clean; full
  suite 620 passed, 0 failed, 43 pre-existing unrelated skips.
- Merged `phase9-consensus` to `master` at `b95f24b`.

### 2026-09-09 — Phase 8 simulation & sandbox execution (T8-00…T8-05)

- Added simulation domain types split across layers: port-level `SimulationSpec`, `SimulationResult`,
  4 enums and 10 value objects in `app/ports/simulation.py` using local `_Frozen` base; domain adds
  `RunStatus`, `SimulationRunRecord`, `SimulationRunStore` and re-exports.
- Added `SimulationEngine` and `SandboxExecutionProvider` port protocols with `SandboxRequest`/
  `SandboxResult`/`SimulationCapabilities` value objects.
- Added `SimulationOrchestrator` application service: request → validate → run → rank sensitivity → store;
  handles `TimeoutError` → `TIMEOUT` and generic → `FAILED`.
- Added `compute_sensitivity_ranks()` pure function ranking by descending absolute index.
- Added Alembic migration `20260909_0020` for `simulation_runs` and `simulation_results` tables with
  forced RLS, CHECK constraints, and indexes.
- Added 36 contract tests with `InMemorySimulationRunStore` and `StubSimulationEngine` doubles.
  76 total tests pass (36 simulation + 28 existing contracts + 12 layering).

### 2026-09-07 — T7-07 deterministic Critique/revision round

- Added fixed dedicated-Critic then peer `CRITIQUE` dispatch and commit ordering, followed by sealed
  author-specific `REVISE` dispatch and stable target/responder response commits.
- Preserved complete execution attribution semantics through generic dispatch outcomes, enforced unique response IDs and
  Critique heads, and persisted ordered `TURN_TIMEOUT` abstentions for Critic, peer and REVISE turns.
- Added phase-level precommit validation, unsupported-Claim `EVIDENCE_GAP` coverage, deprecated alias
  rejection, deterministic complete handoff coverage and explicit empty reasons with no omit parameter.
- Verified 49 focused tests, 607 non-integration tests, one disposable-PostgreSQL handoff integration,
  compileall, and clean Ruff/format/strict mypy over 248 app/test files. T7-08 subsequently closed the
  phase with the complete local, Compose and exact-SHA remote matrix recorded above.

### 2026-09-07 — T7-00 contract reconciliation

- Reconciled roadmap aliases against exact FR-501 and implemented `CritiqueType` values.
- Froze Critic-only proposal authority, active all-artifact targets, seven author-bound responses,
  immutable Critique resolution, targeted `SUPERSEDES`/`RESPONDS_TO` revisions, request disposition,
  stable phase ordering and complete internal explanation handoff.
- Reused Phase 3 artifact/graph/ledger and Phase 6 runtime/attribution/budget seams. No runtime code,
  migration, public API or generated client changed.

### 2026-09-07 — T7-01 through T7-04 Critic contracts, runtime and atomic attacks

- Added exact frozen assignments and seven response shapes; aliases, mutation fields, invalid effects,
  wrong-kind/non-open/unassigned/duplicate attacks and request-bearing Critic bundles fail closed.
- Shipped one deterministic cross-cutting Critic with adversarial objectives and literal LF prompt digest.
  The real mock-backed agent activity emits valid Critiques against all 14 artifact kinds.
- Composed authorized reasoning context, durable budget checks and bounded dispatch. Assignment pins must
  match context; timeout remains abstention; only the third consecutive completed empty round records
  `CRITIC_INACTIVE`; invalid peer output leaves no partial inactivity event.
- Coordinator-derived `ATTACKS` relationships and retry-stable edge IDs now flow through the existing
  artifact/graph/ledger transaction with type/severity qualifiers and mandatory assignments. Exact retry is
  idempotent, all 14 target kinds commit, and invalid, hidden, inactive or future targets leave no partial writes.
- Validation: 86 focused T7-01…04 tests and 565 offline tests pass with 42 live tests deselected; Ruff
  format/lint and strict mypy over 238 files, contracts, 58-row traceability, 89 links and whitespace pass.

### 2026-09-07 — T7-05/T7-06 atomic responses and targeted revisions

- Preserved complete provider/model/token/cost/raw-output metadata through activity strategies and bounded
  dispatch. Deterministic strategies normalize to explicit metadata-free, zero-accounting execution results.
- Added strict replacement-only revision proposals plus append-only response request/result contracts. Exact
  request identity includes the full pinned response and attribution; conflicting retries fail closed.
- Added target-owner, visibility, snapshot, warrant, active/current-head and reference validation for every
  disposition. Each response appends a Critique successor; unresolved/disputed outcomes remain explicit.
- `REVISE` appends a schema-valid target successor with the same kind, logical ID and owner. The coordinator
  derives all `SUPERSEDES`, `RESPONDS_TO`, and Critique `ATTACKS` relationships.
- Migration `20260907_0019` adds forced-RLS append-only request/result tables and widens only graph-level
  `RESPONDS_TO` validation to all artifact source kinds. Direct agent creation of `FACT`/`EVIDENCE` remains
  forbidden.
- Validation: 23 response-specific and 589 offline tests pass; Ruff format/lint and strict mypy are clean
  over all 242 app/test files; compile and offline Alembic SQL generation pass with one
  head. Two focused live PostgreSQL tests pass against a disposable pgvector/PostgreSQL 16 database, covering
  the graph matrix, atomic rollback/commit, exact retry, forced RLS and append-only mutation rejection;
  `0019 → 0018 → head` and `alembic check` pass.

### 2026-09-07 — T6-08 mutable membership, durable budgets and 20-agent proof

- Added append-only, forced-RLS effective-round membership history. Replacement is pre-round-1 only;
  injection is next-round only; advisory plus lifecycle-row locks serialize against round start; replay uses
  ledger sequence rather than caller timestamps.
- Context assembly and PostgreSQL retrieval enforce effective membership, including removal of replaced
  definitions. Session and strict per-definition token/USD totals are read from durable accounting before
  and after bounded dispatch; equality records one explicit `BUDGET_EXHAUSTED` failure.
- The four-worker 20-agent fixture commits one claim per agent through the real coordinator committer in
  pinned order and verifies complete attribution in artifact metadata and completion events.
- Validation: 21 focused and 474 offline tests pass with 42 service-backed tests skipped; Ruff format/lint,
  strict mypy over 229 files, offline Alembic SQL, contracts, 54-row traceability, 88 links and whitespace
  pass. Live PostgreSQL persistence and migration-cycle evidence awaits `TEST_DATABASE_URL`.

### 2026-09-07 — T6-07 coordinator orchestrator-proposal policy

- Added frozen, strict `DECOMPOSE`, `ROUTE`, and `ADVANCE_PHASE` recommendations with complete pinned
  identity and no mutation, transition, persistence or generic command field.
- Added deterministic coordinator policy over only `ReasoningLedger`: exact pins, eligible routing and
  immediate fixed phase order are enforced before one retry-stable `POLICY` decision event is appended.
  Accepted proposals remain inert and explicitly record `applied: false`; T6-02 keeps decomposition semantics.
- Validation: 22 focused and 464 offline tests pass with 41 integrations deselected; Ruff format/lint and
  strict mypy pass over 225 files; contracts, 54-row traceability, 88 links and whitespace pass. No database
  schema or live adapter changed; `TEST_DATABASE_URL` remains unavailable.

### 2026-09-07 — T6-06 sealed shared-pool multi-agent dispatch

- Added whole-batch preflight for sealed same-session/round/phase round-one `ASSESS` inputs before any
  worker invocation. Immutable worker inputs retain proposal-only authority and expose no persistence,
  workflow-transition or peer-agent channel.
- Added fixed queue-consuming shared-worker concurrency with indexed result slots, so completion races cannot
  change caller/pinned-agent ordering. Per-turn deadlines return typed `ABSTAIN` outcomes with
  `TURN_TIMEOUT`; cancellation and runtime errors continue to propagate.
- Validation: 7 focused and 442 offline tests pass; the default suite passes 442 with 41 service-dependent
  integrations skipped; Ruff format/lint, strict mypy, contracts, traceability, links and whitespace pass.
  No database schema or live adapter changed; `TEST_DATABASE_URL` remains unavailable.

### 2026-09-06 — T6-05 deterministic policy-expert catalogue and sealed prompts

- Added five active workspace-scoped policy definitions with stable UUIDv5 identities, distinct fiscal,
  macroeconomic, social-policy, infrastructure and risk objectives/stances, and an exact
  `evidence-first@1.0.0` strategy pin.
- Added five non-empty UTF-8 package resources with frozen literal SHA-256 values, content-addressed object
  keys and verified `ObjectStore` staging. Prompt loading and staging fail closed on byte/digest drift.
- Ran every definition through the real sealed agent-turn activity with deterministic schema-valid mock
  output. JSON-native Pydantic validation preserves strict scalar checking while accepting JSON arrays for
  strict tuple fields.
- Validation: 16 focused and 435 offline tests pass; Ruff format/lint and strict mypy pass over 220 files;
  compile, 16-path/15-error-code contracts, 54-row traceability, 88 Markdown links and whitespace pass. A
  clean wheel install loads all five packaged prompts with their exact hashes. No database change was made;
  `TEST_DATABASE_URL` is unavailable.

### 2026-09-06 — T6-04 deterministic proposal validation and atomic coordinator commit

- Added whole-bundle fail-closed proposal validation over every typed payload and confidence reference.
  Fabricated, inactive, future and wrong-kind references fail before identity allocation or writes.
- Added retry-stable UUID identities for artifacts, graph nodes and events, sorted reference locking and a
  PostgreSQL transaction advisory lock per turn. Exact complete retries return prior state; partial or
  conflicting prior state fails closed.
- Reused the caller-owned reasoning transaction to commit accepted artifacts, graph-node projections and
  attribution-rich ledger events in proposal order. Position confidence is mandatory and evidence
  disposition is hash-covered in artifact metadata and ledger payloads.
- Validation: 53 focused unit tests, one adapter contract and 428 offline backend tests pass; Ruff format
  and lint plus strict mypy over 216 files pass. A migration-backed PostgreSQL concurrent-retry,
  atomicity and fabricated-reference test is authored but skipped without local PostgreSQL settings.

### 2026-09-06 — T6-03 authorized reasoning-context assembly

- Added immutable SDK-free snapshots for exact pinned definitions, hydrated artifact envelopes and
  authorized retrieval outcomes; successful zero-match remains distinct from absent or failed retrieval.
- Added fail-closed assembly checks for session/workspace affinity, exact runnable definition/version,
  active typed objectives/constraints, unique active non-future artifacts, sealed round-one assessment,
  and retrieval principal, subjects, trace, namespace, query hash and result provenance.
- Propagated snapshots through the activity boundary into deterministic LLM prompt JSON and revalidated
  the durable definition before provider creation. Validation: 68 focused tests; 416 full backend tests
  passed with 40 service-dependent integrations skipped; Ruff clean over `app tests`; strict mypy over
  213 files; layering, traceability, 88 Markdown links and `git diff --check` green.

### 2026-09-06 — T5-09 local Phase 5 exit candidate

- Added versioned domain-neutral synthetic source/chunk/query labels, exact expected retrieval order,
component versions and metric caveats. Deterministic evaluator reports recall proxy 1.0 and precision at
2 of 0.5 as comparison values, not scientific truth.
- Added migration `20260906_0017` and retrieval intent/failure handling so expected-match zero results and
infrastructure failures append durable `RAG_FAILED`; valid no-match and authorization denial stay distinct.
- Final local validation: 370 offline and 40 live Compose-backed tests; focused migration/baseline tests;
  strict mypy and Ruff over 204 files; frontend lint/typecheck/19 tests/build; generated client, authored
  contracts, 47-row traceability, 87 Markdown links and `git diff --check` green. Windows Prettier retains
  36 pre-existing checkout CRLF/style warnings; authoritative Linux exact-SHA CI remains pending until the
  owner requests commit and push.

### 2026-09-06 — T5-08 explicit memory tiers and validated promotion

- Added strict working, episodic, semantic and procedural `MemoryScope` contracts and a frozen-port-compatible
  `MemoryProvider`. Existing Redis, ledger/session-artifact and agent-configuration authorities remain owners
  of non-semantic tiers; direct semantic writes fail.
- Added migration `20260906_0016` and matching ORM rows for immutable semantic entries, promotions,
  evidence sets and lifecycle facts. PostgreSQL revalidates active humans, source/evidence identities,
  historical/global namespace, caveats, review/supersession chains; deferred constraints reject
  unpromoted/no-evidence rows. Forced RLS and append-only triggers preserve stale/archive history.
- Validation: 363 offline tests and one focused live PostgreSQL test pass; live proof includes direct
  SQL bypass rejection, forced RLS, append-only mutation rejection, as-of stale resolution, explicit
  stale/archive facts, `alembic check` and `0016 → 0015 → head`. Ruff/format, strict mypy over 201 files,
  compile, layering, contracts, links, traceability and whitespace pass.

### 2026-09-06 — T5-07 resolvable citations, manual evidence and source retraction

- Retrieval candidates preserve exact namespace/source/document/chunk IDs, citation, ordered character
  span, source/chunk digests, source/document/retrieval timestamps and trust through reranking.
- Manual attachment validates the active human member, human-owned evidence, target claim, stored source
  reference and complete ready knowledge chain in PostgreSQL before appending a text-free dependency.
- Migration `20260906_0015` adds append-only forced-RLS citation/retraction facts. Reason-required retraction
  is irreversible, excludes future retrieval and preserves old resolution plus Phase 10 dependency IDs.
- Validation: 359 offline tests; 4 focused live PostgreSQL tests in 8.14s; Ruff/format, strict mypy over 196
  files, compile/layering/contracts/links/traceability/whitespace, drift and `0015 → 0014 → head` green.

### 2026-09-06 — T5-06 namespace grants and retrieval audit

- Extended requests with stable attempt/trace IDs and explicit human/agent identity. PostgreSQL validates
  every supplied workspace, user, agent-definition and session subject before grant resolution. One
  materialized relation enforces all six tier contexts before scoring; agent session access additionally
  requires `session_agents`, and forged extra subjects deny the requested scope.
- Added immutable `RetrievalAttempt`/`RetrievalAudit` contracts and PostgreSQL persistence. Migration
  `20260906_0014` adds append-only forced-RLS `retrieval_attempts` with hashes, identifiers, counts, outcome,
  versions and degradation but no query/chunk text. Denied paths audit before raising; allowed paths audit
  before return; audit-write failure fails retrieval closed.
- Validation: 354 offline tests passed with 37 integrations deselected; 3 focused live PostgreSQL tests
  passed in 7.89s. Ruff clean; strict mypy over 190 files; Alembic drift and `0014 → 0013 → head` green.
  Compile, format, 86 Markdown links, traceability, contracts and whitespace checks are green.

### 2026-09-06 — T5-05 hybrid retrieval and reranking

- Added strict retrieval request/result/candidate values, explicit subject and namespace scope, query and
  index identities, full provenance, arm census, per-arm/fused/rerank scores and degradation state.
- Added migration `20260906_0013` with an immutable generated `tsvector` and GIN index. PostgreSQL lexical
  and UUID-backed vector arms resolve active read grants and chunk ACLs inside materialized pre-score
  relations. Deterministic RRF uses `k0 = 60`; reranker output cannot mutate provenance or invent/drop hits.
- Vector outage or index mismatch retains lexical hits with explicit degradation. Reranker port failure
  retains fused order; permission and other permanent failures remain failures, never silent no-match.
- Validation: 352 offline tests (36 integration tests deselected) pass in 10.15s; 2 focused live PostgreSQL
  tests pass in 7.20s. Ruff is clean and strict mypy covers 187 files. Alembic reports no drift, downgrade/
  re-upgrade reaches `20260906_0013`, and GIN/grant/ACL/deterministic-repeat behavior is live-proven.

### 2026-09-06 — T5-04 UUID-backed pgvector index integration

- Extended derived `vector_items` through linear migration `20260906_0012` with a complete nullable
  UUID-backed identity, composite provenance-chain foreign keys, embedding model/version and scope index.
- Added typed `KnowledgeVectorIndex` and PostgreSQL adapter. Writes resolve authoritative provenance/hash
  and serialize namespace model pinning with sorted advisory locks; reads reject embedding identity
  mismatch, stale hashes and non-ready sources/documents, with deterministic chunk-UUID tie ordering.
  Legacy `VectorStore` reads/deletes exclude typed rows and colliding writes fail closed.
- Validation: 345 offline tests (35 integration tests deselected) and 6 authoritative live PostgreSQL tests
  passed in 15.03s; migration upgrade/downgrade/re-upgrade, forced RLS, cross-tenant rejection, cosine
  IVFFlat index, persistence, pgvector-store coverage, stale-data rejection and `alembic check` are green.
  Disposable PostgreSQL cleanup exited 0. Ruff, format, strict mypy over 182 files, compile, layering,
  contracts, links and traceability pass. Frontend lint, typecheck, production build, 19 tests and generated
  OpenAPI contract verification pass; generated `types.ts` has no diff.

### 2026-09-06 — T5-03 durable ingestion activity and object lifecycle

- Added strict reference-only source-ingestion activity input/result contracts, bounded Temporal retry and
  heartbeat policy, content-addressed object read-back verification and deterministic provenance commit.
- Added migration `20260906_0011`, matching ORM metadata and a transaction-scoped facade. Forced-RLS
  operation checkpoints preserve immutable retry identity, attempt counts, independent acquire/parse/embed/
  index states, parser warnings and stage-specific redacted permanent/transient failures.
- Exact retries return original source/document/chunk IDs; conflicting retries fail; unsupported media is
  retained by digest but fails explicitly; parsed text remains lexical-ready while embedding/index lag is
  durable. Validation: 342 offline tests, 53 focused tests and 2 focused live PostgreSQL tests passed;
  clean upgrade, downgrade/re-upgrade, RLS and `alembic check` are green; Ruff/format over 194 files, strict
  mypy over 181 files, lock, links, contracts, traceability and compile gates pass.

### 2026-09-06 — T5-02 tenant-safe knowledge persistence

- Added strict immutable namespace, grant, source, document and chunk values plus a typed repository
  protocol and transaction-scoped SQLAlchemy adapter with full provenance-chain round trips.
- Added linear migration `20260906_0010` and matching ORM rows. Composite workspace foreign keys, forced
  RLS, typed grant-subject checks, immutable identity triggers and physical-delete rejection prevent
  cross-tenant or unresolvable provenance. Lifecycle and ACL fields remain explicitly mutable.
- Validation: 335 non-integration tests, 39 focused ingestion/knowledge/layering tests, and 2 focused live
  PostgreSQL migration tests passed. Clean upgrade, downgrade/re-upgrade and `alembic check` are green;
  Ruff/format over 186 files, strict mypy over 175 files, lock, links, contracts and traceability pass.

### 2026-09-06 — T5-01 deterministic document ingestion

- Added strict immutable normalized document, structure locator and chunk contracts with pinned parser
  and `agora-whitespace-v1` chunker versions, exact character spans and canonical SHA-256 identities.
- Added PDF, DOCX, TXT, Markdown, CSV, XLSX, JSON and HTML parsing adapters. Table rows stay whole and
  repeat headers; malformed, empty and invalid-UTF-8 input fails closed through `PermanentPortError`.
- Added 24 focused tests using deterministic in-memory fixtures. Validation: 332 non-integration tests
  passed with 32 integrations deselected; Ruff/format and strict mypy over 170 files, 12 layering tests,
  lock, links, contracts and traceability gates pass.

### 2026-09-06 — T5-00 retrieval and memory contract freeze

- Reconciled conflicting memory port signatures, namespace semantics, derived vector-index ownership,
  ingestion/chunk identity, API ownership and retrieval baseline scope.
- Added T5-01…09 acceptance criteria. Chose versioned synthetic fixtures for mechanics while leaving Q-1
  experiment domains to Phase 16; fixed chunk defaults at deterministic 800/150; required explicit grants
  before scoring and PostgreSQL-backed provenance authority.

### 2026-09-06 — T4-04 durable session controls

- Added authenticated, idempotent pause, resume, cancel, deprecated terminate compatibility and typed human
  directive API operations backed by strict Temporal signal envelopes.
- Added deterministic workflow-side control serialization and command deduplication. Only workflow-called
  activities commit PostgreSQL lifecycle changes and reasoning-ledger events atomically.
- Validation: 30 focused live integration tests passed with 287 deselected; disposable PostgreSQL cleanup
  passed. Commit `714f08b7c349a6e6b4d5b11b06299682af3ac76f` is pushed to `origin/master`; GitHub Actions run
  [`34011486812`](https://github.com/potatosaladz/agora/actions/runs/34011486812) passed all six jobs.

### 2026-09-06 — T4-03 typed agent turns and round-one start

- Added strict versioned `turn_request`, `proposal_bundle`, artifact-proposal and activity-result contracts.
  Round-one assessment is sealed, artifact payloads use the canonical strict validators, and model output
  cannot emit commit/round-advance envelopes or classify model proposals directly as `FACT`/`EVIDENCE`.
- Agent turns load exact UTF-8 prompt bytes from `ObjectStore`, verify the pinned SHA-256 before any provider
  call, resolve immutable definition/configuration state in tenant transactions, persist normalized usage,
  and close each turn-scoped provider on success or failure.
- Registered `run_agent_turn` beside bootstrap transitions in the production Temporal worker. The bootstrap
  now atomically persists `SESSION_INITIALIZED` and round-one `ROUND_STARTED`, reaching authoritative
  PostgreSQL state `RUNNING`/round 1 before its durable wait.
- Validation: 274 offline backend tests, Ruff, strict mypy over 153 files, 22 focused agent-activity tests,
  and focused live PostgreSQL plus real Temporal worker proofs passed. GitHub Actions run
  [`34005422198`](https://github.com/potatosaladz/agora/actions/runs/34005422198) passed all six jobs for exact
  implementation SHA `8cc835f4029aca5964c388513aeaba1fc02af4d3`. RAG, simulation and symbolic ports do
  not exist yet; when introduced in their planned phases they remain constrained to this activity boundary.

### 2026-09-06 — T4-02 deterministic session bootstrap

- Added the complete validated lifecycle graph and migration `20260905_0009`, which creates the
  authoritative forced-RLS `session_lifecycles` projection and backfills existing draft sessions.
- Added row-locked transactional lifecycle changes with atomic reasoning-ledger appends. Exact retries
  revalidate the original event identity without duplicating either the event or projection change.
- Added the deterministic `SessionBootstrapWorkflow`, PostgreSQL transition activity and production worker
  registration. API-generated transition IDs are immutable workflow input; bootstrap commits
  `SESSION_INITIALIZED` before entering the T4-03 round-one transition.
- Added idempotent `POST /api/v1/sessions/{id}/start`, including stable workflow/run reattachment after API
  rollback, lifecycle-backed API responses, authored OpenAPI, generated TypeScript and frontend client.
- Validation: 252 offline backend tests, Ruff, strict mypy over 149 files, frontend contract/lint/typecheck/
  10 tests/build, schema-autogeneration drift check, and focused live PostgreSQL and Temporal tests passed.
  The cumulative T4-03 exact-SHA CI run `34005422198` now covers this implementation.

### 2026-09-06 — T4-01 workflow-engine boundaries and Temporal adapter

- Replaced the speculative `Any`-based workflow contract with strict versioned JSON commands,
  idempotent start results, diagnostic execution descriptions and lifecycle health/close. Kept worker
  lifecycle separate; concrete workflow/activity registration is constructor-time adapter composition.
- Added deterministic in-memory client/worker adapters and Temporal SDK 1.32.0 adapters. Temporal start
  pins `REJECT_DUPLICATE` plus `FAIL`; duplicate starts return the original run id with `started=false`.
- Resolved API/state authority: draft creation remains `201`; T4-02 owns separate start `202`; PostgreSQL
  and the ledger remain authoritative while Temporal visibility state is diagnostic.
- Added Temporal Server 1.29.1, PostgreSQL 16 and UI 2.34.0 to Compose and CI. Validation: 240 offline and
  28 live tests passed; real Temporal start/duplicate/describe and worker poll/complete passed; `/ready`
  returned six `ok` components; Ruff, strict mypy over 137 files, links, contracts, trace and Compose config
  are green.

### 2026-09-06 — T3-09 Phase 3 exit

- Added an executable schema manifest for all 10 Phase 3 tables and live PostgreSQL comparison of ordered
  columns, types and nullability; the migration lifecycle also proves the exact Phase 3 table delta.
- Reviewed AP-1…AP-34 against the Phase 3 diff with no violation and explicit deferral for unimplemented
  workflow, trustworthiness UI and research/reporting behavior.
- Validation: 226 offline and 26 live tests passed without skips; Ruff, strict mypy, frontend format/lint/
  typecheck/9 tests/build, contract/client drift, links, traceability and whitespace are green. A clean
  volume-free Compose rebuild reached healthy, `/ready` returned five `ok` components, UI returned 200 and
  Alembic was at `20260905_0008`. GitHub Actions run `33989090448` passed all six jobs for exact local-exit
  SHA `7aaf1aabdc74a8cdba283d4524759eb1db6a0d03`, closing T3-09 and Phase 3.

### 2026-09-05 — T3-08 Phase 3 acceptance and requirement traceability

- Added accessible browser walkthrough from a complete session manifest to persisted proposition and visibly
  unsupported hypothesis, using generated API types and authenticated idempotent client operations.
- Corrected stale Phase 0 matrix meanings and mapped FR-101…103 plus FR-301…312 to concrete design, code,
  unit/property/UI/contract/live PostgreSQL evidence. Checker enforces complete implemented Phase 3 rows.
- Validation: 226 offline tests passed; 25 live integrations passed with no skips; Ruff, strict mypy over
  126 files, frontend lint/typecheck/9 tests/build, OpenAPI/client drift, links, trace and whitespace green.

### 2026-09-05 — T3-07 tenant-scoped Phase 3 HTTP API and contracts

- Added RBAC-protected draft-session create/read and artifact create/read/revise/withdraw routes over the
  existing caller-owned transaction, graph projection and reasoning ledger services.
- Added durable workspace-scoped idempotency with advisory-lock serialization, exact replay, changed-request
  conflict detection, `If-Match` version checks, public typed IDs, explicit unsupported-claim output and
  strict JSON-to-domain decoding without weakening domain construction.
- Added migration `20260905_0008`, authored OpenAPI paths/schemas, regenerated TypeScript API types, unit
  contract coverage and an end-to-end HTTP-to-PostgreSQL atomicity/isolation acceptance.
- Validation: 210 offline tests and 22 configured PostgreSQL integration tests pass; Ruff format/lint, strict
  mypy over 123 files, compileall, layering, offline migration generation, OpenAPI/client drift, frontend
  lint/typecheck/6 tests/build, contracts, links, traceability and diff checks are green.

### 2026-09-05 — T3-06 atomic artifact lifecycle writes

- Added the typed `ReasoningArtifactStore` PostgreSQL adapter and an application-layer
  `ArtifactCommitService` that composes artifact, graph and ledger ports without committing.
- Initial commit writes a typed artifact, graph node and ID-only ledger event. Revision locks and validates
  the active predecessor, inserts a new revision/node, supersedes the predecessor, adds a `SUPERSEDES` edge
  and records the event. Declared parent relationships project to graph edges; withdrawal changes lifecycle
  only and appends its reason plus warrant artifact ids.
- Proved conflict rejection and, on PostgreSQL 16, successful commit/revise/withdraw plus rollback of all
  three writes and unconsumed sequence when a deferred constraint fails at transaction commit.
- Validation: 200 offline tests and 16 PostgreSQL reasoning-persistence tests pass; Ruff format/lint, strict
  mypy over 115 files, layering, offline migration generation, Alembic drift, links, traceability seed and
  diff checks are green.

### 2026-09-05 — T3-05 append-only hash-chained reasoning ledger

- Added immutable append/persisted-event/verification values, exact canonical payload/event hashing and a
  caller-transaction-scoped SQLAlchemy append/read/verify adapter.
- Added migration `20260905_0007` with automatic per-session heads, locked gapless sequence allocation,
  tenant-safe foreign keys, forced RLS, append-only triggers and least-privilege mutation revocation.
- Proved deterministic hashes, matching/conflicting retries, concurrent ordering, rollback without gaps,
  ordered reads, clean verification, deliberate tamper detection, RLS and migration backfill.
- Validation: 192 offline tests and 15 PostgreSQL reasoning-persistence tests pass; Ruff format/lint, strict
  mypy over 111 files, offline migration generation and Alembic drift are green.

### 2026-09-05 — T3-04 tenant-safe reasoning-graph persistence

- Added the `ReasoningGraphStore` domain port, strict node/edge values, SQLAlchemy graph rows and a
  caller-transaction-scoped PostgreSQL adapter that flushes without taking commit ownership.
- Added linear migration `20260905_0006` with tenant/session-safe foreign keys, uniqueness and no-self-loop
  constraints, normative traversal indexes and forced RLS on graph nodes and edges.
- Enforced deferred artifact-kind resolution, the complete closed edge-endpoint policy and protection
  against node updates that would invalidate incident edges. Exhaustive coverage checks all
  14×14×16 kind/edge combinations.
- Proved artifact-plus-projection commit/rollback, valid and invalid edges, node updates, RLS,
  downgrade/re-upgrade and Alembic drift on PostgreSQL 16. Validation: 182 offline tests and 11 targeted
  PostgreSQL tests pass; Ruff format/lint, strict mypy over 107 files and offline migration generation are
  green.

### 2026-09-05 — T3-03 tenant-safe relational persistence

- Added linear migration `20260905_0005` and matching SQLAlchemy metadata for exactly five frozen Phase 3
  tables: draft sessions, pinned session agents, unified immutable reasoning artifacts and typed
  objective/constraint bindings.
- Enforced composite tenant/session foreign keys, closed JSONB payload/envelope checks, revision and
  same-session reference integrity, complete deferred session binding, artifact content immutability,
  physical-delete prevention, indexes and forced RLS on every new tenant table.
- Live PostgreSQL testing exposed a missing no-op `ELSE` in the deferred artifact-reference trigger for
  valid kinds without payload references; fixed it and added regression coverage.
- Proved clean upgrade, exact five-table delta from `20260905_0004`, downgrade/re-upgrade, Alembic drift,
  decimal/timestamp validation, isolation and all integrity triggers on PostgreSQL 16. Validation: 173
  offline tests and 9 PostgreSQL migration/persistence tests pass; Ruff format/lint, strict mypy over 103
  files, compileall and offline migration generation are green.

### 2026-09-05 — T3-02 session binding and proposition normalization

- Added a strict frozen `DRAFT` session aggregate that binds problem text, pinned agent-definition row
  IDs plus logical/version metadata, typed objective/constraint references and resource budget.
- Enforced non-empty agent/objective sets, unique IDs and logical agents, tenant/session affinity,
  objective/constraint type separation, round zero, database-compatible budget limits and UTC timestamps.
- Closed proposition normalization status to `PROPOSED | VALIDATED | AMBIGUOUS`, added deterministic
  version-aware normalization identity and rejected `AMBIGUOUS` propositions at the consensus-input gate.
- Added focused positive/negative tests. Validation: 78 focused and 173 full offline tests pass; 7 live
  integration tests deselected; Ruff, format, mypy over 101 files, compileall, layering, contracts, links,
  traceability seed and diff checks pass.

### 2026-09-05 — T3-01 immutable reasoning artifacts

- Added strict frozen Pydantic models and enums for the common artifact envelope and all 14 FR-301
  kinds, including discriminated artifact and uncertainty unions.
- Enforced revision, ownership, provenance, source, evidence verification/trust, fact-confidence,
  position-confidence, decimal, timestamp, formal AST and deep JSON immutability invariants.
- Added RFC 8785-compatible canonical JSON, exact normative content-hash preimages, deterministic
  SHA-256 identity, JSON/Python validation helpers and complete public exports.
- Added 46 focused tests covering every kind, invalid combinations, canonicalization, hashes, schema
  discriminators and lifecycle-independent content identity.

### 2026-09-04 — Phase 0 execution

**Objective:** produce the complete architecture/documentation baseline without writing
application code.

**Done**

1. Inspected the shared workspace: not a Git repository; target project folder did not
   exist. Confirmed destination with the user.
2. Created `collective-reasoning-platform/` with `memory-bank/`, `project/`, `docs/adr/`,
   `docs/consensus-formalism/`, `.cline/`; initialized Git.
3. Wrote root documents: `README.md`, `CHANGELOG.md`, `.gitignore`.
4. Wrote memory bank: `projectbrief.md`, `architecture.md`, `techContext.md`,
   `activeContext.md`, `progress.md`, `tasks.md`, `decisions.md`, `errors.md`,
   `api-contracts.md`.
5. Wrote `docs/ARCHITECTURE.md` containing all eight required Mermaid diagrams plus the
   service boundary table and state-machine definition.
6. Wrote the domain specifications: `REQUIREMENTS.md`, `DATA_MODEL.md`, `AGENT_MODEL.md`,
   `STRUCTURED_REASONING.md`, `REASONING_GRAPH.md`, `CONSENSUS_MODEL.md`, `MARL_MODEL.md`,
   `NEURO_SYMBOLIC.md`, `EPISTEMIC_MODEL.md`, `RAG_ARCHITECTURE.md`,
   `MEMORY_ARCHITECTURE.md`, `SIMULATION_ARCHITECTURE.md`, `METRICS.md`,
   `AGENT_PROTOCOLS.md`.
7. Wrote `docs/PORTS.md` defining all nineteen extension-point contracts with signatures,
   semantics, failure modes and idempotency expectations — design only, no adapters.
8. Wrote `docs/API.md` and `docs/API_CONTRACTS.md` (versioned payload contracts).
9. Wrote `docs/MVP_BOUNDARY.md` classifying every requirement as
   `MVP` / `Core Post-MVP` / `Research Extension` / `Future`.
10. Wrote ADR-001 … ADR-020 covering every fixed architectural decision.
11. Wrote security (`SECURITY.md`, `THREAT_MODEL.md`, `MCP_SECURITY.md`), trustworthiness
    (`AUDITABILITY.md`, `EXPLAINABILITY.md`, `TRACEABILITY.md`, `REPRODUCIBILITY.md`,
    `EXPERIMENTATION.md`), operations (`DEPLOYMENT.md`, `DOCKER_SWARM.md`, `TESTING.md`,
    `EXTENDING.md`), plus `RESEARCH_NOTES.md`, `ANTI_PATTERNS.md`, `docs/README.md`.
12. Wrote consensus formalism documents for `weighted`, `evidence_weighted`,
    `constraint_aware` (MVP) and `deliberative`, `bayesian`, `prediction_market` (research), plus
    `README.md` (shared definitions and the feasibility gate) and `TEMPLATE.md`. Files are named by
    strategy id, not by a `*-consensus.md` suffix.
13. Wrote project state: `PLAN.md`, `TASKS.md`, `CURRENT_STATE.md`, `ERRORS.md`, `DECISIONS.md`,
    `HANDOFF.md`, and a hand-seeded `TRACEABILITY.csv`.
14. Ran the Phase 0 validation pass (file inventory, Mermaid fence balance, relative-link
    resolution, contradiction checklist) and fixed what it found.
15. **Reconciliation (T0-13).** The inventory revealed that `tasks.md` and `CHANGELOG.md` marked work
    complete that had never been written: 18 referenced documents did not exist. Created them
    (`API_CONTRACTS.md`, `METRICS.md`, `CONSENSUS_MODEL.md`, `EPISTEMIC_MODEL.md`,
    `RAG_ARCHITECTURE.md`, `SIMULATION_ARCHITECTURE.md`, `MARL_MODEL.md`, `MVP_BOUNDARY.md`,
    `NEURO_SYMBOLIC.md`, `MEMORY_ARCHITECTURE.md`, `AGENT_MODEL.md`, `AGENT_PROTOCOLS.md`,
    `STRUCTURED_REASONING.md` and the trustworthiness set), added ADR-017 … ADR-020, unified every
    `Phase:` field against the roadmap, and rewrote the state files against the filesystem.
    Recorded as `E-01` in `project/ERRORS.md` with a prevention rule.

**Tests run:** none applicable — no executable code exists yet. Validation consisted of
structural documentation checks (see `project/CURRENT_STATE.md` §"Last successful command").

**Buildable / testable / documented / runnable / recoverable:**
documented ✔ · recoverable ✔ · buildable/testable/runnable are *not applicable* in
Phase 0 by design and become applicable in Phase 1.

**Not done:** no application code, no infra manifests — deliberate.

---

### 2026-09-04 — Phase 1 acceptance reconciliation

- Audited T1-00 through T1-15 against the acceptance text in `project/TASKS.md`.
- Closed T1-00, T1-01, and T1-11; all other tasks remain open for explicitly documented missing evidence.
- Restored green backend gates: Ruff clean, mypy clean across 46 source files, 25 pytest tests passing.
- Fixed `InMemoryEventBus.read_from()` sequence replay and added regression tests.
- Completed T1-02: added the lifespan-managed FastAPI factory, wired settings, health routes,
  middleware and problem handlers, and proved lifecycle, liveness/readiness separation, and uniform
  domain/validation/404/unhandled error envelopes with endpoint-level tests.
- Revalidated the backend: Ruff clean, mypy clean across 47 app source files, 32 pytest tests passing.
- Completed T1-03: added AST-based package-boundary enforcement plus mutation-style self-tests that
  reject deliberate absolute and relative domain-to-adapter imports while accepting allowed inward
  edges. Revalidated Ruff, mypy across 47 app source files, and 39 pytest tests.
- Completed T1-04: added async SQLAlchemy/asyncpg engine and tenant-scoped sessions, shared typed ORM
  metadata, minimal workspace/tenant models, and an Alembic baseline with enabled and forced RLS. A
  disposable PostgreSQL 16 test proved clean upgrade and non-owner cross-tenant read/update/insert
  isolation.
- Completed T1-05: added the pgvector extension, a forced-RLS `vector_items` table and cosine IVFFlat
  index, plus a thin async PostgreSQL `VectorStore` with deterministic tie ordering, metadata filters,
  upsert, namespace deletion, and port-error translation. A deterministic 1,000-vector integration
  fixture proved stable top-k retrieval, extension/index presence, and non-owner tenant isolation.
  Revalidated Ruff, mypy across 67 source files, 46 non-integration tests, and two PostgreSQL/pgvector
  integration tests.
- Completed T1-06: aligned in-memory and Redis cache semantics, bounded every write TTL to 1–86,400
  seconds, retained atomic `SET NX EX` fixed windows, and added contract tests. A disposable Redis 7
  instance with RDB/AOF persistence disabled proved every key expires, invalid TTL writes create no
  keys, fixed windows do not extend, and actual expiry occurs. Revalidated Ruff, mypy across 69 source
  files, 51 non-integration tests, 7 layering tests, and the Redis integration test.
- Completed T1-07: added real MinIO acceptance coverage for upload/get, presigned HTTP read, SHA-256
  tamper detection, health, and anonymous `s3:ListBucket` denial. Disposable MinIO integration passed;
  Ruff, mypy across 70 source files, and 51 non-integration tests remained green.
- Completed T1-08: fixed four `nats-py` integration defects in reconnect, default-domain, stream replica,
  and queue/durable configuration. A disposable NATS Server 2.10.29 JetStream test proved
  publish/subscribe, NAK redelivery of the same event ID, and exactly one consumer-side effect after
  event-ID deduplication. Ruff, mypy across 71 source files, 51 non-integration tests, and the repeatable
  NATS integration proof passed.
- Completed T1-09: added a root development Compose stack, a locked non-root backend image, migration
  and MinIO bucket-init jobs, persistent named volumes, loopback-only host ports, disabled Redis
  persistence, and healthchecks for every long-running service. A clean `docker compose up --wait`
  exited 0; Postgres, Redis, MinIO, NATS, and backend were healthy; both init jobs exited 0; `/ready`
  reported all adapters `ok`; Alembic was at head; all five live integration tests passed.
- Completed T1-10: added `AccessTokenVerifier`, immutable verified principals carrying workspace context,
  canonical workspace roles, external-identity users, and forced-RLS memberships. The application now
  permits only `/health` and `/ready` without authentication, rejects missing/invalid bearer tokens,
  denies routes without explicit role policy, disables generated API documentation, and ships an
  unconfigured production verifier that accepts no token. All four roles, workspace context, and problem
  responses are covered; a disposable PostgreSQL test proved migration `0003`, exact enum values, and
  non-owner cross-workspace membership read/insert isolation plus zero Alembic schema drift. Ruff,
  format, mypy (76 files), and 64
  non-integration tests passed.
- Advanced T1-12 to integration validation: added application-owned tracer providers and Prometheus
  registries, explicit FastAPI/SQLAlchemy lifecycle cleanup, authenticated `ADMIN`/`OPERATOR` metrics,
  route-template RED metrics, SQL query/transaction telemetry without statement or parameter capture,
  and recursive structured-log redaction with request/span context. Added unit acceptance for RBAC,
  cardinality, isolation, shutdown, startup failure, redaction, and SQL telemetry, plus an authenticated
  test-only API→PostgreSQL trace test using `InMemorySpanExporter`. Ruff, mypy across 80 files, and all
  69 non-integration tests pass. The PostgreSQL test collected and skipped because
  `TEST_DATABASE_URL` is unavailable and this host has no Docker engine; T1-12 remains in progress.
- Completed T1-13: added authored OpenAPI 3.1/error contracts, deterministic generated TypeScript,
  React 18 + strict TypeScript + Vite, hash routing, TanStack Query, local fonts, a responsive operational
  observatory, accessibility checks, and a locked non-root frontend image. Format, ESLint, strict
  typecheck, six Vitest tests, OpenAPI lint, codegen diff, and production build pass.
- Completed T1-14: added GitHub Actions gates for backend/frontend quality, contracts, generated-client
  drift, traceability seed and Markdown links, empty-session replay, and a full Compose integration job.
  The integration job supplies every `TEST_*` value, exercises all adapters including the API-to-DB
  trace, checks API/frontend health, and cannot convert missing infrastructure into a skip.
- Added executable offline contract/link/trace checks and corrected the malformed seven-column
  `TRACEABILITY.csv` seed to match its eight-column schema. Full annotation generation remains T10-03.
- Completed T1-12 live acceptance after Docker became available: the targeted authenticated
  FastAPI-to-PostgreSQL trace passed with server/DB parentage, correlation metadata, RED/database
  metrics, and SQL non-leakage assertions intact. All six integration tests then passed with no skip.
- Advanced T1-15: clean expanded Compose stack built and reached healthy for Postgres, Redis, MinIO,
  NATS, backend, and frontend; init jobs exited 0; `/ready` returned 200 with five `ok` components; the
  frontend returned 200. First GitHub Actions run `33922160948` exposed three clean-checkout/tooling
  defects; fixes are recorded as E-09. Run `33923240340` then passed all six required jobs, closing T1-15
  and Phase 1.

---

## Milestone ledger

### 2026-09-12 — T11-01 formalisation pipeline

- Added a closed typed AST with canonical numeric strings, deterministic rendering and RFC 8785/JCS
  hashing; validation is structural/type/unit-only and never invokes a solver.
- Added immutable exact-source-pinned revisions, deterministic validation facts, human confirmation or
  rejection facts, and derived `CANDIDATE`, `VALIDATED`, `REJECTED` plus exact enforceability semantics.
- Added forced-RLS PostgreSQL tables and constraints, advisory-lock revision serialization, lifecycle
  outbox records, idempotent authenticated APIs, OpenAPI/generated types, and FR-707 traceability.
- Validation: 7 focused domain/API tests, one live PostgreSQL test, 684 non-integration tests, Ruff/format,
  strict mypy, compileall, OpenAPI/client, frontend typecheck, traceability, links, and migration checks pass.

| Milestone | Target | Status |
| --- | --- | --- |
| M0 Architecture approved | after Phase 0 review | **complete — D-13, 2026-09-04** |
| M1 Skeleton runs in Compose | Phase 1 | **complete — expanded stack and all local gates green; run `33923240340` green** |
| M2 Agents configurable, MockLLM works | Phase 2 | **complete — provider-neutral calls, encrypted credentials, durable registry/accounting, and live PostgreSQL proof green** |
| M3 Artifacts + event ledger persisted | Phase 3 | **complete — typed persistence, atomic graph/ledger lifecycle, acceptance and exact-SHA CI green** |
| M4 Session survives browser close | Phase 4 | **complete locally — ledger-backed SSE, browser rehydration, and worker retry recovery green** |
| M5 Retrieval with provenance | Phase 5 | **local exit candidate committed at `45253c8`; remote CI pending** |
| M6 Structured assessments | Phase 6 | **complete — T6-00…09 and exact-SHA GitHub Actions run `34146288870` green** |
| M7 Critic → revision cycle | Phase 7 | **complete — T7-00…08 and exact-SHA GitHub Actions run `34667037521` green** |
| M8 Numerical simulation | Phase 8 | not started |
| M9 Constraint-aware consensus + minority preserved | Phase 9 | not started |
| M10 Recommendation traces to sources | Phase 10 | not started |
| M11 Z3 rejects infeasible alternative | Phase 11 | **Complete** — T11-01…04 complete; UNSAT alternatives are blocked and UNKNOWN remains unresolved |
| M12 Trajectories recorded | Phase 12 | not started |
| M13 Manifest + replay modes | Phase 13 | not started |
| M14 Full UI | Phase 14 | T14-01…04 complete; T14-05…06 open |
| M15 MCP gateway enforced | Phase 15 | not started |
| M16 Research extensions demonstrated | Phase 16 | not started |
| M17 Swarm stack hardened | Phase 17 | not started |
| **MVP demo: 18 success criteria** | end of Phase 14 core | not started |

---

## Velocity / effort notes

Phase 0 produced ~45 documents. The dominant cost is *decision precision*, not typing:
every artifact envelope field and every port signature becomes a compatibility
obligation later. Keep subsequent phases similarly incremental — one subsystem per
session, documented and tested before moving on.

### 2026-09-05 — Phase 2 publication and Phase 3 planning

- Pushed Phase 2 commit `5034e7b07cefec9532fc8930f086e5da082bf6d9`; `origin/master` resolves to the
  same SHA and GitHub Actions run `33952091288` passed.
- Split the Phase 3 XL outline into four increments and T3-00…T3-09 with explicit acceptance gates.
- Found contract conflicts that block implementation: the "20 entities" list crosses later phases;
  FR-301 names 14 artifact kinds but `facts` has no concrete table; the envelope/status vocabularies and
  ledger actor/hash fields disagree; evidence references Phase 5 source/chunk tables; and the old exit
  gate referred to a nonexistent `artifacts` table.
- Made T3-00 a documentation-first reconciliation gate. No Phase 3 runtime code is claimed.
- Completed T3-00: froze 14 artifacts, lifecycle/envelope, `Fact` provenance, session/API/UI ownership,
  graph projection, four ledger actor classes, transactional per-session sequence allocation, RFC 8785
  canonicalization and exact hash preimages. Planning SHA `0eb5810` passed run `33952819808`.

### 2026-09-06 — T4-05 bounded activity policy

- Added SDK-free state-commit and agent-turn timeout/retry policy mapped explicitly into Temporal.
- Added stable caller-derived operation IDs, redacted permanent/transient classification, heartbeats and
  cancellation draining, plus exact-replay PostgreSQL LLM-call accounting.
- Added preallocated bootstrap/control failure IDs and atomic `ACTIVITY_DEAD_LETTERED` transitions from the
  active lifecycle state to `FAILED`; PostgreSQL lifecycle and ledger remain checkpoint authority.
- Verified 73 focused tests, 303 non-integration tests, 30 live integrations (including `DRAFT → FAILED`
  replay and conflicting call identity), Ruff format/lint, strict mypy over 162 files, 86 Markdown links,
  and `git diff --check`. Commit/push and exact-SHA CI are pending.

### 2026-09-06 — T4-06 through T4-08 durable realtime and recovery

- Added post-commit ledger event capture/publication, strict reference-only NATS envelopes, existing-stream
  subject reconciliation, and a PostgreSQL-authoritative SSE gateway with `Last-Event-ID` resume.
- Added browser-close restoration from a minimal durable session pointer, authoritative projection reload,
  ordered timeline replay, duplicate-sequence suppression, reconnect state, and terminal stream shutdown.
- Added HTTP authorization/cursor tests, authored event schema enforcement, real ledger→NATS→SSE integration,
  replacement-worker PostgreSQL exact replay, and real Temporal worker restart after post-commit ack loss.
- Verified 326 backend non-integration tests, 25 frontend tests, focused live PostgreSQL/NATS/Temporal recovery,
  Ruff, strict mypy over 173 files, frontend lint/build, contract path checks, and generated API type drift.
  Commit/push and exact-SHA CI remain pending.
