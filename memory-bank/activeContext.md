# Active Context

**Snapshot taken:** 2026-09-14 · **Phase:** 14 complete · **Active task:** Phase 14 exit complete
This is the "what is happening right now" file. Rewrite it at the end of every
significant unit of work.

---

## 1. Focus of the current session

T14-06 Audit Search and Phase 14 are complete. Scoped authenticated Q1–Q8 requests delegate to existing
audit services and append successful reads to `access_log`; the code-split UI keeps evidence order,
completeness and integrity distinct. The frozen usability script identifies the minority position/author/
warrant and weakest evidence/recorded reason directly from visible UI facts, with working Graph,
provenance, Assumption, Replay and Audit navigation. No migration was added. Do not start Phase 15.

T14-05 Replay Controls is complete. Authenticated finalized-manifest reads and replay requests bind the
public source session to exact id/version/hash pins and delegate to existing replay services. STRICT remains
read-only and provider-free, TOLERANT preserves MATCHED/DIFFERENT ordered diffs, and LIVE requires write role
plus confirmation and exposes fresh lineage or a typed unavailable result. The code-split UI is accessible
and responsive. No persistence or migration changed. T14-06 Audit Search is next and has not started.

T14-04 Explanation Panel is complete. The authenticated read composes only persisted consensus,
recommendation, evidence/provenance, dissent, assumption, Critique, risk/uncertainty and symbolic facts. All
required sections include values or explicit empty reasons, and weakest evidence uses recorded facts only.
The code-split UI provides executive, expert, formal and machine-readable views with accessible responsive
navigation. No persistence or migration changed.

T14-03 Assumption Register is complete. The authenticated read composes all assumption, constraint and
uncertainty revisions with lifecycle, attribution, evidence, dependents, critiques, provenance, graph and
exact symbolic facts. The code-split UI distinguishes those concepts and renders missing analysis plus
`UNKNOWN → DEFER` explicitly with accessible responsive navigation. No persistence or migration changed.
T14-04 Explanation Panel is complete.

T14-02 Dissent View is complete. A new authenticated read-only endpoint composes the latest persisted
consensus explanation, selected alternative, supporting/opposing/qualifying evidence, complete Critique
handoff, exact artifact state and existing graph/provenance identities. The code-split UI presents all
minority entries and open/unresolved/disputed critiques without omission controls or composite scores, with
keyboard, screen-reader and responsive behavior. No persistence or migration changed.

T14-01 Graph View is complete. The authenticated subgraph endpoint reuses the existing transaction graph
port and traversal, translating public IDs without new persistence or migration. The code-split React view
renders authoritative server pages with labelled edge semantics, keyboard selection, textual equivalence,
responsive states and explicit loading/error/empty/pagination/truncation disclosure. Focused and full local
gates plus isolated Compose deployment pass.

Phase 14 task authority remains frozen in `docs/PHASE14_ACCEPTANCE.md`. T14-01…06 and the scripted usability
fixture are complete. Earlier-phase implementation ownership remains unchanged.

Phase 13 T13-04 is complete. `app/domain/run_manifest.py` defines canonical typed pins and the
`CREATED | FINALIZED` lifecycle; `app/application/run_manifest.py` stores exact canonical bytes by
digest and supplies finalized manifests to T13-03; `app/db/run_manifest.py` and migration
`20260914_0026` enforce one manifest/session, optional tenant-safe source lineage, forced RLS and a
single immutable finalization transition. No HTTP was added.

Phase 13 T13-03 is complete. `app/domain/replay.py` owns the closed three-mode contract and immutable
manifest reference, historical replay, step, exact implementation, execution, structured diff, first
mismatch and result values. `app/application/replay.py` verifies caller-scoped source identity, ledger
integrity and exact event history before exhaustive mode dispatch. STRICT reconstructs recorded inputs,
allows only exact-version deterministic non-external execution, reuses Phase 12 MARL `verify_bundle`, and
stops at the first mismatch. TOLERANT executes only explicitly permitted steps and records ordered
implementation/provider/model/configuration/output/status/timing-sensitive differences without claiming
VERIFIED. LIVE delegates creation and requires fresh source-linked session/manifest/event/result IDs. No
HTTP or persistence was added because T13-04 owns durable run manifests and database-backed linkage.

Phase 13 T13-01 is complete. The METRICS.md catalogue is shipped as 43 immutable `MetricDefinition`s
(EP-01…06, RR-01…07, DH-01…07, CQ-01…06, RB-01…05, CE-01…05, HO-01…04, CA-01…03) behind the new
`MetricPlugin` port in `app/ports/metrics.py`, a deterministic exact-lookup `MetricCatalogue` in
`app/domain/metrics.py`, and an application catalogue in `app/application/metrics.py`. Thirteen focused
tests transcribe METRICS.md field-by-field, cover the FR-901 profile rule and pin the Phase 12 reward
metrics (`ep-02`, `dh-03`, `dh-02`, `cq-03`, `ce-03`) at version "1". Traceability moves FR-901 and
NFR-019 to partial and FR-902 to implemented (`last_verified: local-phase13-2026-09-14`); the generated
CSV holds 104 rows with no drift. No metric engine, `metric_values` storage, API, UI, replay or
migration was added; Alembic head had stayed `20260912_0024`. The Compose stack is isolated under project
name `agora_opencode` (env-parameterized loopback ports, dedicated volumes/networks, renamed images)
so it cannot collide with the old `agora` stack.

