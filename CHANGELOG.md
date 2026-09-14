# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
uses semantic versioning once it ships a release. Phase 0 is pre-release.

---

## [Unreleased]

### Added — Phase 14 T14-01 (Graph View)

- Added authenticated `POST /api/v1/graph/subgraph` over the existing tenant/session-scoped graph traversal,
  including public IDs, closed filters, bounded radius/page size, query-bound cursors, deterministic ordering
  and independent truncation/pagination.
- Added a code-split responsive Graph View with authoritative TanStack Query state, labelled edge semantics,
  keyboard selection, visible focus, textual equivalence and explicit operational states.
- Added focused API, PostgreSQL and frontend acceptance coverage. No migration, persistence, repository or
  traversal implementation was added.

### Added — Phase 14 acceptance contract

- Froze the ordered T14-01…T14-06 Graph, Dissent, Assumption, Explanation, Replay and Audit UI task
  boundaries, requirement references and ownership in `docs/PHASE14_ACCEPTANCE.md`.
- Defined the scripted Phase 14 usability fixture without claiming implementation or passing evidence.
- Preserved all existing graph, consensus, symbolic, replay, manifest and audit infrastructure; no runtime
  code, API route, frontend component, persistence or migration changed.

### Added — Phase 13 T13-04 (pinned run manifests)

- Added canonical version-1 `RunManifestDocument` pins and deterministic manifest bytes/hash/identity.
- Added creation and exactly-once finalization through content-addressed object storage, plus exact
  finalized-manifest resolution for T13-03 strict replay with no latest fallback.
- Added migration `20260914_0026` for one forced-RLS, tenant-safe manifest per session, optional
  source-session lineage, and database-enforced immutable finalized state.

### Added — Phase 13 T13-03 (full-session replay modes)

- Added closed, typed `REPLAY_STRICT`, `REPLAY_TOLERANT`, and `REPLAY_LIVE` contracts and exhaustive
  `SessionReplayService` orchestration. All modes bind an exact caller-scoped historical source and verify
  the authoritative ledger chain/event set before replay.
- STRICT reconstructs recorded external outputs, invokes only exact-version deterministic local
  implementations, reuses Phase 12 MARL bundle verification, stops at the first mismatch, and never writes
  historical data. TOLERANT re-executes only explicitly permitted steps and returns ordered structured
  implementation/provider/model/configuration/output/status/timing-sensitive differences without claiming
  strict verification. LIVE requires a source-linked new execution with fresh session, manifest, event and
  result identities.
- Added 11 focused tests. No migration or HTTP endpoint was added; durable run manifests and database-backed
  live replay lineage remain T13-04.

### Added — Phase 13 T13-02 (audit record generation and the eight audit queries)

- Added migration `20260912_0025` with tenant-safe forced-RLS, caller-append-only `access_log` and
  `audit_anchors` (shared `BEFORE UPDATE OR DELETE` trigger raising sqlstate 27000, `REVOKE UPDATE,
  DELETE`, composite `(workspace_id, session_id)` FK into `sessions`).
- Added typed audit contracts (`app/domain/audit.py`: access-log entries, anchor publishing via the
  shared deterministic `_anchor_facts`, chain/append reports), DB adapters (`app/db/audit.py`:
  `SqlAlchemyAccessLogRepository`, `SqlAlchemyAuditAnchorRepository`,
  `SqlAlchemySessionParticipantReader`) and `ConsensusResultStore.get_round_result`.
- Added `app/application/audit.py` answering the eight audit questions (Q1–Q8) as typed services —
  `AuditQueryService` (originating-turn rationale, sealed claims, round context, dissent, termination,
  strategy provenance), `AccessAuditService` (Q7 bounded strictly before `recommendations.created_at`,
  cursor pagination) and `ChainVerificationService` (per-day head recomputation + ledger `verify`).
- Added 21 focused unit tests and 7 live PostgreSQL acceptance tests (append-only, RLS 42501
  isolation, FK 23503, Q7-before-acceptance, same-day anchor conflict, two-day chain verification,
  tamper detection). No HTTP/OpenAPI added (Phase 14).
- Reconciled AUDITABILITY.md (v1.4: implemented storage + per-question real paths) and DATA_MODEL.md
  (§11.1 with implemented DDL); FR-807/NFR-006 flipped to implemented
  (`last_verified: local-phase13-2026-09-14`).

### Fixed — Phase 13 census acceptance

- Extended the head-tables census in `test_reasoning_revision_downgrades_reupgrades_and_has_no_drift`
  with the Phase 13 table set (`access_log`, `audit_anchors`) so the migration-drift test passes at
  head `20260912_0025`.

### Added — Phase 13 T13-01 (metric catalogue)

- Added the `MetricPlugin` port, immutable six-field `MetricDefinition` value objects, the
  deterministic domain `MetricCatalogue` and an application catalogue of all 43 METRICS.md metrics
  (`EP-01…06`, `RR-01…07`, `DH-01…07`, `CQ-01…06`, `RB-01…05`, `CE-01…05`, `HO-01…04`, `CA-01…03`).
