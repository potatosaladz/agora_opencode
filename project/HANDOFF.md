# Handoff

**For:** whoever continues this work, probably with no memory of the session that produced it.
**As of:** 2026-09-15 · **Phase:** 15 contract frozen · **Active task:** T15-00 complete

## Read these five, in this order

| # | File | Why |
| --- | --- | --- |
| 1 | [../README.md](../README.md) | what the project is, the discipline, the roadmap |
| 2 | [CURRENT_STATE.md](CURRENT_STATE.md) | where things actually stand, and what is not done |
| 3 | [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) | the three invariants and the authority split — everything else follows from them |
| 4 | [../docs/MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md) | what is refused, and the protocol for changing that |
| 5 | [ERRORS.md](ERRORS.md) | the five mistakes already made, so they are not made twice |

Then, if implementing: [../docs/PORTS.md](../docs/PORTS.md) →
[../docs/DATA_MODEL.md](../docs/DATA_MODEL.md) →
[../docs/API_CONTRACTS.md](../docs/API_CONTRACTS.md) →
[../docs/TESTING.md](../docs/TESTING.md).

## The three sentences that matter

1. The **coordinator** owns authority; an LLM may propose a next step but may never decide that a
   session has reached consensus ([ADR-013](../docs/adr/ADR-013-coordinator-vs-orchestrator-authority.md)).
2. **Feasibility precedes preference**: an alternative that violates a hard constraint is removed before
   anything is ranked, and the removal is shown with its unsat core
   ([ADR-014](../docs/adr/ADR-014-pluggable-consensus-feasibility-gate.md)).
3. **Absence of evidence is a result**: `INSUFFICIENT_EVIDENCE` is an outcome, not a zero, and no
   composite score is ever the headline ([../docs/METRICS.md](../docs/METRICS.md)).

A change that breaks any of these is not a refactor. It is a different project.

## Immediate next action

Read [PHASE15_ACCEPTANCE.md](../docs/PHASE15_ACCEPTANCE.md) and ADR-021. T15-00 is complete; implement only
T15-01 Gateway as Sole Tool Egress when authorized. It owns the stateless Streamable HTTP gateway, frozen
typed port, deterministic read-only fixture tool, lifecycle/error/cancel/restart behavior and network bypass
proof. It does not own registry persistence, production allowlists, approvals/limits/audit, quarantine or
SSRF controls. T15-02…04 remain open. Do not start T15-02 or Phase 16.

Read [PHASE14_ACCEPTANCE.md](../docs/PHASE14_ACCEPTANCE.md) before continuing Phase 14. T14-01 is complete.
`POST /api/v1/graph/subgraph` delegates to the existing graph store with public-ID,
scope, radius/filter/page/cursor validation, and the code-split Graph View renders its authoritative pages
with accessible visual/textual equivalents and responsive interaction. It added no migration, persistence,
repository or traversal. The Phase 14 usability fixture remains unpassed.

T14-02 is now complete. The authenticated dissent read composes existing persisted consensus explanations,
Critique handoff, artifacts, provenance and graph-node identities; the code-split UI exposes selected
context, evidence relations, every minority entry and unresolved disagreement without filtering or scores.
No migration or persistence was added.

T14-03 is complete. The authenticated register composes existing assumptions, constraints, uncertainties,
evidence, graph dependencies, Critique handoff, recommendations and exact symbolic facts without new state.
The code-split UI preserves lifecycle and `UNKNOWN → DEFER`, and links to Graph, provenance and Dissent
views.

T14-04 is complete. Its authenticated read composes persisted consensus/recommendation explanations,
evidence/provenance, T14-02 dissent, T14-03 assumptions, Critique handoff, risk/uncertainty and symbolic
facts without recomputation or generated prose. The code-split panel provides executive, expert, formal and
machine-readable views.

T14-05 is complete. Authenticated finalized-manifest reads and exact source/manifest-bound replay requests
delegate to existing replay services. STRICT remains provider-free verification, TOLERANT preserves ordered
MATCHED/DIFFERENT semantics, and LIVE requires write authorization plus confirmation and exposes fresh
lineage or a typed unavailable result. The code-split UI is accessible and responsive; no migration or
persistence was added.