Phase 13 T13-02 is complete. Migration `20260912_0025` adds forced-RLS, caller-append-only `access_log`
and `audit_anchors` (shared `BEFORE UPDATE OR DELETE` trigger raising sqlstate 27000, `REVOKE UPDATE,
DELETE`, composite `(workspace_id, session_id)` FK). Typed contracts live in `app/domain/audit.py`
(access-log entries, `AuditAnchor.publish` over the shared pure `_anchor_facts`, chain/append/reports);
adapters in `app/db/audit.py` (`SqlAlchemyAccessLogRepository`, `SqlAlchemyAuditAnchorRepository`,
`SqlAlchemySessionParticipantReader`) plus `ConsensusResultStore.get_round_result`; and
`app/application/audit.py` answers the eight audit questions (Q1–Q8 in AUDITABILITY.md) as typed
services. Invariants held: Q1 originates via `causation_id` (≤32 hops), Q7 strictly before
`recommendations.created_at`, `ChainVerificationService.chain_integrity` recomputes each day-head from
the ledger and uses `reasoning_ledger.verify`. Evidence: 21 focused unit tests and 7 live PostgreSQL
acceptance tests (append-only 27000, RLS 42501, FK 23503, Q7-before-acceptance, same-day conflict,
two-day chain, tamper detection); census test extended with Phase 13 tables. Docs AUDITABILITY.md 1.4
and DATA_MODEL.md §11.1 describe the implemented tables; FR-807/NFR-006 flip to implemented
(`last_verified: local-phase13-2026-09-14`). No HTTP/OpenAPI (Phase 14), nightly anchor job, or Q2/Q3/Q5 doc-fiction
events.

Phase 12 T12-01 through T12-05 are complete. Deterministic MARL observations, advisory actions, coordinator decisions,
five exact metric-linked reward components, conserved provenance credit, lifecycle persistence, canonical
two-file export, and hermetic bounded replay verification are implemented. PostgreSQL revision
`20260912_0024` is append-only and forced-RLS; the in-memory adapter has matching behavior. No training,
general metrics infrastructure, full-session `REPLAY_STRICT`, or production consensus routing was added.

T11-04 and Phase 11 are complete. The application policy maps `SAT → PROCEED`, `UNSAT → BLOCK`, and
`UNKNOWN → DEFER`, classifies timeout/incomplete/other reasons safely, and integrates only with persisted
symbolic evaluations and the consensus feasibility gate. `UNKNOWN` stays immutable and visible; a selected
unknown is capped at `CONDITIONAL_CONSENSUS` and cannot count as affirmative symbolic assurance. No
migration, API, graph, outbox, lifecycle, retry, or override
was added.

T11-03 is complete. Symbolic results now carry solver-neutral exact typed SAT witnesses or deterministic
AGORA AST-path UNSAT cores. Evaluations are persisted idempotently against exact formalisation revisions in
forced-RLS append-only PostgreSQL storage with database evidence-shape and revision/hash consistency guards.
T11-03 added no public API, graph edge, outbox event, lifecycle mutation, or violation policy.

Phase 10 T10-01 through T10-04 are complete on `phase10-reasoning-graph`: graph read traversals,
recommendation-to-source provenance, deterministic generated traceability, and workspace-wide source
impact analysis with durable exact-version reports and atomic `SOURCE_RETRACTED` outbox insertion.
T11-01 established immutable source-pinned formalisation revisions, deterministic AST validation,
human confirmation/rejection facts, derived status/enforceability, forced-RLS persistence, outbox events,
and authenticated idempotent APIs. T11-02 adds transient solver execution without changing that boundary.
Current evidence is 716 non-integration backend tests, focused symbolic/service coverage, and live
formalisation plus symbolic-evidence persistence tests, with strict static, traceability, and migration gates.

## 2. Currently active task

Phase 13 T13-01 through T13-04 are closed (metric catalogue; audit persistence + eight audit queries;
STRICT/TOLERANT/LIVE replay; durable pinned run manifests). Phase 14's contract is frozen and all six
implementation tasks remain open; T14-01 Graph View, T14-02 Dissent View and T14-03 Assumption Register are
complete, and T14-04 Explanation Panel is next.
Phase 12 T12-01 through
T12-05 and Phase 11
are closed. Phases 0–4 and 6–10 have exact-SHA
remote evidence. Phase 5 remote evidence remains tracked
independently. T7-08 and Phase 7 are complete at exact SHA
`25914b48e1c5140279720d1a4dfb66483cf744a3`; GitHub Actions run `34667037521` passed all six jobs.

## 3. Completed in this session so far

- `T13-03` Full-session replay modes implemented in `app/domain/replay.py` and
  `app/application/replay.py`, with 11 focused tests in `tests/unit/test_replay.py`. STRICT verifies
  ledger/event identity and deterministic exact-version outputs without external calls; TOLERANT reports
  explicit ordered diffs; LIVE requires fresh linked identities. Phase 12 MARL verification remains
  distinct and reusable. No migration/API; T13-04 retains manifest persistence ownership.