- Added exact `get(metric_id, metric_version)` lookup with no "latest" fallback, retirement-with-
  successor rules, and 13 catalogue tests that transcribe METRICS.md field-by-field and pin the Phase 12
  reward metrics (FR-901, FR-902, NFR-019). No metric engine, storage, API, UI, replay or migration was
  introduced; Alembic head stays `20260912_0024`.

### Added — isolated Compose stack under `agora_opencode`

- Relabelled the Compose project `agora_opencode`, parameterised every host-facing port in `.env`
  (loopback-bound, non-conflicting defaults), and introduced dedicated volumes, networks and
  `agora_opencode/`-prefixed images so the dev stack cannot collide with an existing `agora` deployment.

### Fixed — Phase 12 ORM/alembic-chain acceptance drift (surfaced by the integration gate)

- Declared the `ck_marl_episodes_status_shape` CHECK constraint on `MarlEpisodeRow`, which migration
  `20260912_0024` creates but the ORM metadata had omitted, so `alembic check` no longer flags it for
  removal (E-21). No migration file changed; head stays `20260912_0024`.
- Replaced the stale hardcoded head literal `20260911_0021` with the runtime-resolved Alembic head in
  `test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` and extended its head-tables census
  with the Phase 11 (`formalizations`, `formalization_validations`, `formalization_decisions`,
  `symbolic_evaluations`) and Phase 12 (`marl_episodes`, `marl_trajectory_records`) tables (E-22).

### Added — Phase 12 deterministic MARL trajectories

- Added strict frozen observation, action, coordinator, five-component exact reward, provenance-credit,
  transition, episode, export, and replay-result contracts. Symbolic feasibility remains authoritative.
- Added deterministic in-memory and caller-transaction-owned PostgreSQL trajectory stores, migration
  `20260912_0024`, forced RLS, tenant-safe foreign keys, append-only facts, and append-or-conflict semantics.
- Added exact two-file JCS export and bounded hermetic offline verification with a closed deterministic
  fourteen-code failure precedence. No training algorithm, production-policy wiring, Phase 13 metric engine,
  or full-session `REPLAY_STRICT` was introduced.

### Added — Phase 11 T11-04 (UNKNOWN handling policy)

- Added an application-owned exhaustive symbolic policy: `SAT → PROCEED`, `UNSAT → BLOCK`, and
  `UNKNOWN → DEFER`, with deterministic timeout/incomplete/other classification and structured
  explanation metadata.
- Integrated the policy with persisted symbolic evaluation and the shared consensus feasibility gate.
  `UNKNOWN` remains visible and immutable; if non-symbolic inputs rank it first, the result is explicitly
  `CONDITIONAL_CONSENSUS` and never positive symbolic assurance.
- Added no migration, API, graph edge, outbox event, retry, lifecycle mutation, or human override.

### Added — Phase 11 T11-02 (Z3 symbolic reasoner)

- Added a solver-neutral `SymbolicReasoner` port and bounded, per-invocation Z3 adapter for the complete
  closed T11-01 AST/operator set, with explicit symbol/sort checks and exact decimal/rational semantics.
- Added first-class `SAT`, `UNSAT`, and `UNKNOWN` results with revision/hash, solver version, timeout and
  deterministic configuration metadata; invalid input, unsupported input, and solver failures remain
  distinct from unsatisfiability.
- Wired the adapter through process composition and added exhaustive focused tests. No API, persistence,
  graph, outbox, lifecycle, enforceability, witness, or unsat-core behavior changed.

### Added — Phase 11 T11-01 (formalisation pipeline)

- Added immutable, source-revision-pinned formalisation revisions with a closed typed AST, canonical JCS
  hashing/rendering, explicit symbols and deterministic structural, sort and unit validation.
- Added authoritative status derivation from append-only validation and human decision facts:
  `CANDIDATE`, `VALIDATED`, and `REJECTED`. Only a successfully validated and human-confirmed exact
  revision is enforceable; no solver execution or symbolic evaluation persistence is included.
- Added forced-RLS PostgreSQL persistence, lifecycle outbox facts, optimistic concurrency, idempotent
  authenticated APIs, opaque `frm_` IDs, tests, and generated API/traceability contracts.

### Added — Phase 10 (reasoning graph provenance)

- Added T10-04 workspace-wide source-impact analysis over every canonical citation root. The service
  exhausts paginated, depth-bounded forward traversals, preserves exact artifact versions and path
  metadata, and reports affected claims, alternatives, consensus results, and recommendations with an
  explicit `COMPLETE` or `INCOMPLETE` state. Source retraction, immutable impact/dependency persistence,
  and durable `SOURCE_RETRACTED` workspace-outbox insertion are atomic and do not mutate downstream
  artifacts. Authenticated APIs expose idempotent retraction and tenant-scoped report reads.
- Added T10-03 deterministic generation of `project/TRACEABILITY.csv` from validated documentation,
  source, backend-test, and frontend-test annotations for all 104 authoritative requirements. Added
  strict malformed/unknown/node validation, focused generator tests, semantic evidence-quality audit,
  and CI drift checking. Mapping coverage remains explicitly distinct from implementation or scientific
  verification.
- Added T10-02 typed `provenance_of(artifact)` orchestration and
  `GET /api/v1/artifacts/{artifact_id}/provenance`. It reuses bounded, cycle-safe T10-01 backward
  traversal, preserves exact edge semantics and pagination metadata, and enriches EVIDENCE nodes with
  verification plus canonical source/document/chunk citation snapshots and current source status.