T14-06 and Phase 14 are complete. Scoped authenticated Q1–Q8 Audit Search delegates to the existing audit
services, records successful reads, and presents ordered evidence with independent completeness/integrity.
The frozen usability script passes for visible minority and weakest-evidence discovery plus required
navigation. No migration or replacement audit subsystem was added.

Phase 13 T13-01 through T13-04 are complete. T13-02 ships the Phase 13 audit substrate: migration
`20260912_0025` adds forced-RLS, caller-append-only `access_log` and `audit_anchors`, and
`app/application/audit.py` answers the eight audit questions (Q1–Q8 in
[AUDITABILITY.md](../docs/AUDITABILITY.md)) as typed services over `app/domain/audit.py`,
`app/db/audit.py`, and `ConsensusResultStore.get_round_result`. Appended append-only (sqlstate
27000), RLS 42501 isolation, FK 23503, Q7-before-acceptance, same-day anchor conflict, two-day chain
verification and tamper detection are proven by 21 focused unit tests and 7 live PostgreSQL tests;
`alembic check` is drift-free at head `20260912_0025`. By design still absent: any HTTP/OpenAPI for
the audit queries (Phase 14), the nightly anchor job, WORM external anchor storage, and the Q2/Q3/Q5
doc-fiction events (`STATUS_CHANGED`, `CONTEXT_ASSEMBLED`, `ROUND_TERMINATED`/`CONSENSUS_REACHED`/
`HUMAN_TERMINATED`) — those questions are answered from real durable facts instead. T13-03 adds the
closed STRICT/TOLERANT/LIVE contracts and `SessionReplayService`: STRICT is historical deterministic
verification with exact versions and no external calls; TOLERANT is controlled re-execution with an
ordered structured diff and no false VERIFIED claim; LIVE is a source-linked new execution whose
session/manifest/event/result identities must all be fresh. The service verifies ledger integrity and
exact event history first and reuses Phase 12 MARL `verify_bundle()` without changing it. No HTTP or
persistence was added in T13-03. T13-04 now adds canonical `RunManifestDocument` pins, content-addressed
object bytes, and migration `20260914_0026` with one forced-RLS `reproducibility_manifests` row per
session, optional tenant-safe source lineage, and exactly one immutable `CREATED → FINALIZED`
transition. `PersistedReplaySource` resolves only exact finalized id/version/hash pins for T13-03. No
HTTP endpoint was added. Phase 14 task authority is now frozen; implementation has not started.

Phase 11 is complete through T11-04. `SymbolicUnknownPolicy` keeps solver facts separate from
application action: `SAT → PROCEED`, `UNSAT → BLOCK`, `UNKNOWN → DEFER`. The persisted evaluation remains
immutable. Consensus is the only downstream consumer; a selected unresolved alternative is capped at
`CONDITIONAL_CONSENSUS` and is never symbolically assured. No migration, API, graph, outbox, lifecycle,
retry, or human override was added.
Phase 12 (MARL environment) is the next authoritative phase; do not start it without authorization.

T11-03 is complete. `SymbolicReasoner[FormalizationRevision]` now returns solver-neutral exact typed SAT
witnesses or deterministic AGORA AST-path UNSAT cores. `SymbolicEvaluationService` and the PostgreSQL
repository persist immutable evidence against the exact revision/hash and solver configuration with
idempotent replay, forced RLS, and append-only enforcement. T11-03 added no API, graph edge, outbox event,
lifecycle mutation, or policy verdict.

T11-01 remains complete. The validated formalisation boundary is unchanged:
`formalizations`, `formalization_validations`, and `formalization_decisions` are immutable PostgreSQL
authority, while `validation_status` and `enforceable` are derived. T11-01 performs no solver execution.
T11-02 is complete; do not conflate syntactic validity with satisfiability or truth.
T11-01 acceptance passed 7 domain/API tests and one live PostgreSQL test. T11-02 focused acceptance adds
26 symbolic tests; the current non-integration suite passes 710 tests with 53 deselected. Ruff, format, strict
mypy, compileall, generated-client drift, frontend typecheck and 22 Vitest tests, traceability, links, one
Alembic head, live migration drift, offline SQL, and diff checks are green.