- `T13-02` Audit record generation and the eight audit queries implemented:
  `alembic/versions/20260912_0025_audit_tables.py`, `app/db/models/audit.py`,
  `app/domain/audit.py`, `app/db/audit.py`, `app/application/audit.py`,
  `ConsensusResultStore.get_round_result` (`app/domain/consensus.py`, `app/db/consensus.py`,
  fake in `tests/unit/test_consensus.py`), `app/composition/container.py` wiring, and
  `tests/unit/test_audit_queries.py` (21 green) plus `tests/integration/test_audit_persistence.py`
  (7 live PostgreSQL acceptance tests green against the local `agora-postgres-1` container on
  127.0.0.1:5432). Docs AUDITABILITY.md v1.4 + DATA_MODEL.md §11.1; census test
  `test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` extended with Phase 13 tables.
  Traceability FR-807/NFR-006 implemented; 104 rows no drift. Full gate green: unit 698 passed,
  PostgreSQL integration 55 passed / 8 infra-gated skipped, strict mypy 305 files, `alembic check` drift-free
  at head `20260912_0025`, links green, Compose config valid, backend image builds.
- `T13-01` Metric catalogue implemented: `app/ports/metrics.py` (`MetricPlugin` + value objects),
  `app/domain/metrics.py` (`MetricCatalogue`), `app/application/metrics.py` (43 shipped definitions),
  and `tests/unit/test_metric_catalogue.py` (13 green tests). Traceability: FR-901 partial,
  FR-902 implemented, NFR-019 partial; generated TRACEABILITY.csv at 104 rows with no drift. Also
  isolated the Compose stack under `agora_opencode` (parametrized loopback ports, dedicated
  volumes/networks, prefixed images). Full gate green: non-integration 755 passed and integration
  56 passed on the isolated stack, which surfaced and fixed two pre-existing Phase 12 alembic-chain
  defects (E-21: missing `ck_marl_episodes_status_shape` in ORM metadata; E-22: stale head literal).
  Alembic head stays `20260912_0024` with no new migration.
- `T0-01` Repository scaffold + Git initialization.
- `T0-02` `README.md`, `CHANGELOG.md`, `.gitignore`.
- `T0-03` Memory bank: `projectbrief.md`, `architecture.md`, `techContext.md`.
- `T0-04` Architecture document with all eight Mermaid diagrams.
- `T0-05` Domain/research specifications (data model, agent model, structured
  reasoning, consensus, MARL, neuro-symbolic, epistemic, RAG, memory, simulation,
  metrics, reasoning graph, agent protocols).
- `T0-06` Port contracts for all nineteen extension points (`docs/PORTS.md`).
- `T0-07` API + contract documents (`docs/API.md`, `docs/API_CONTRACTS.md`).
- `T0-08` MVP boundary and requirement classification (`docs/REQUIREMENTS.md`,
  `docs/MVP_BOUNDARY.md`).
- `T0-09` ADR-001 … ADR-020.
- `T0-10` Security, trustworthiness, operations and research documents.
- `T0-11` Consistency pass: contradiction checklist, link and fence validation.
- `T0-13` Reconciliation. The inventory showed that `T0-05 … T0-10` had been marked complete while 18
  referenced documents did not exist. All were written, ADR-017 … ADR-020 added, the six consensus
  formalisms and their template written, the `project/` state set created
  (`PLAN.md`, `TASKS.md`, `DECISIONS.md`, `ERRORS.md`, `HANDOFF.md`, `CURRENT_STATE.md`,
  `TRACEABILITY.csv`), every `Phase:` field unified with the roadmap, and `docs/README.md`,
  `CHANGELOG.md` and this file rewritten against the filesystem. Root cause recorded as `E-01`.

## 4. Phase 0 boundary (historical)

Phase 0 deliberately produced no application code before approval. After D-13 closed that gate,
Phase 1 added backend ports/adapters, migrations, Compose, authored contracts, frontend, and CI. Every
deliverable remains subject to its individual acceptance criterion.

## 5. Assumptions made in this session

1. **Project location.** Created at
   `C:\Users\baito\.cline\data\workspaces\chat\collective-reasoning-platform` because the
   shared chat workspace is not itself a project. The user selected this option
   explicitly. Move it (and `git init` there) if a different home is preferred.
2. **Codename.** "Agora" is used as a working codename only; it is not load-bearing and
   can be renamed without architectural impact.
3. **Git identity.** The initial `Author identity unknown` failure is recorded as `E-06`. Before the
   first push, repository-local identity was set to `potatosaladz <baitosabtu@gmail.com>` and the
   unpublished root history was rewritten so every commit uses that identity.
4. **Toolchain verified in T1-00.** Measured versions remain recorded in
   [techContext.md](techContext.md) §6.1; current Docker availability must still be checked per session.