- Extended `CitationRepository` with deterministic multi-citation lookup by evidence artifact. No graph
  schema or SOURCE/DOCUMENT/CHUNK graph-node kinds were added.

### Added — Phase 9 (consensus engine)

- Added T9-01 `ConsensusContext`, `ConsensusResult`, `ConsensusExplanation` and every supporting
  consensus value object (`AgentPosition`, `EvidenceCitationInput`, `ObjectiveInput`, `DissentEntry`,
  `MinorityEntry`, `FeasibilityVerdict`, `StrategyConfig`) in `app/ports/consensus.py`, plus the
  eight-member `ConsensusOutcome` enum required by FR-604.
- Added T9-02 the shared feasibility gate (`feasibility_gate()` in `app/domain/consensus.py`),
  implemented once and reused by every strategy so an infeasible alternative can never be ranked
  regardless of score (FR-602, FR-603).
- Added T9-03 `WeightedStrategy` (deterministic linear aggregation), `EvidenceWeightedStrategy`
  (support weighted by verified evidence strength) and `ConstraintAwareStrategy`
  (feasibility-gated lexicographic, MVP default) in `app/application/consensus.py`, each reproducing
  its worked example from `docs/consensus-formalism/` verbatim.
- Added T9-04 outcome classification covering all eight FR-604 classes: `FULL_CONSENSUS`,
  `PARTIAL_CONSENSUS`, `CONDITIONAL_CONSENSUS`, `PARETO_SET`, `NO_CONSENSUS`, `DEADLOCK`,
  `INSUFFICIENT_EVIDENCE`, `INFEASIBLE`. A session with no verified evidence returns
  `INSUFFICIENT_EVIDENCE` rather than a ranking; conflicting objectives yield `PARETO_SET` rather
  than a forced single winner (FR-607).
- Added T9-05 `ConsensusOrchestrator`, resolving a strategy, evaluating it, and persisting the
  result plus a complete explanation with every outcome (FR-605).
- Added T9-06 `StrategyRegistry`, refusing an unregistered or undocumented strategy (FR-608, S-1)
  and rejecting duplicate name/version pairs.
- Minority and dissenting positions are preserved in every result and cannot be suppressed through
  the API (FR-505, FR-506).
- Added 13 new unit tests in `backend/tests/unit/test_consensus.py` covering worked examples for all
  three strategies, registry rejection paths, and orchestrator persistence. Ruff and mypy clean;
  full suite 620 passed, 0 failed, 43 pre-existing unrelated skips.

### Added — Phase 8 (simulation & sandbox execution)

- Added T8-01 simulation domain types split across layers. Port-level `SimulationSpec` with content-addressed
  `spec_content_hash`, `SimulationResult` carrying all FR-702 fields (engine, engine_version, spec_hash, seed,
  run_count, convergence, intervals, sensitivity, validity_domain), and 4 enums (`EngineKind`,
  `ConvergenceStatus`, `SimulationFailureCode`, `NetworkPolicy`) plus 10 value objects in
  `app/ports/simulation.py`. Uses local `_Frozen` base class (no cross-layer import). Domain layer adds
  `RunStatus`, `SimulationRunRecord` (with status-dependent validation), and `SimulationRunStore` protocol.
- Added T8-02 `SimulationEngine` and `SandboxExecutionProvider` port protocols. Engine defines `run`,
  `validate`, `capabilities`; sandbox defines `execute`, `health`, `close` with `SandboxRequest` (image
  digest, resource limits, no-network default) and `SandboxResult` (exit code, terminated_by consistency).
- Added T8-03 `SimulationOrchestrator` application service coordinating request → validate → run → rank
  sensitivity → store. Handles `TimeoutError` → `TIMEOUT` and generic exceptions → `FAILED` with proper
  error recording and status transitions.
- Added T8-04 `compute_sensitivity_ranks()` pure function ranking sensitivity entries by descending absolute
  index value.
- Added T8-05 Alembic migration `20260909_0020` for `simulation_runs` and `simulation_results` tables with
  forced RLS, CHECK constraints, and indexes on workspace+session and spec_hash.
- Added T8-00 contract tests: 36 tests covering `SimulationSpec` (14), `SimulationResult` (6),
  `ValidationReport` (2), `SimulationRunRecord` (5), port protocols (4), sensitivity ranking (3), and async
  orchestration (2) with `InMemorySimulationRunStore` and `StubSimulationEngine` test doubles.

### Added — Phase 7 (critic and revision loop)

- Closed T7-08 with 82 focused, 677 offline and 52 live tests; clean backend/frontend, contract,
  migration, traceability, link, whitespace and anti-pattern gates; and a clean disposable Compose run.
  GitHub Actions run `34667037521` passed all six jobs at exact SHA
  `25914b48e1c5140279720d1a4dfb66483cf744a3`. MinIO and its client retain their exact image versions and
  digests while using Quay after the corresponding Docker Hub repositories became unavailable.