Phase 0 was approved by the project owner on 2026-09-04 and recorded as D-13; T0-12 and the D-02 gate
are complete. T1-00 through T1-11 are closed. The backend has enforced import boundaries,
async SQLAlchemy/Alembic with forced tenant RLS, pgvector, and Redis/MinIO/NATS adapters with real
integration proofs. T1-09 added a locked, non-root backend image and root `docker-compose.yml` with
Postgres, Redis, MinIO, NATS, migration and bucket-init jobs, and health-gated backend startup. A clean
`docker compose up --wait` exited 0; all long-running services were healthy, init jobs exited 0,
`/ready` reported every adapter `ok`, Alembic was at head, and all five integration tests passed against
the stack. T1-10 added fail-closed bearer verification, four canonical workspace roles, explicit
route policies, external-identity users, and forced-RLS memberships; its disposable PostgreSQL proof
passed. T1-12 now has app-scoped tracing/metrics, authenticated `/metrics`, recursively redacted logs,
SQLAlchemy spans/metrics, lifecycle tests, and an authenticated test-only API→database route. T1-13
adds the authored OpenAPI contract, generated TypeScript client, React/Vite/TanStack Query operational
UI, tests, and non-root image. T1-14 adds gating GitHub Actions for quality, contracts, traceability,
links, replay, and all live integrations. Ruff, mypy across 81 source files, 70 non-integration tests,
six frontend tests, strict typecheck, and frontend production build are green. Docker became available;
the targeted observability integration passed, then all six integration tests passed with no skip. The
expanded stack reached healthy for all six long-running services, `/ready` returned five `ok` components,
and frontend returned 200. T1-12 is complete. GitHub Actions run `33923240340` passed every required
job after the E-09 clean-checkout fixes. T1-15 and Phase 1 are complete.