5. **Temporal vs Phase 1.** The fixed decision list names Temporal as the durable
   workflow engine, but Phase 1 only requires infrastructure to be *reachable*. The
   `WorkflowEngine` port therefore has an `inmemory` adapter for Phase 1 so the API
   skeleton can run before Temporal integration in Phase 4. This is an additive
   decision, recorded as ADR-003 §Consequences, not a change to the fixed decision.
6. **Skills directory.** `.cline/skills/` was created but left empty; no project-local
   skill is needed to complete Phase 0, and the specification says to create it only if
   skills will actually be used.

## 6. Blockers

No Phase 0 approval blocker remains. The project owner approved the architecture on 2026-09-04
(D-13), satisfying the D-02 gate.

## 7. Phase 1 acceptance review

`T1-00` through `T1-11` are complete. Evidence: measured tool versions are recorded in
`techContext.md`; Ruff and mypy pass; 70 non-integration tests pass; the FastAPI factory owns adapter
lifecycle; an AST gate enforces backend package boundaries; production rejects the `env_file` secret
provider; PostgreSQL/pgvector, Redis, MinIO, and NATS pass real adapter integration tests. The root
Compose stack builds a locked, non-root backend image, runs migration and bucket init jobs, and reaches
healthy for Postgres, Redis, MinIO, NATS, and backend under `docker compose up --wait`; `/ready` reports
all selected adapters `ok`. T1-10 adds fail-closed bearer verification, explicit per-route role policy,
external-identity users, canonical memberships, and live forced-RLS proof. T1-12 through T1-15 later
closed the observability, frontend, CI, and Phase 1 exit requirements described below.

T1-12 implementation and offline acceptance are now complete: application instances own isolated
metric registries and tracer providers; `/metrics` is restricted to `ADMIN`/`OPERATOR`; RED and
database metrics use bounded labels; structured logs recursively redact secret keys and registered
literals while adding request/span context; SQLAlchemy emits query/transaction telemetry without SQL
or parameters; and lifespan cleanup removes instrumentation and shuts tracing down. The authenticated
test-only API→database integration route and in-memory span assertions are present. Ruff, mypy across
81 files, and 70 non-integration tests pass. Docker became available later in the session; the targeted
PostgreSQL trace passed, followed by all six integration tests with no skip. T1-12 is complete.

T1-13 and T1-14 are complete. `contracts/openapi.yaml` is the authored OpenAPI 3.1 source; generated
TypeScript regenerates with no diff. The React 18/Vite skeleton has strict TypeScript, hash routing,
TanStack Query, local fonts, responsive accessible views, six passing tests, and a production build.
The frontend is included in Compose as a non-root Nginx image. The expanded stack reached healthy for
all six long-running services; init jobs exited 0; `/ready` returned five `ok` components; frontend
returned 200. `.github/workflows/ci.yml` gates backend
and frontend quality, contract drift, traceability seed shape, Markdown links, empty-session replay,
the healthy Compose stack, every live adapter, and the API-to-PostgreSQL trace. The first remote run,
`33922160948`, exposed three clean-checkout/tooling defects recorded as `E-09`. Run `33923240340` passed
all six jobs after those fixes. T1-15 and Phase 1 are complete.

Phase 2 is complete. It implements the SDK-neutral LLM port, OpenAI-compatible and mock providers,
bounded structured-output repair, encrypted provider credentials, tenant-scoped registry persistence,
versioned immutable-on-use agent definitions, and mandatory token/cost/raw-artifact records. Provider SDK
imports are executable-linted to `app/adapters/`. The exit contract runs one definition through two
distinct compatible endpoints and the mock. After fixing asyncpg-incompatible multi-statement trigger DDL
and SQLAlchemy result materialization, migration `20260905_0004` passed live clean-upgrade, RLS, schema,
repository round-trip, Alembic drift, and trigger immutability checks. The healthy Compose stack passed
all 7 live integration tests; 95 non-integration tests, Ruff, mypy over 97 files, and compileall are green.

T3-01 is complete. `app.domain.reasoning` now provides immutable, closed Pydantic value objects for the
common envelope and all 14 FR-301 artifact kinds, discriminated artifact and uncertainty unions, strict
epistemic and revision invariants, deep-frozen open JSON values, RFC 8785-compatible canonical JSON, and
the exact normative content-hash preimage. Public package exports and 46 focused regression tests cover
construction, invalid combinations, schema discriminators, canonical decimal handling and byte-stable
identity.

T3-02 is complete locally. `app.domain.session_binding` provides a frozen `DRAFT` aggregate with pinned
agent-definition row/version metadata, typed objective/constraint references, strict budget bounds,
workspace/session affinity, uniqueness and UTC timestamp invariants. Proposition normalization now has a
closed `PROPOSED | VALIDATED | AMBIGUOUS` status, version-aware deterministic identity and a pure consensus
gate that rejects `AMBIGUOUS`. Focused tests pass 78/78; full offline backend tests pass 173 with 7 live
tests deselected. Ruff, format, mypy over 101 files, compileall, 12 layering tests, contracts, links,
traceability seed and diff hygiene are green.