- Froze T7-00 against Phase 6 SHA `6d671acffe7abd3e5b587042457f300e0c442adc`: exact FR-501
  taxonomy, Critic-only proposal authority, target eligibility, seven response dispositions, immutable
  Critique resolution, sealed target revision, request deferral, stable phase ordering and complete
  explanation handoff. Reused existing artifact, graph, ledger, runtime, attribution and budget paths;
  kept simulation, consensus, traversal, metrics and full UI in their owning phases.
- Added T7-01 frozen `CritiqueAssignment` and `CritiqueResponseProposal` values plus pure Critic-bundle
  validation over the existing provider-neutral `ProposalBundle`. Exact FR-501/FR-503 values are enforced;
  aliases, mutation fields, wrong-kind/non-open/unassigned/duplicate attacks, Critic requests, and malformed
  disposition-specific effects fail closed.
- Shipped one deterministic workspace-scoped cross-cutting Critic with adversarial objectives, a literal
  LF prompt digest and content-addressed staging. A real mock-backed activity fixture emits one valid
  Critique against every one of the 14 artifact kinds.
- Added coordinator-mediated Critic dispatch over the existing authorized context, bounded worker pool and
  durable budget boundary. Assignment pins must match the hydrated context; timeout remains `TURN_TIMEOUT`,
  while only the third consecutive completed empty round records `CRITIC_INACTIVE`.
- Added assignment-gated atomic Critique commit. The coordinator derives hash-covered `ATTACKS`
  relationships and retry-stable edge IDs before the existing artifact/graph/ledger transaction; exact
  retry is idempotent and invalid/hidden/inactive/future targets leave no partial writes.
- Added T7-05/T7-06 atomic Critique responses. All seven dispositions append immutable Critique resolution
  heads and explicit append-only request/results with complete runtime attribution. Target-owner,
  visibility, warrant, current-head and retry checks fail closed; exact retries return the prior result.
- Added same-kind target revisions with coordinator-derived `SUPERSEDES`, `RESPONDS_TO`, and Critique
  `ATTACKS` lineage. Migration `20260907_0019` adds forced-RLS append-only response tables and widens only
  graph-level `RESPONDS_TO` validation to all artifact kinds without relaxing direct `FACT`/`EVIDENCE`
  creation policy.
- Added T7-07 deterministic `CRITIQUE` then `REVISE` orchestration. Dedicated Critic and peer turns retain
  bounded budgeted dispatch and pinned commit order; response turns use sealed contexts and stable
  target/responder commit order. Timeouts append explicit abstention events, all phase outputs validate
  before their first commit, and the complete latest-head explanation handoff has no omission control.

### Added — Phase 6 (domain expert reasoning)

- Froze T6-00 authority, runtime/strategy, automatic decomposition, sealed-assessment, durable
  `NO_EVIDENCE`, attribution, intervention, budget and 20-logical-agent acceptance contracts before
  runtime work. Kept Critic/revision, consensus, metrics/replay and experiments in their owning phases.
- Added immutable `ReasoningContext`, generic `AgentRuntime` / `ReasoningStrategy` ports, fail-closed
  exact-version strategy selection, Phase 4 activity composition and a deterministic offline strategy.
  Position proposals now require a consistent `CITED` or `NO_EVIDENCE` disposition.
- Added proposal-only automatic decomposition through the pinned agent activity path. Empty, mixed,
  request-bearing, canonicalizer-mismatched, ambiguous and duplicate proposition bundles fail before
  identity allocation or persistence.
- Added fail-closed authorized reasoning-context assembly over immutable pinned-definition, typed
  objective/constraint, eligible artifact and retrieval-provenance snapshots. Cross-scope or stale data,
  malformed authorization, missing required retrieval and round-one artifact visibility are rejected;
  successful zero-match retrieval remains distinct from failure through the final LLM prompt.
- Added deterministic proposal validation and caller-transaction-scoped coordinator commit. Complete
  bundles are preflighted before writes; fabricated, inactive, future or wrong-kind references fail closed.
  Retry-stable artifact/node/event identities and a turn-scoped PostgreSQL advisory lock make exact
  concurrent redelivery idempotent while partial or conflicting prior commits are rejected.
- Persisted accepted artifacts, graph-node projections and attribution-rich ledger events in proposal
  order. Position confidence is mandatory, `CITED`/`NO_EVIDENCE` is hash-covered in artifact metadata and
  event payloads, and provider model, prompt pin, usage, cost, turn, phase and commit time remain auditable.
- Added the deterministic five-expert policy catalogue for fiscal, macroeconomic, social, infrastructure
  and risk analysis. Definitions use workspace-scoped UUIDv5 identities, distinct objectives and stances,
  and exact strategy/prompt pins.
- Shipped five digest-sealed UTF-8 prompt resources with content-addressed object keys and `ObjectStore`
  staging. All five run through the existing sealed agent-turn activity with schema-valid deterministic
  mock output; JSON-native validation now accepts JSON arrays for strict tuple fields without weakening
  strict scalar validation.
- Added bounded shared-pool dispatch for sealed logical-agent turns. Dispatch rejects unsealed or mixed
  round-one `ASSESS` batches before invoking a worker, preserves input order despite completion races, and
  converts only per-turn deadlines into typed `ABSTAIN` outcomes with `TURN_TIMEOUT`; runtime failures still
  propagate and workers retain no persistence, workflow-transition or peer-channel authority.