Phase 2 adds provider-neutral LLM contracts, OpenAI-compatible and deterministic mock adapters,
structured-output repair, raw trace persistence, per-call usage/cost accounting, AES-256-GCM envelope
encryption, and a tenant-scoped durable agent registry with versioning. Migration `20260905_0004` is the
single Alembic head. A live clean migration and repository round-trip proved forced RLS, bytea credential
storage, composite tenant foreign keys, version supersession, and database-trigger immutability. The
same agent definition produced three traceable records through two distinct compatible endpoints and the
mock. Current gates: Ruff format/lint, mypy over 97 files, compileall, 95 offline tests, and all 7 live
integration tests green. Commit `5034e7b` is pushed; GitHub Actions run
[`33952091288`](https://github.com/potatosaladz/agora/actions/runs/33952091288) passed for that SHA.

Phase 3 is decomposed into T3-00…T3-09. T3-00 froze the contract. T3-01/T3-02 added strict immutable values
for all 14 artifact kinds and the separate immutable `DRAFT` session aggregate. T3-03 added migration
`20260905_0005` plus matching SQLAlchemy rows for the five session/artifact tables. T3-04 added the
`ReasoningGraphStore` port, graph rows, caller-transaction-scoped adapter and migration `20260905_0006`.
PostgreSQL enforces closed artifact and edge kinds, tenant/session-safe foreign keys, deferred artifact-kind
and endpoint resolution, the complete endpoint matrix, no self-loops, unique triples, incident-edge-safe
node updates and forced RLS. Clean migration, downgrade/re-upgrade, Alembic drift, atomic commit/rollback
and tenant isolation are live-tested. Current evidence is 182 offline tests and 11 targeted PostgreSQL
tests. T3-05 adds migration `20260905_0007`, immutable ledger values, SQLAlchemy rows and a
caller-transaction-scoped append/read/verify adapter. Locked heads allocate gapless committed order;
idempotent retries, canonical hashes, rollback, verification/tamper detection, append-only triggers and
forced RLS are covered. Current evidence is 192 offline tests, 15 PostgreSQL reasoning-persistence tests,
Ruff, strict mypy over 111 files and migration checks. T3-06 adds the typed artifact store and atomic
commit/revise/withdraw application service over the existing graph and ledger ports. Revision locks and
supersedes the active predecessor, inserts a new typed row/node and `SUPERSEDES` edge, while withdrawal
changes lifecycle only and appends a warranted event. Declared parent relationships become graph edges in
the same transaction. A deferred PostgreSQL failure proves all three writes roll back. Current evidence is
200 offline tests, 16 PostgreSQL reasoning-persistence tests, Ruff, strict mypy over 115
files and migration checks. T3-07 adds tenant-scoped draft-session and artifact lifecycle HTTP routes,
durable forced-RLS idempotency, `If-Match`, public IDs, authored OpenAPI/generated TypeScript and live atomic
HTTP-to-PostgreSQL proof. Current evidence is 210 offline and 22 configured PostgreSQL tests, strict mypy over
123 files, frontend lint/typecheck/6 tests/build and contract drift gates. T3-08 adds accessible FR-101 walkthrough,
explicit unsupported-claim rendering, exhaustive property tests and implemented trace rows for all 15 Phase 3
requirements. Current evidence: 226 offline tests passed, 25 live integrations without skips, 9 frontend
tests and strict mypy over 126 files. T3-09 adds an executable 10-table schema/document comparison and
completes the all-34 anti-pattern review. A clean volume-free Compose rebuild is healthy, `/ready` has five
`ok` components, UI returns 200, Alembic is at `20260905_0008` (`head`), and all 26 live integrations pass
without skips. GitHub Actions run
[`33989090448`](https://github.com/potatosaladz/agora/actions/runs/33989090448) passed all six jobs for exact
exit SHA `7aaf1aabdc74a8cdba283d4524759eb1db6a0d03`; T3-09 and Phase 3 are complete. T4-01 is complete
locally: typed client/worker ports, in-memory and Temporal adapters, pinned Temporal Compose services,
six-component readiness and real start/duplicate/describe/worker-completion proofs are green. T4-02 adds
the full validated lifecycle graph, forced-RLS PostgreSQL projection, atomic ledger transitions,
deterministic bootstrap worker and idempotent `202` start. Evidence is 252 offline tests, focused live
PostgreSQL/Temporal proofs, Ruff/mypy/frontend/contracts, and migration drift checks. T4-03 adds strict
typed agent-turn/proposal contracts, sealed prompt hash verification, a process-safe tenant transaction
facade, turn-scoped provider cleanup and production `run_agent_turn` registration. Bootstrap now reaches
persisted `RUNNING` round 1 before waiting. Current evidence is 274 offline tests, strict mypy over 153
files, Ruff, 22 focused agent tests, and focused live PostgreSQL/Temporal proofs. GitHub Actions run
[`34005422198`](https://github.com/potatosaladz/agora/actions/runs/34005422198) passed all six jobs for exact
implementation SHA `8cc835f4029aca5964c388513aeaba1fc02af4d3`. T4-04 adds authenticated, idempotent
pause/resume/cancel/legacy-terminate and typed human-input signals, deterministic workflow interpretation,
and atomic PostgreSQL-authoritative lifecycle/ledger commits. Its 30 focused live integration tests passed
with 287 deselected. Commit `714f08b7c349a6e6b4d5b11b06299682af3ac76f` is pushed; GitHub Actions run
[`34011486812`](https://github.com/potatosaladz/agora/actions/runs/34011486812) passed all six exact-SHA jobs.
T4-05 through T4-08 are complete. Final Phase 4 SHA
`d9efa51cbb2fee52b6d32bf47e3346b31d7d392b` passed all six jobs in GitHub Actions run
[`34031523362`](https://github.com/potatosaladz/agora/actions/runs/34031523362). T5-00 freezes Phase 5
contracts and detailed T5-01…09 acceptance criteria. T5-01 adds deterministic structure-aware parsers
and chunking for all eight required formats. T5-02 adds migration `20260906_0010`, forced-RLS knowledge
provenance tables, composite tenant references, immutable identities and transaction-scoped repositories.
T5-03 adds migration `20260906_0011`, reference-only bounded ingestion activity, content-addressed digest
verification, exact-retry identity and durable independent acquire/parse/embed/index checkpoints with safe
failures. T5-04 adds migration `20260906_0012`, UUID-backed `vector_items`, authoritative hash/provenance
validation, deadlock-safe embedding model/version pinning, ready-state and stale-data exclusion, isolated
legacy compatibility, deterministic ordering and runtime-role RLS/index proof. T5-05 adds migration
`20260906_0013`, indexed lexical search, grant/ACL predicates inside pre-score materialized relations,
deterministic RRF with recorded arm scores, a strict reranker port and explicit vector/reranker degradation.
Final T5-05 evidence is 352 offline tests with 36 integration tests deselected, 2 focused live PostgreSQL
tests, Ruff clean, strict mypy over 187 files, no migration drift and successful downgrade/re-upgrade.
T5-06 adds stable retrieval attempt/trace IDs, explicit human/agent identity, trusted PostgreSQL subject
validation and one materialized relation for all six tier contexts before scoring. Agent session access
requires `session_agents`; forged subjects deny scope. Migration `20260906_0014` adds append-only forced-RLS
`retrieval_attempts`; allowed/denied records store hashes, IDs, census, outcome, versions and degradation but
never query/chunk text, and audit failure fails retrieval closed. Final evidence is 354 offline tests with 37
integrations deselected, 3 focused live PostgreSQL tests, Ruff clean, strict mypy over 190 files, no Alembic
drift and successful `0014 → 0013 → head`.
T5-07 adds migration `20260906_0015` with append-only forced-RLS citation snapshots and retraction facts.
PostgreSQL resolves human attribution, evidence/claim identity and exact locator/hashes/timestamps/trust
against the full ready knowledge chain. Retraction is irreversible and reason-required; future retrieval
excludes the source while old citations and evidence/claim dependency records remain readable. Final
evidence: 359 offline tests, 4 focused live PostgreSQL tests in 8.14s, strict mypy over 196 files, green
inherited gates, no Alembic drift and successful `0015 → 0014 → head`.
T5-08 adds migration `20260906_0016`, explicit four-tier scopes, a frozen-port-compatible PostgreSQL
provider and append-only forced-RLS semantic entry/promotion/evidence/lifecycle facts. Direct semantic
writes and raw unvalidated SQL fail; active human validator, non-empty evidence/caveats, source snapshot,
review and supersession are database-validated. Stale/archive history never deletes authority. Final
evidence: 363 offline tests, one focused live PostgreSQL test, strict mypy over 201 files, green inherited
gates, no Alembic drift and successful `0016 → 0015 → head`.
T5-09 local exit candidate adds versioned synthetic retrieval corpus/evaluator and migration
`20260906_0017` for durable `RAG_FAILED` audit outcomes. Final local evidence is 370 offline and 40 live
Compose-backed tests, strict typing, format/lint, frontend 19 tests/build, contracts, traceability, links
and whitespace.
Phase 5 commit is `45253c8b91c103e9632554de8b31d55a5a5281c4`; push only when explicitly
authorized, then capture exact-SHA CI from branch `phase5-rag` in
`C:\Users\baito\.cline\data\workspaces\chat\agora-phase5-rag`.
Phase 6 uses isolated branch `phase6-domain-reasoning`. T6-00 through T6-09 are complete. Final commit
`6d671acffe7abd3e5b587042457f300e0c442adc` passed all six jobs in GitHub Actions run `34148649503`. Read
[../docs/PHASE6_ACCEPTANCE.md](../docs/PHASE6_ACCEPTANCE.md) first. T6-06 is published at exact SHA
`cd1034725d9f2404126861edf4cbc5d34564d672` with local and remote matching before T6-07 work began.
T6-07 adds strict inert `DECOMPOSE`, `ROUTE`, and `ADVANCE_PHASE` recommendations. Coordinator policy pins
all identities, checks eligible route targets and immediate fixed phase order, then records exactly one
retry-stable `POLICY` accepted/rejected event with `applied: false`; it has no state-mutation dependency and
does not extend Temporal. Validation is 22 focused and 464 offline tests with 41 service-dependent tests
deselected; Ruff format/lint, strict mypy over 225 files, contracts, traceability, links and whitespace are
clean. No database schema or live adapter changed, and `TEST_DATABASE_URL` remains unavailable.
T6-08 adds migration `20260907_0018`, append-only ledger-ordered effective membership, lifecycle-lock
serialization against round start, effective-round context/retrieval authorization, strict durable
session/definition token and USD checks, and explicit one-time `BUDGET_EXHAUSTED` failure. Its four-worker
20-agent fixture commits 20 claims in pinned order and verifies complete event/artifact attribution.
Validation is 21 focused and 474 offline tests with 42 service-backed tests skipped; Ruff format/lint,
strict mypy over 229 files, offline migration SQL, contracts, traceability, links and whitespace are clean.
T6-09 then passed all 42 live Compose-backed tests, the complete Node 22 frontend gate with 22 tests, and
the inherited local gates before the exact-SHA hosted run above. The final SHA includes only the guaranteed
XOR tamper-test fix and synchronized error records; production encryption is unchanged.

Phase 7 uses `phase7-critic-revision`. T7-00 is complete: read
[../docs/PHASE7_ACCEPTANCE.md](../docs/PHASE7_ACCEPTANCE.md) before implementation. It freezes exact FR-501
names, Critic-only output, all-artifact active-target checks, seven author-bound responses, immutable
Critique resolution versions, targeted revisions with `SUPERSEDES`/`RESPONDS_TO`, deferred Phase 8
simulation requests, stable ordering and a complete internal explanation handoff. No runtime/schema change
was made during reconciliation. T7-01 through T7-06 are complete locally: strict assignment/response
contracts, one digest-pinned Critic, budgeted authorized dispatch with the three-empty-round inactivity
rule, atomic attacks, all seven author responses and same-kind target revisions are implemented. Response
request/result rows are append-only and forced-RLS; exact retry identity contains full runtime attribution.
The coordinator locks both heads and derives `SUPERSEDES`, `RESPONDS_TO`, and Critique `ATTACKS` lineage.
Evidence is 23 response-specific and 589 offline tests, with clean Ruff and strict mypy over all 242 app/test
files. Migration `20260907_0019` is the single head and offline SQL generation passes. Two focused live
PostgreSQL tests pass against a disposable PostgreSQL 16/pgvector database, including atomic rollback,
exact retry, graph policy, forced RLS and append-only checks; `0019 → 0018 → head` and `alembic check` pass.
T7-07 is complete locally. The round coordinator runs bounded dedicated Critic and optional peer `CRITIQUE`
dispatch, validates the whole Critique phase before pinned Critic-then-peer commits, then runs sealed
author-specific `REVISE` dispatch and stable target/responder commits. Complete execution attribution semantics,
runtime-owned response IDs, duplicate response/head checks and ordered timeout abstentions are explicit. The deterministic
handoff includes every latest head with no omit path and explicit empty reasons. An unsupported Claim is
reported as `EVIDENCE_GAP`; the deprecated `UNSUPPORTED_CLAIM` alias remains rejected. Evidence is 49 focused
and 607 offline tests, one live PostgreSQL handoff test, compileall and clean 248-file Ruff/format/mypy.
T7-08 and Phase 7 are complete; no public HTTP API changed. Exit evidence is 82 focused, 677 offline and
52 live tests, clean backend/frontend and repository gates, Alembic head `20260911_0021` with no drift,
and a clean disposable Compose run. Exact SHA `25914b48e1c5140279720d1a4dfb66483cf744a3` passed all six jobs
in GitHub Actions run [`34667037521`](https://github.com/potatosaladz/agora/actions/runs/34667037521).


Phase 10 uses `phase10-reasoning-graph`. T10-01 is complete locally: `ReasoningGraphStore` has backward,
forward, and bidirectional subgraph traversals over tenant/session-scoped recursive CTEs with path-based cycle
safety, explicit depth/radius caps, edge-type filters, and deterministic opaque cursor pagination. Pagination
orders node UUIDs before edge UUIDs, caps pages at 200, binds cursors to the complete query, and separates
depth `truncated` from `next_cursor`. Live PostgreSQL tests cover cycles, truncation, filtering, isolation, and
lossless multi-page reconstruction. The existing Phase 8 migration was repaired to reference
`agent_definitions.id`, use typed JSONB defaults, and register matching ORM metadata; the cumulative migration
acceptance now expects head `20260909_0020` and both simulation tables. Focused T10-01 Ruff/format/strict-mypy
checks pass, 20 graph unit tests pass, 7 live traversal tests pass, and the live cumulative downgrade/re-upgrade
plus `alembic check` passes. Repo-wide strict mypy (257 files), 666 non-integration tests, layering, and
offline head SQL also pass. Repo-wide Ruff is still red on inherited Phase 8/9 formatting/lint debt outside
the T10-01 diff. A full live integration attempt did not complete under the command harness after six tests;
focused T10-01 and migration live gates are the observed evidence. T10-02 is complete. The
`GET /api/v1/artifacts/{artifact_id}/provenance` read composes `trace_backward` with canonical artifact
and citation stores, exposes verification and current source status, preserves every edge type, and uses
existing depth-12 and cursor bounds. Citation lookup is a deterministic collection because one evidence
artifact may cite multiple chunks. No graph schema migration was added. Five focused provenance tests pass.
The exact live command `uv run pytest tests/integration/test_citation_retraction_persistence.py -q -rs`
passed 1 test in 2.98 seconds on implementation SHA
`e86e9ca24c06b8139a35d510a3c36b372f3499be`. It ran against a fresh disposable
`pgvector/pgvector:pg16` container with database/user `agora_test`, a random loopback port, generated
credentials, and a subprocess-scoped `TEST_DATABASE_URL`; no volume was attached and the container was
removed. The fixture now uses distinct hashes and matching source references for its two chunks. T10-03
is complete: `project/TRACEABILITY.csv` is deterministically generated for all 104 requirements from
74 documentation, 46 source, and 511 test annotations. The evidence audit retained 77 sole-`NFR-016`
tests, reassigned 149, and narrowed Phase 8 simulation and Phase 9 consensus citations. Pytest collects
729 tests; 677 non-integration tests pass, 52 service-dependent tests are deselected, strict mypy
passes over 267 files, and frontend/trace/link checks pass. Repository-wide Ruff still reports inherited
Phase 8/9 debt. T10-04 is implemented locally: source retraction, exhaustive bounded/cycle-safe impact
traversal, immutable exact-version reports, and `SOURCE_RETRACTED` outbox insertion share one
transaction, with authenticated idempotent APIs and generated OpenAPI types. Its two focused live
PostgreSQL tests pass, including clean migration plus drift, forced RLS, append-only enforcement,
rollback atomicity, report round-trip, and workspace-outbox publication.

## Known gaps

| Gap | Detail |
| --- | --- |
| Traceability evidence is not verification | 104 mapped rows do not mean 104 implemented, executed, or scientifically validated requirements; two live adapter tests retain NFR-016 as contract-parity evidence |
| No real-domain evaluation corpus | Phase 5 uses versioned synthetic mechanics fixtures; Q-1 remains for Phase 16 experiments |
| Documents are ahead of implementation | Some documented contracts now have adapters and tests, but the complete design baseline is not yet implemented |

## Recovery protocol

```bash
git status && git log --oneline -10     # expect: untracked tree until the first commit
cat project/CURRENT_STATE.md            # what is true now
cat project/TASKS.md                    # what is open, with acceptance criteria
cat project/ERRORS.md                   # what not to repeat
```

Then run the link check before trusting any cross-reference:

```powershell
# from the repository root
Get-ChildItem -Recurse -Filter *.md | ForEach-Object {
  $d = $_.DirectoryName
  Select-String -Path $_.FullName -Pattern '\]\((?!https?:|#)([^)#]+)' -AllMatches | ForEach-Object {
    foreach ($m in $_.Matches) {
      $t = ($m.Groups[1].Value -split '#')[0]
      if ($t -and -not (Test-Path (Join-Path $d $t))) { "$($_.Path) -> $t" }
    }
  }
}
```

## Working rules that are easy to violate by accident

- Write documents in sections. A single write above ~6 KB fails, and a partial write is worse
  ([ERRORS.md](ERRORS.md) E-03).
- Never mark a task done from intent. Observe the file, then tick it (E-01).
- Update the state files in the same commit as the change they describe.
- New terminology goes into [../docs/STRUCTURED_REASONING.md](../docs/STRUCTURED_REASONING.md) before it
  is used anywhere else.
- A new consensus strategy without a formalism document must be refused by the loader, and the refusal
  is the test.