T3-03 is complete locally. Migration `20260905_0005` and matching SQLAlchemy rows persist exactly the five
frozen session/artifact tables with composite tenant foreign keys, closed JSONB validators, deferred
reference/revision/binding checks, immutable/no-delete artifacts, indexes and forced RLS. Live tests found
and fixed a missing no-op `ELSE` in reference validation for artifact kinds without payload references.
PostgreSQL 16 clean upgrade, exact table delta, downgrade/re-upgrade, drift, decimal/timestamp validation,
tenant isolation and trigger behavior pass. Current evidence is 173 offline tests and 9 PostgreSQL
migration/persistence tests; Ruff, format, strict mypy over 103 files, compileall and offline migration SQL
generation are green.

T3-04 is complete locally. The `ReasoningGraphStore` port and SQLAlchemy adapter write immutable graph
nodes and edges inside caller-owned transactions. Migration `20260905_0006` adds tenant/session-safe
foreign keys, forced RLS, uniqueness, no-self-loop and traversal-index constraints plus deferred artifact
kind, endpoint-policy and incident-edge validation. Unit coverage exhaustively checks all 14×14×16
kind/edge combinations. PostgreSQL 16 proves atomic commit/rollback, valid and invalid edges, node updates,
RLS, clean migration, downgrade/re-upgrade and Alembic drift. Current evidence is 182 offline tests and 11
targeted PostgreSQL tests; Ruff format/lint, strict mypy over 107 files and offline migration SQL generation
are green.

T3-05 is complete locally. Migration `20260905_0007`, immutable ledger values and the SQLAlchemy ledger
adapter provide locked gapless per-session order, idempotent event IDs, canonical payload/event hashes,
ordered reads and chain verification. PostgreSQL enforces automatic heads, tenant isolation and append-only
events.

T3-06 is complete locally. A typed `ReasoningArtifactStore` and `ArtifactCommitService` compose artifact,
graph and ledger writes inside one caller-owned transaction. Initial commit writes the row/node/event;
revision locks and supersedes the active predecessor, inserts a new revision/node and `SUPERSEDES` edge;
declared parent relationships project to graph edges; withdrawal changes lifecycle only and records a
warranted event. A deferred PostgreSQL constraint failure proves all three writes roll back without
consuming ledger sequence. Current evidence is 200 offline and 16 targeted
PostgreSQL tests; Ruff, strict mypy over 115 files and migration generation/checks are green.

T3-07 is complete locally. Tenant-scoped HTTP routes expose draft-session create/read and artifact
create/read/revise/withdraw with RBAC, durable idempotent replay, `If-Match`, typed public IDs and explicit
unsupported claims. Strict JSON boundary decoding preserves domain strictness and opaque JSON. Migration
`20260905_0008` adds forced-RLS idempotency records; authored OpenAPI and generated TypeScript match. Current
evidence is 210 offline and 22 configured PostgreSQL tests, strict mypy over 123 files, frontend
lint/typecheck/6 tests/build, contract, migration, layering, link and trace gates.

T3-08 is complete locally. Accessible reasoning desk commits a complete bound draft, structured proposition
and unsupported hypothesis, then renders `UNSUPPORTED / NO EVIDENCE`. All 15 Phase 3 requirement rows now
carry implemented design/code/test evidence; checker resolves every test node. Exhaustive property suites
cover revision identity and every uncertainty type/representation pair. Evidence: 226 offline tests passed,
25 live integrations with no skips, strict mypy over 126 files, 9 frontend tests/build and all static gates.

T3-09 local exit is green. `DATA_MODEL.md` contains a machine-readable schema contract for the 10 Phase 3
tables and live acceptance compares PostgreSQL column order, type and nullability against it. All 34
anti-patterns were reviewed without a Phase 3 violation. A clean `down --volumes` plus `up --build --wait`
completed successfully; all six long-running services were healthy, init jobs exited 0, `/ready` returned
five `ok` components, frontend returned 200, Alembic was at `20260905_0008`, and all 26 integration tests
passed without skips. GitHub Actions run `33989090448` passed all six jobs for exact exit SHA
`7aaf1aabdc74a8cdba283d4524759eb1db6a0d03`, closing T3-09 and Phase 3.

During review, `InMemoryEventBus.read_from()` was found to return no replay data. It now performs
sequence-based bounded replay and has regression coverage. Real NATS integration then exposed four
SDK mismatches in the JetStream adapter: reconnect options, empty-domain handling, the replica field,
and queue/durable naming. All four are corrected and covered by unit plus integration evidence.

T4-01 is complete locally. Typed, SDK-free `WorkflowEngine` commands and diagnostic descriptions are
separate from lifecycle-only `WorkflowWorker`; Temporal SDK types and definition registration stay under
adapters. Duplicate starts resolve to the original execution, PostgreSQL remains status authority, and
draft creation remains separate from the `202` start route added in T4-02. Temporal Server 1.29.1 plus UI 2.34.0
run in Compose with a dedicated PostgreSQL 16 store. Evidence: 240 offline and 28 live tests, real worker
poll/completion, six `ok` readiness components, Ruff, mypy over 137 files and all document gates green.