- Added strict inert orchestrator proposals for decomposition, eligible-agent routing and immediate phase
  advancement. Deterministic coordinator policy rejects pin, phase, route and fixed-order violations and
  appends one retry-stable `POLICY` acceptance/rejection event with `applied: false`; no mutation dependency
  or workflow extension is exposed.
- Added append-only, ledger-ordered effective-round session membership with lifecycle-lock serialization,
  context/retrieval enforcement, and forced workspace RLS. Added durable session and strict per-definition
  token/USD checks around bounded dispatch with explicit one-time `BUDGET_EXHAUSTED` failure. The 20-agent
  fixture now commits 20 fully attributed claims in pinned order through four shared workers.

### Added — Phase 5 (RAG and memory namespaces)

- Froze T5-00 retrieval, ingestion, namespace, citation, memory and evaluation contracts before runtime
  work; added requirement-level T5-01…09 acceptance criteria.
- Selected deterministic 800-token-target/150-token-overlap chunking, explicit pre-scoring namespace
  grants, PostgreSQL provenance authority over derived vector indexes, and a versioned synthetic retrieval
  mechanics baseline that does not pre-empt Phase 16 experiment-domain selection.
- Added T5-09 local exit candidate: versioned domain-neutral corpus and reviewed labels, deterministic
  baseline evaluator, PostgreSQL exact-output/digest/isolation gate and durable `RAG_FAILED` audits.
  Full local Compose gate passes; exact-SHA CI remains pending owner-requested publication.
- Reconciled `MemoryProvider` signatures and froze asynchronous source ingestion, session retrieval,
  resolvable human evidence, additive source retraction and validated promotion API ownership.
- Added strict immutable ingestion contracts, pinned deterministic whitespace chunking, exact locators
  and content identity plus parsing adapters for PDF, DOCX, TXT, Markdown, CSV, XLSX, JSON and HTML.
  Empty, malformed and invalid-UTF-8 documents fail closed; table rows remain whole with repeated headers.
- Added tenant-safe knowledge namespace, grant, source, document and chunk contracts, ORM rows and
  transaction-scoped repositories. Migration `20260906_0010` enforces composite workspace references,
  forced RLS, typed grant subjects, immutable provenance identities and no physical provenance deletion.
- Added a typed Temporal source-ingestion activity and PostgreSQL-authoritative operation checkpoints.
  Migration `20260906_0011` persists independent acquire/parse/embed/index states, attempt counts, parser
  warnings and redacted failure taxonomy under forced RLS. Content-addressed source bytes are read-back
  digest verified; exact retries return original IDs; unsupported media fails explicitly after acquisition.
- Added PostgreSQL hybrid retrieval with pre-score namespace/grant/ACL filtering, deterministic RRF,
  strict reranking, explicit degradation and append-only text-free retrieval audits.
- Added exact citation snapshots and PostgreSQL-validated human evidence attachment. Migration
  `20260906_0015` adds append-only forced-RLS citation/retraction facts; irreversible, reason-required
  retraction excludes future retrieval while preserving old resolution and Phase 10 dependencies.
- Added explicit working, episodic, semantic and procedural memory scopes plus a frozen-port-compatible
  `MemoryProvider`. Migration `20260906_0016` adds append-only forced-RLS semantic entries, validated
  promotions, evidence sets and monotonic stale/archive history; direct writes and SQL bypass fail without
  deleting authoritative rows.

### Added — Phase 4 (durable orchestration)

- Added typed, SDK-free `WorkflowEngine` and lifecycle-only `WorkflowWorker` ports with deterministic
  in-memory reference adapters and Temporal Python SDK 1.32.0 adapters.
- Added idempotent workflow starts with explicit duplicate policies, diagnostic execution descriptions,
  health/readiness integration and raw-SDK exception translation.
- Added pinned Temporal Server 1.29.1, PostgreSQL 16 and UI 2.34.0 Compose services plus CI/live tests for
  start, duplicate start, describe, health and actual worker polling/completion.
- Reconciled workflow trigger and state authority: draft creation remains `201`; T4-02 adds separate
  start `202`; PostgreSQL and the ledger remain authoritative over Temporal visibility state.
- Added the complete validated session lifecycle graph, forced-RLS `session_lifecycles` projection,
  row-locked atomic projection/ledger transitions, and migration `20260905_0009`.
- Added deterministic `SessionBootstrapWorkflow` registration and worker composition; API-allocated
  transition IDs are immutable workflow input, activity I/O is retry-safe, and the workflow persists
  `SESSION_INITIALIZED` followed by round-one `ROUND_STARTED` before its durable Temporal wait.
- Added idempotent `POST /api/v1/sessions/{id}/start` with stable workflow/run reattachment after API
  rollback, lifecycle-backed session responses, authored OpenAPI, generated TypeScript, and frontend client.
- Added strict versioned agent-turn/proposal contracts, a Temporal `run_agent_turn` activity, sealed
  content-hash-verified prompt loading, provider-independent usage accounting, and proposal-only authority
  validation. Process-lived activities hold factories rather than SQLAlchemy sessions; each registry
  operation opens its own tenant-scoped transaction and every turn-scoped provider is closed deterministically.
- Verified T4-01 through T4-03 implementation commit `8cc835f4029aca5964c388513aeaba1fc02af4d3` with
  GitHub Actions run `34005422198`; all six jobs passed.
- Added authenticated, idempotent pause, resume, cancel, deprecated terminate compatibility and typed human
  directives through strict Temporal signals. Workflow-side serialization and atomic lifecycle/ledger
  activities keep PostgreSQL authoritative. Commit `714f08b7c349a6e6b4d5b11b06299682af3ac76f` passed all six
  jobs in GitHub Actions run `34011486812`.
- Added bounded state-commit and agent-turn activity policies, stable operation IDs, redacted permanent and
  transient failure classification, agent-turn heartbeat/cancellation handling, durable bootstrap/control
  dead-letter transitions, and idempotent PostgreSQL LLM-call accounting. The normative policy is
  `docs/ORCHESTRATION_POLICY.md`.
- Added post-commit ledger-to-NATS publication and authenticated SSE replay from PostgreSQL `ledger_seq` with
  `Last-Event-ID`, reference-only event payloads, authored wire schema, and transport-independent catch-up.
- Added browser-close session restoration with authoritative projection rehydration and ordered timeline
  deduplication, plus live NATS delivery and Temporal worker-replacement recovery tests proving stable
  activity identity and exactly-once committed effects.

### Planning — Phase 3 (structured reasoning model)

- Split the former XL Phase 3 outline into T3-00…T3-09 across contract, persistence, ledger and boundary
  increments with requirement-level acceptance criteria.
- Added a documentation-first reconciliation gate for the conflicting entity taxonomy, artifact
  envelope, `Fact` representation, Phase 5 provenance references, and ledger sequence/hash semantics.
- Froze T3-00: 14 Phase 3 artifact kinds, one lifecycle/envelope, first-class `Fact`, opaque source
  provenance, synchronous draft-session boundary, tenant-safe graph projection, four actor classes,
  gapless per-session ledger order, RFC 8785 canonicalization and exact hash preimages.
- Verified Phase 2 commit `5034e7b` is pushed and GitHub Actions run `33952091288` passed.
- Verified planning commit `0eb5810` with GitHub Actions run `33952819808` passed.

### Added — Phase 3 (structured reasoning model)

- Immutable, strict domain values for the common reasoning envelope and all 14 FR-301 artifact kinds,
  with discriminated unions, epistemic invariants, deep-frozen JSON, RFC 8785 canonicalization and
  deterministic content hashes.
- Immutable `DRAFT` session/problem bindings that pin agent-definition version rows and typed objective
  and constraint references while enforcing workspace/session affinity, uniqueness, budget bounds,
  timestamp validity and round zero without importing Phase 4 workflow behavior.
- Closed proposition normalization status, deterministic version-aware normalization identity and a
  consensus-input guard that rejects ambiguous normalizations.
- Added migration `20260905_0005` and matching SQLAlchemy rows for draft sessions, pinned agents, immutable
  typed reasoning artifacts and objective/constraint bindings, with composite tenant foreign keys, strict
  JSONB checks, deferred integrity triggers, indexes and forced RLS on all five tenant tables.
- Added live PostgreSQL acceptance for payload/envelope validation, decimal and timestamp formats,
  tenant/session references, revision chains, deferred binding completeness, artifact immutability,
  deletion prevention, RLS, downgrade/re-upgrade and Alembic drift. The tests exposed and fixed a missing
  no-op `ELSE` in deferred reference validation for artifact kinds without payload references.
- Added the `ReasoningGraphStore` port, immutable node/edge values and a caller-transaction-scoped
  SQLAlchemy adapter, plus migration `20260905_0006` for tenant-safe graph nodes and edges.
- Enforced node-to-artifact kind resolution, the complete closed edge-endpoint matrix, same-workspace and
  same-session endpoints, no self-loops, unique triples, incident-edge-safe node updates and forced RLS.
- Added exhaustive endpoint-policy and live PostgreSQL acceptance for atomic artifact/projection writes,
  rollback, invalid edges, node updates, RLS, downgrade/re-upgrade and Alembic drift.
- Added immutable ledger values and hash helpers, a caller-transaction-scoped append/read/verify boundary,
  SQLAlchemy rows and migration `20260905_0007` for per-session heads and append-only reasoning events.
- Enforced idempotent event IDs, locked gapless sequence allocation, canonical payload/event hashes,
  tenant/session-safe foreign keys, forced RLS, automatic head creation and database-rejected mutation.
- Added unit and live PostgreSQL proofs for deterministic hashes, retry identity, concurrency, rollback,
  ordered reads, clean-chain verification, tamper detection, least privilege, RLS and migration backfill.
- Added a typed `ReasoningArtifactStore` and transaction-level `ArtifactCommitService` that commit initial
  artifacts with graph nodes and ledger events, append revisions with `SUPERSEDES` edges, and withdraw by
  lifecycle transition plus event without mutating content or deleting history.
- Added locked revision/withdrawal preconditions, caller-supplied IDs and timestamps, ID-only event payloads,
  required withdrawal warrants, typed row rehydration and projection of declared parent relationships.
  Live PostgreSQL proves artifact, graph and ledger writes all roll back when a deferred constraint fails.