T4-02 is complete locally. Migration `20260905_0009` adds a forced-RLS lifecycle projection backed by
the complete validated state graph. Row locks make each projection transition and reasoning-ledger append
atomic; exact event retries revalidate identity without duplication. The deterministic bootstrap workflow
uses immutable API-allocated event IDs and commits `SESSION_INITIALIZED` through an activity. The separate
idempotent `202` start endpoint preserves the original Temporal execution
across replay and API attachment rollback. Evidence: 252 offline tests, strict mypy over 149 files, Ruff,
frontend contract/lint/typecheck/10 tests/build, migration drift checks, and focused live PostgreSQL and
Temporal tests.

T4-03 is complete. `run_agent_turn` accepts and returns strict protocol-versioned contracts,
loads the exact prompt bytes pinned by each agent definition, rejects digest/UTF-8/schema/authority/turn
violations, records completed provider usage, and closes its turn-scoped provider on every path. A
process-lived activity retains no `AsyncSession`; its registry facade opens a fresh workspace-bound
transaction per operation. The bootstrap now commits `ROUND_STARTED` after `SESSION_INITIALIZED`, leaving
PostgreSQL at `RUNNING` round 1 before waiting. Evidence: 274 offline tests, strict mypy over 153 files,
Ruff, 22 focused agent tests, focused live PostgreSQL/Temporal proofs, and all six jobs in exact-SHA CI run
`34005422198`. Retrieval, simulation and symbolic ports remain future-phase work and must use the same
activity boundary.

T4-04 is complete. Authenticated pause, resume, cancel, deprecated terminate compatibility and typed human
directives enter Temporal as strict retry-stable signal envelopes. The deterministic workflow serially
interprets them, deduplicates command identities and delegates every accepted transition to an atomic
PostgreSQL lifecycle/ledger activity. Validation included 30 focused live integration tests with 287
deselected. Commit `714f08b7c349a6e6b4d5b11b06299682af3ac76f` is pushed; exact-SHA GitHub Actions run
`34011486812` passed all six jobs.

T4-05 is complete locally. State commits use a 15-second attempt timeout, 300-second schedule budget and ten
attempts; agent turns use 120/300 seconds, three attempts and a 30-second heartbeat timeout. Every retry
reuses a stable caller-derived activity/call identity. Permanent and transient failures are translated at
the Temporal boundary without raw exception text. Final bootstrap/control failures commit a preallocated,
redacted `ACTIVITY_DEAD_LETTERED` event with an atomic transition to `FAILED`; PostgreSQL lifecycle plus the
hash-chained ledger remains checkpoint authority. PostgreSQL call accounting accepts exact replay and
rejects conflicting identity reuse. Local evidence: 73 focused tests, 303 non-integration tests, 30 live
integration tests, Ruff format/lint, strict mypy over 162 files, 86 Markdown links, and clean diff check.

T4-06 through T4-08 are complete locally. PostgreSQL ledger appends are captured as post-commit publication
candidates; exact activity replay creates no second candidate. NATS carries strict reference-only event
envelopes on `session.{workspace}.{session}.committed` and only wakes `RealtimeGateway`; every SSE emission
is reread from PostgreSQL by `ledger_seq`, with `Last-Event-ID` precedence and heartbeat catch-up if transport
publication is lost. Browser recovery stores a minimal active-session pointer, reloads the authoritative
terminal projection, resumes the ledger timeline, and deduplicates sequence replay. Live tests prove real
NATS wake-up/SSE delivery and real Temporal worker replacement after simulated post-commit acknowledgement
loss, with stable event identity and one committed effect.

Phase 5 T5-00 through T5-07 are complete locally. The eight required formats parse into deterministic,
structure-aware chunks. Migration `20260906_0010` makes PostgreSQL authoritative for namespaces, typed
grants, sources, parsed documents and chunks; all five tables use forced RLS and composite workspace
references. Provenance identity and physical rows are database-protected while audited lifecycle/ACL
fields remain mutable. Migration `20260906_0011` adds the forced-RLS PostgreSQL ingestion checkpoint.
Reference-only Temporal input resolves content-addressed object bytes by expected digest; exact retries
reuse immutable operation/request identity; acquire/parse/embed/index states and safe failure taxonomy are
durable. Unsupported media fails explicitly after digest verification, and parsed text remains available
while embedding/index lag is visible. Current evidence is 342 offline tests, 53 focused ingestion/
knowledge/object/layering tests, 2 focused live PostgreSQL tests, Ruff/format over 194 files, strict mypy
over 181 files, and green lock/document/compile gates. Migration `20260906_0012` extends the replaceable
`vector_items` index with UUID-backed namespace/chunk/document/source references. Typed writes resolve
the authoritative hash/provenance chain and serialize model/version pinning with sorted namespace advisory
locks. Reads reject index identity mismatch, stale hashes and non-ready sources/documents, with deterministic
chunk-UUID tie ordering. Legacy operations cannot read, delete, or overwrite typed rows.
Current T5-04 evidence is 345 offline tests (35 integration tests deselected), 6 authoritative live
PostgreSQL tests in 15.03s, and clean disposable-container teardown. Ruff/format, strict mypy over 182
files, migration/compile/layering/contracts/links/traceability gates pass. Frontend lint, typecheck,
production build, 19 tests and generated OpenAPI contract verification pass; `types.ts` has no diff.
Migration `20260906_0013` adds an immutable generated lexical search vector and GIN index. Retrieval uses
typed explicit namespaces/subjects, active grants and chunk ACL predicates inside materialized pre-score
relations for both arms. Deterministic RRF records lexical, vector and fused scores; strict reranker output
validation prevents provenance mutation. Vector outage/index mismatch and reranker failure retain candidates
with explicit degradation. T5-05 evidence is 352 offline tests, 2 focused live PostgreSQL tests, Ruff clean,
strict mypy over 187 files, no Alembic drift and successful downgrade/re-upgrade.
Migration `20260906_0015` adds append-only forced-RLS citation snapshots and source-retraction facts.
Manual attachment validates human attribution, the evidence/claim relationship, exact stored source
reference and complete ready knowledge chain before append. Hits preserve exact IDs, ordered span, hashes,
source/document/retrieval timestamps and trust. Retraction is irreversible and reason-required; it excludes
future retrieval but preserves old citation resolution and evidence/claim dependency records. T5-07 evidence
is 359 offline tests, 4 focused live PostgreSQL tests in 8.14s, strict mypy over 196 files, green inherited
gates and successful `0015 → 0014 → head` with no drift.
Migration `20260906_0016` adds append-only forced-RLS semantic entries, validated promotions, evidence sets
and monotonic stale/archive lifecycle facts. Four memory scopes are explicit; non-semantic tiers retain
their existing authorities. Direct semantic writes and raw SQL bypass fail. PostgreSQL validates active
humans, source/evidence identity, namespace, caveats, review and supersession while preserving every row.
T5-08 evidence is 363 offline tests, one focused live PostgreSQL test, strict mypy over 201 files, green
inherited gates and successful `0016 → 0015 → head` with no drift.

T6-06 is complete locally. A batch preflight rejects unsealed or mixed session/round/phase round-one
`ASSESS` turns before dispatch. A fixed queue-consuming worker fleet bounds proposal-only concurrency, indexed result
slots make output order independent of completion order, and per-turn deadlines produce typed
`ABSTAIN`/`TURN_TIMEOUT` outcomes without hiding runtime failures or cancellation. Worker inputs expose no
persistence, transition or peer-agent channel. Evidence is 7 focused and 442 offline tests; the default
suite passes 442 with 41 service-dependent integrations skipped; Ruff format/lint, strict mypy, contracts,
traceability, links and whitespace gates are clean. T6-06 is published at exact SHA
`cd1034725d9f2404126861edf4cbc5d34564d672`; local and remote matched before T6-07 work began.

T6-07 is complete locally. Frozen orchestrator proposals contain only decomposition, routing or next-phase
recommendations; mutation/transition fields and actions fail strict validation. Coordinator-only policy
checks every identity pin, routing eligibility and immediate fixed phase order, then appends one stable
accepted/rejected `POLICY` event with orchestrator attribution, rule/version and `applied: false`. It depends
only on `ReasoningLedger`, does not invoke T6-02 semantics and does not extend Temporal. Evidence is 22
focused and 464 offline tests with 41 integrations deselected; 225-file Ruff format/lint and strict mypy,
contracts, 54-row traceability, 88-link and whitespace gates are clean. No database change was required.

T6-08 is complete locally. Append-only forced-RLS membership deltas are effective by round and replay in
ledger order; membership writes lock the lifecycle row to exclude round-start races. Context and retrieval
reject definitions outside effective membership, including superseded replacements. Durable session and
definition token/USD totals bracket bounded dispatch and a reached ceiling records one explicit
`BUDGET_EXHAUSTED` failure. A four-worker 20-agent fixture commits 20 claims in pinned order and verifies
full attribution in artifacts and completion events. Evidence is 21 focused and 474 offline tests with 42
service-backed skips, clean Ruff and strict mypy over 229 files, offline migration SQL, contracts,
traceability, links and whitespace. The complete 42-test live Compose suite later passed during T6-09.

T6-09 and Phase 6 are complete. Cross-platform prompt and generated-client EOL gates are stable; 69 focused,
479 offline and 42 live backend tests pass; the complete Node 22 frontend gate passes 22 tests. Final
exact-SHA GitHub Actions run `34148649503` passed all six jobs for
`6d671acffe7abd3e5b587042457f300e0c442adc`, including the guaranteed XOR tamper-test fix.

T7-00 is complete. The frozen contract corrects non-normative roadmap aliases, composes existing immutable
artifact/graph/ledger paths, maps all seven responses to additive Critique heads, and keeps simulation,
consensus, traversal, metrics and UI in later phases. No runtime code or schema changed.

T7-01 through T7-04 are complete locally. Frozen assignment and response values enforce exact FR-501 and
FR-503 vocabulary. A shipped Critic with a literal LF prompt digest runs through the existing activity and
attacks every artifact kind. Coordinator dispatch reuses authorized context, bounded workers and durable
budgets; timeout is not inactivity, and `CRITIC_INACTIVE` requires three consecutive completed empty rounds.
The existing proposal transaction now requires exact assignment and derives one retry-stable, type/severity-
qualified `ATTACKS` edge for each Critique. Evidence is 86 focused tests and 565 offline tests with 42 live tests deselected; Ruff format/lint,
strict mypy over 238 files, contracts, 58-row traceability, 89 links and whitespace are green.