- Full backend evidence is 200 offline tests plus 16 PostgreSQL reasoning-persistence tests; Ruff format and
  lint, strict mypy over 115 files, offline migration generation and Alembic drift are green.
- Added tenant-scoped Phase 3 session create/read and artifact create/read/revise/withdraw HTTP routes with
  explicit RBAC, durable idempotent replay, `If-Match` conflicts, typed public IDs and unsupported-claim state.
- Added strict kind-specific JSON boundary decoding for all artifact payloads, source timestamps and session
  deadlines while preserving opaque metadata/locator JSON and strict Python-domain construction.
- Added migration `20260905_0008` for forced-RLS workspace idempotency records, authored all runtime paths in
  OpenAPI, regenerated TypeScript API types and added unit plus live HTTP-to-PostgreSQL acceptance coverage.
- T3-07 evidence: 210 offline tests and 22 configured PostgreSQL integrations pass; OpenAPI/client drift,
  frontend lint/typecheck/6 tests/build, Ruff, strict mypy, layering and migration generation are green.
- Added accessible Phase 3 reasoning desk: complete draft-session manifest, typed proposition creation,
  typed unsupported hypothesis creation, and prominent `UNSUPPORTED / NO EVIDENCE` rendering.
- Corrected stale Phase 0 traceability rows and added implemented code/test/status evidence for every
  FR-101…103 and FR-301…312 requirement. Checker now validates Phase 3 completeness and test node IDs.
- Added exhaustive property suites for revision identity and uncertainty representations. T3-08 evidence:
  226 offline tests passed, 25 live integrations without skips, strict mypy over 126 files, 9 frontend
  tests/build, contracts, traceability, links, Ruff and ESLint green.
- Added a machine-readable Phase 3 schema manifest to `DATA_MODEL.md` and live PostgreSQL acceptance that
  compares every Phase 3 table's ordered columns, types and nullability with that documented contract.
- Completed the local T3-09 exit: all 34 anti-patterns reviewed, inherited backend/frontend/contract/doc
  gates green, clean volume-free Compose rebuild healthy, `/ready` and UI reachable, Alembic at head, and
  all 26 live integration tests passed without skips. GitHub Actions run `33989090448` passed all six jobs
  for exact exit SHA `7aaf1aabdc74a8cdba283d4524759eb1db6a0d03`, closing T3-09 and Phase 3.

### Added — Phase 2 (LLM abstraction & agent registry)

- Provider-neutral generation, embedding, capabilities, normalized errors, usage/cost, trace, timeout,
  and content-addressed raw-artifact contracts.
- OpenAI-compatible HTTP and deterministic fixture-driven mock providers with structured-output
  validation and bounded repair retries.
- Tenant-scoped LLM configuration, encrypted credential envelope, versioned agent definition, and LLM
  call-accounting models, migration, and SQLAlchemy repository.
- AES-256-GCM envelope encryption with random per-credential data keys, workspace/configuration-bound
  authenticated data, and master-key resolution through `SecretProvider`.
- Phase 2 exit contract: one agent definition runs through two distinct compatible endpoints and the
  mock, producing three traceable records with visible per-call cost.
- Live PostgreSQL acceptance for clean migration, forced RLS, tenant-safe foreign keys, bytea encrypted
  fields, repository round-trip, Alembic drift, version supersession, and trigger-enforced immutability.
- Executable boundary checks confining infrastructure SDK imports, including pgvector and Prometheus,
  to `app/adapters/`.

### Added — Phase 1 (Foundation)

- Development `docker-compose.yml` for PostgreSQL/pgvector, Redis, MinIO, NATS JetStream, migration,
  bucket initialization, and the backend, with health-gated startup and loopback-only host ports.
- Reproducible non-root backend image built from `backend/uv.lock`; local credential template in
  `.env.example` with no committed values.
- Full-stack acceptance evidence: clean `docker compose up --wait`, all services healthy, init jobs
  successful, `/ready` all `ok`, Alembic at head, and all five live integration tests passing.
- Deny-by-default bearer authentication and workspace RBAC with canonical `ADMIN`, `RESEARCHER`,
  `OPERATOR`, and `VIEWER` roles; only `/health` and `/ready` are public, while missing route policy
  denies valid principals. Added external-identity users, forced-RLS memberships, and a fail-closed
  unconfigured verifier pending the production IdP adapter.
- Application-scoped OpenTelemetry tracing and SQLAlchemy query spans, isolated Prometheus RED/database
  metrics behind an `ADMIN`/`OPERATOR` `/metrics` policy, recursive structured-log redaction, and
  lifecycle cleanup. Live API-to-PostgreSQL trace acceptance and all six integration tests pass.
- React 18 + strict TypeScript + Vite operational skeleton with hash routing, TanStack Query server
  state, responsive accessibility-aware UI, local fonts, Vitest tests, and a non-root static image.
- Authored OpenAPI 3.1 and error-taxonomy contracts with deterministic TypeScript generation and
  drift checks. Added executable contract, link, traceability-seed, and empty-session replay gates.
- GitHub Actions pipeline gating backend/frontend lint, formatting, typecheck, unit tests, build,
  contracts, traceability, links, full Compose integrations, and API-to-PostgreSQL tracing.