T7-05 and T7-06 are complete locally. Provider/accounting metadata now survives activity-backed strategy
and bounded dispatch boundaries; deterministic strategies receive an explicit metadata-free wrapper.
Append-only, forced-RLS response requests/results preserve exact retry identity and all seven explicit
outcomes. A sealed author-specific response command locks and validates current Critique/target heads,
ownership, visibility, warrants and revision references before appending the Critique successor. `REVISE`
also appends a same-kind/logical-id/owner target successor with coordinator-derived `SUPERSEDES`,
`RESPONDS_TO`, and Critique `ATTACKS` relationships. Evidence intent remains explicitly requested and
simulation remains deferred. Validation is 23 response-specific and 589 offline tests, clean Ruff and strict
mypy over 242 app/test files, one Alembic head, and successful offline SQL
generation. Two focused tests passed against a disposable PostgreSQL 16/pgvector database, proving the
widened graph matrix plus commit/rollback, exact retry, forced RLS and append-only response persistence;
`0019 → 0018 → head` and `alembic check` also pass.
- Completed T7-07: a single caller-transaction coordinator now runs dedicated Critic and optional peer
  `CRITIQUE` dispatch before sealed author-specific `REVISE` dispatch. Critic commits remain ahead of peer
  commits in pinned order; responses commit by target artifact and responder definition. Runtime-generated
  response IDs, complete execution attribution semantics, duplicate response/head rejection, and explicit
  ordered timeout abstention events are enforced. All Critic/peer outputs and all REVISE outputs validate before their
  respective phase's first write. The explanation reader returns every latest Critique head in stable
  ledger/id order with no omit path and explicit empty reasons. An unsupported Claim is represented by
  `EVIDENCE_GAP`; the deprecated `UNSUPPORTED_CLAIM` alias still fails closed. Evidence: 49 focused tests,
  607 offline tests, one live PostgreSQL handoff test, compileall, and clean Ruff/format/strict mypy over 248
  app/test files. No public HTTP API changed.
- Completed T7-08 and Phase 7: 82 focused and 677 offline tests pass; a clean disposable Compose stack
  passed all 52 live integration tests, Alembic head `20260911_0021`, and migration drift checks. Backend,
  frontend, contracts, generated traceability, links, whitespace, and anti-pattern review are green. During
  exact-SHA CI, Docker Hub removed the pinned MinIO repositories; Compose now uses the same exact manifests
  through Quay. GitHub Actions run `34667037521` passed all six jobs at exact SHA
  `25914b48e1c5140279720d1a4dfb66483cf744a3`.

## 8. Risks noticed during this session

| Risk | Impact | Mitigation now recorded |
| --- | --- | --- |
| Scope gravity — the spec can produce an unbuildable "everything at once" system | High | Hard MVP boundary + phase gates + stop-after-Phase-0 rule |
| Consensus formalism drifting into a single hard-coded score | High | `ConsensusStrategy` port + mandatory per-plugin formalism docs + feasibility-before-ranking rule |
| Traceability becoming an afterthought bolted onto Phase 10 | High | Provenance fields in every artifact envelope from Phase 3; graph write path in Phase 3/4, not retrofitted |
| LLM nondeterminism undermining "reproducibility" claims | Medium | Four distinct replay modes; manifest records what cannot be reproduced |
| Stateful HA mislabelling | Medium | ADR-020 separates local single-instance from production HA architecture |
| Documentation rot (docs diverging from code, and from the task register) | High | Happened once in Phase 0 (`E-01`); prevention is TS-06 link/file-existence check and "observe, then tick" |
| Windows host / POSIX container assumptions mismatch | Low-Medium | Phase 1 verifies toolchain; all container images Linux-based |

## 9. Next recommended action

Phase 13 T13-01 through T13-03 are complete: the METRICS.md catalogue ships as 43 immutable
`MetricDefinition`s with an exact-lookup `MetricCatalogue` and 13 green tests, and migration
`20260912_0025` plus `app/application/audit.py` answer the eight audit questions with 21 unit + 7 live
PostgreSQL tests, FR-807/NFR-006 implemented in the generated 104-row traceability. T13-03 adds
STRICT/TOLERANT/LIVE replay orchestration and 11 focused tests. T13-04 (run manifests with pinning) is
next and must be verified from [project/TASKS.md](../project/TASKS.md) before starting; do not begin it
automatically. Phase 13 audit
HTTP (Phase 14), the nightly anchor job, and external WORM anchor storage remain deferred. Keep Phase 5
commit `45253c8b91c103e9632554de8b31d55a5a5281c4` remote evidence tracked independently.

## 10. How to resume this project cold

```bash
git status && git log --oneline -10
cat project/CURRENT_STATE.md
cat project/HANDOFF.md
```
Then follow the recovery protocol in [../README.md](../README.md#recovery-protocol-mandatory-every-session).