- Expanded Compose proof: frontend plus Postgres, Redis, MinIO, NATS, and backend healthy; init jobs
  exited 0; `/ready` reported five `ok` components; frontend returned 200.

### Added — Phase 0 (Requirements & Architecture)

- Repository scaffold: `README.md`, `CHANGELOG.md`, `.gitignore`, Git repository.
- **Memory bank** (`memory-bank/`): `projectbrief.md`, `architecture.md`,
  `techContext.md`, `activeContext.md`, `progress.md`, `tasks.md`, `decisions.md`,
  `errors.md`, `api-contracts.md`.
- **Project state** (`project/`): `PLAN.md`, `TASKS.md`, `CURRENT_STATE.md`, `ERRORS.md`,
  `DECISIONS.md`, `HANDOFF.md`, and a hand-seeded `TRACEABILITY.csv`.
- **Architecture**: `docs/ARCHITECTURE.md` with eight Mermaid diagrams — Swarm
  deployment, logical services, durable workflow, collective reasoning loop, RAG data
  flow, reasoning/provenance graph, neuro-symbolic flow, consensus flow.
- **Domain specifications**: `docs/REQUIREMENTS.md`, `docs/DATA_MODEL.md`,
  `docs/AGENT_MODEL.md`, `docs/STRUCTURED_REASONING.md`, `docs/REASONING_GRAPH.md`,
  `docs/CONSENSUS_MODEL.md`, `docs/MARL_MODEL.md`, `docs/NEURO_SYMBOLIC.md`,
  `docs/EPISTEMIC_MODEL.md`, `docs/RAG_ARCHITECTURE.md`, `docs/MEMORY_ARCHITECTURE.md`,
  `docs/SIMULATION_ARCHITECTURE.md`, `docs/METRICS.md`, `docs/AGENT_PROTOCOLS.md`.
- **Extension-point contracts**: `docs/PORTS.md` — normative signatures and semantics
  for all nineteen ports (design only; no adapters implemented).
- **Contracts & API**: `docs/API.md`, `docs/API_CONTRACTS.md` (versioned payload
  schemas for reasoning artifacts, events, consensus results, audit records).
- **Trustworthiness**: `docs/AUDITABILITY.md`, `docs/EXPLAINABILITY.md`,
  `docs/TRACEABILITY.md`, `docs/REPRODUCIBILITY.md`, `docs/EXPERIMENTATION.md`.
- **Security**: `docs/SECURITY.md`, `docs/THREAT_MODEL.md`, `docs/MCP_SECURITY.md`.
- **Operations**: `docs/DEPLOYMENT.md`, `docs/DOCKER_SWARM.md`, `docs/TESTING.md`,
  `docs/EXTENDING.md`, `docs/RESEARCH_NOTES.md`, `docs/ANTI_PATTERNS.md`.
- **MVP boundary**: `docs/MVP_BOUNDARY.md` — every requirement classified
  `MVP` / `Core Post-MVP` / `Research Extension` / `Future`.
- **ADRs 001–020** in `docs/adr/` with an index and dependency graph (`docs/adr/README.md`),
  covering every fixed architectural decision plus secret provisioning (017), the sandbox execution
  boundary (018), the append-only event ledger (019) and the stateful HA boundary (020).
- **Consensus formalisms** in `docs/consensus-formalism/`: `README.md` (shared definitions and the
  mandatory feasibility gate), `TEMPLATE.md`, and one specification per strategy — `weighted.md`,
  `evidence_weighted.md`, `constraint_aware.md` (MVP) and `deliberative.md`, `bayesian.md`,
  `prediction_market.md` (research). Files are named by registered strategy id.

### Historical Phase 0 boundary

- Phase 0 deliberately added no runtime code. Backend, frontend, migration, test, image, and Compose
  artifacts were introduced only after approval, during Phase 1.

### Changed

- `docs/README.md` index now reflects the files that exist, with reading orders grouped by role.
- Every `Phase:` field across `docs/`, `docs/adr/` and `docs/consensus-formalism/` unified with the
  roadmap in `README.md` (Z3 → 11, frontend → 14, realtime gateway → 4, sandbox → 8, MARL → 12,
  research strategies → 16). Recorded as decision D-08 in `project/DECISIONS.md`.
- `memory-bank/tasks.md`, `activeContext.md`, `progress.md` rewritten against the filesystem rather
  than against intent.

### Fixed

- **Documentation drift.** `tasks.md` and this changelog recorded `T0-05 … T0-10` as complete while 18
  referenced documents had never been written, leaving cross-links pointing at files that did not
  exist. Created the missing documents and reconciled every state file with the inventory. Root cause
  and prevention recorded as `E-01` in `project/ERRORS.md`.
- Consensus-formalism filenames claimed in the changelog (`weighted-consensus.md` and siblings) never
  matched the files on disk; both are now the strategy-id form.
- `project/CURRENT_STATE.md` asserted the repository was not under Git; it is initialised, with zero
  commits (`E-05`).
- Cross-references corrected to the real section numbers of `REQUIREMENTS.md`, `DATA_MODEL.md`,
  `PORTS.md` and `ARCHITECTURE.md`.
