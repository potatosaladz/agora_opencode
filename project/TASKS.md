# Tasks (project register)

**Last updated:** 2026-09-10 · **Companion:** [../memory-bank/tasks.md](../memory-bank/tasks.md) (live
view) · [PLAN.md](PLAN.md) (phase contracts)

Legend: `[x]` done · `[~]` in progress · `[ ]` open · `[!]` blocked · `[-]` dropped
Estimates are focused-person-days and are honest about being guesses: `S` ≤ 1, `M` 2–4, `L` 5–10,
`XL` > 10 (split it).

## Phase 0 — Requirements & architecture · **complete and approved**

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T0-01 | Repository scaffold, Git init | `[x]` | S | `git status` runs; `.gitignore` excludes secrets and local state |
| T0-02 | Root `README.md`, `CHANGELOG.md` | `[x]` | S | structure, discipline and roadmap stated; recovery protocol present |
| T0-03 | Memory bank (9 files) | `[x]` | M | brief, architecture, tech context, active context, progress, tasks, decisions, errors, api-contracts |
| T0-04 | `docs/ARCHITECTURE.md` + 8 diagrams | `[x]` | L | every diagram parses as Mermaid; state ownership table names exactly one owner per state |
| T0-05 | Domain & research specifications | `[x]` | XL | 13 documents; every artifact type has fields, invariants and a lifecycle |
| T0-06 | Port contracts (19 ports) | `[x]` | L | each port has signature, semantics, adapter obligations, failure modes |
| T0-07 | API + versioned contracts | `[x]` | L | error envelope, pagination, idempotency, streaming and versioning rules all specified |
| T0-08 | MVP boundary + requirement classification | `[x]` | M | every `FR-`/`NFR-` carries exactly one track label |
| T0-09 | ADR-001 … ADR-020 | `[x]` | L | every ADR names rejected alternatives and negative consequences |
| T0-10 | Security / trustworthiness / ops docs | `[x]` | XL | 14 documents; STRIDE threats each map to a control |
| T0-11 | Consistency pass | `[x]` | L | link check clean; phase numbering unified with the roadmap; no document references a file that does not exist |
| T0-12 | Present Phase 0, request approval | `[x]` | S | approval recorded as dated decision [D-13](DECISIONS.md#accepted) |

**Gate satisfied:** Phase 0 was approved by the project owner on 2026-09-04 and recorded as D-13.

## Phase 1 — Foundation

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T1-00 | Verify toolchain | `[x]` | S | versions recorded in [../memory-bank/techContext.md](../memory-bank/techContext.md) |
| T1-01 | `pyproject.toml`, ruff/mypy/pytest config, package skeleton | `[x]` | M | `ruff check`, `mypy` and `pytest` all run green on an empty suite |
| T1-02 | FastAPI app factory, settings, health, error envelope | `[x]` | M | `/health` and `/ready` distinguish liveness from dependency health; every error uses the envelope |
| T1-03 | Layer layout with import-lint | `[x]` | M | a deliberate forbidden import makes CI fail (test the test) |
| T1-04 | Postgres + async SQLAlchemy + Alembic baseline | `[x]` | L | `alembic upgrade head` from empty; RLS active on tenant tables |
| T1-05 | pgvector + `VectorStore` port + Postgres adapter | `[x]` | S | cosine and IVFFlat index created; a 1k-vector fixture retrieves deterministically |
| T1-06 | Redis adapter (cache / rate limit only) | `[x]` | S | a test proves no durable object is stored in Redis |
| T1-07 | MinIO adapter behind `ObjectStore` | `[x]` | M | upload, presigned read, digest verification; bucket policy denies listing |
| T1-08 | NATS adapter behind `EventBus` + in-memory test double | `[x]` | M | publish/subscribe round-trip; duplicate delivery is idempotent |
| T1-09 | `docker-compose.yml` with healthchecks | `[x]` | M | `docker compose up --wait` reaches healthy for every service |
| T1-10 | Auth skeleton + RBAC roles | `[x]` | L | deny-by-default: an unauthenticated request to any non-public route is refused, tested per role |
| T1-11 | `SecretProvider` (env dev, Swarm secret prod) | `[x]` | S | prod startup refuses `env_file` provider |
| T1-12 | OTel + Prometheus + structured logs | `[x]` | M | one request traced API → DB; `/metrics` exposes RED metrics; redaction filter tested |
| T1-13 | Vite + React + TS skeleton, generated client | `[x]` | M | client regenerates from the OpenAPI document with no diff |
| T1-14 | CI pipeline | `[x]` | M | lint, typecheck, unit, contract, integration, link check, `trace-check` all gating |
| T1-15 | Phase 1 exit | `[x]` | S | healthy stack + green CI + docs updated in the same commit |

## Phases 2–17 · task detail

Full breakdown in [PLAN.md](PLAN.md). Estimates are per phase, not per task, until the phase is next.

| Phase | Status | Est | Exit criterion (the one that matters) |
| --- | --- | --- | --- |
| 2 LLM + registry | `[x]` | L | one agent definition runs on two providers and the mock; no SDK import outside `adapters/` |
| 3 Reasoning model | `[x]` | 4×M | T3-00…T3-09 complete; exact-SHA GitHub Actions run `33989090448` green |
| 4 Orchestration | `[~]` | XL | T4-01…03 complete with exact-SHA CI run `34005422198`; browser closed mid-session, worker killed, session completes, UI restores from the ledger |
| 5 RAG + memory | `[ ]` | L | every returned chunk resolves to a stored digest; cross-namespace retrieval fails closed |
| 6 Domain reasoning | `[ ]` | M | every position links evidence or declares `NO_EVIDENCE`; fabricated citations fail CI |
| 7 Critic loop | `[ ]` | L | a planted unsupported claim is detected and the detection is visible in the explanation |
| 8 Simulation | `[ ]` | L | same spec + seed replays byte-identically; sandbox has no network route (proven by test) |
| 9 Consensus | `[ ]` | XL | worked examples pass as unit tests; no-evidence input yields `INSUFFICIENT_EVIDENCE` |
| 10 Graph + traceability | `[ ]` | L | one API call walks a recommendation to its primary sources |
| 11 Neuro-symbolic | `[ ]` | L | an infeasible alternative is removed with its unsat core quoted |
| 12 MARL environment | `[ ]` | M | trajectories replay deterministically; reward components map to metric ids |
| 13 Trustworthiness | `[~]` | L | T13-01 complete; everything else open — a past session answers "why did it say that"; manifest replays in `TOLERANT` mode |
| 14 Full UI | `[ ]` | XL | a naive reviewer finds the minority position and the weakest evidence from the UI alone |
| 15 MCP gateway | `[ ]` | L | workers have no internet route; hostile tool output does not widen agent scope |
| 16 Research extensions | `[ ]` | XL | three research strategies each beat or lose to `constraint_aware` on measured terms |
| 17 Swarm + hardening | `[ ]` | L | restore drill succeeds; every threat has a control with a test id |

## Phase 12 — Deterministic MARL environment · **complete**

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T12-01 | Exact MARL domain and reward/credit contracts | `[x]` | M | frozen strict schemas, five metric-linked exact reward components, conserved provenance credit, and feasibility invariants pass |
| T12-02 | Episode lifecycle and in-memory store | `[x]` | M | OPEN/COMPLETE/INCOMPLETE, terminal/incomplete semantics, gapless append, idempotency, conflict and isolation pass |
| T12-03 | Canonical export and hermetic offline verification | `[x]` | L | exact two-file JCS/LF bytes, hash graph, pinned registry, bounded untrusted input, and deterministic 14-code first failure pass |
| T12-04 | PostgreSQL persistence and migration | `[x]` | L | revision 0024, tenant-safe FKs, forced RLS, append-only guards, caller-owned transaction and advisory-lock allocation implemented |
| T12-05 | Acceptance, documentation and traceability | `[x]` | M | focused tests, migration/static/full checks, normative MARL/port docs, FR-906 Phase 12 ownership and generated traceability are reconciled |

## Phase 13 — Trustworthiness · T13-01 complete

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T13-01 | Metric catalogue implemented ([METRICS.md](../docs/METRICS.md)) | `[x]` | M | 43 immutable shipped `MetricDefinition`s (EP-01…06, RR-01…07, DH-01…07, CQ-01…06, RB-01…05, CE-01…05, HO-01…04, CA-01…03) carry the six admission fields (profile/dimension, label, direction, range kind/bounds, unit, ID); `MetricCatalogue` orders deterministically and `get(metric_id, metric_version)` fails closed with no "latest"; 13 focused tests transcribe METRICS.md field-by-field and pin the Phase 12 reward metrics at version `"1"`; no metric engine, storage, API, UI, replay or migration added and no frontend/metrics runtime touched |
| T13-02 | Audit record generation and the eight audit queries ([AUDITABILITY.md](../docs/AUDITABILITY.md)) | `[x]` | L | migration `20260912_0025` adds forced-RLS append-only `access_log` + `audit_anchors` (`TRIGGER` rejects UPDATE/DELETE, sqlstate 27000); `app/domain/audit.py` typed contracts incl. `AuditAnchor.publish` and shared `_anchor_facts`; `app/db/audit.py` adapters (`SqlAlchemyAccessLogRepository`, `SqlAlchemyAuditAnchorRepository`, `SqlAlchemySessionParticipantReader`); `app/db/consensus.py` gains `ConsensusResultStore.get_round_result`; `app/application/audit.py` answer Q1-Q8 as typed services (`AuditQueryService`, `AccessAuditService`, `ChainVerificationService`) with pure determinism (`_anchor_facts`, ledger `chain_integrity`, `_originating_turn`), Q7 bounded strictly before `recommendations.created_at`; 21 unit + 7 PostgreSQL integration tests incl. tamper detection, RLS 42501 isolation, FK 23503, same-day anchor conflict, two-day chain verification; docs AUDITABILITY.md 1.4 + DATA_MODEL.md 11.1; FR-807/NFR-006 flipped to implemented |
| T13-03 | Replay modes `STRICT` / `TOLERANT` / `LIVE` | `[ ]` | M | not started |
| T13-04 | Run manifests with pinning | `[ ]` | M | not started |

## Phase 3 — detailed execution plan

The original XL item is split into four independently green increments. T3-00 is blocking: the design
baseline currently disagrees on the entity set, common envelope, `Fact` representation, ledger columns,
and references to tables owned by later phases. Runtime code must not guess through those differences.

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T3-00 | Reconcile and freeze the Phase 3 contracts | `[x]` | M | `REQUIREMENTS`, `DATA_MODEL`, `STRUCTURED_REASONING`, API contracts and ADR-019 agree on the Phase 3 entity set, concrete DDL, session/API/UI boundary and verification, provenance references, actor vocabulary, per-session sequence allocation and hash preimage; links/contracts pass |
| T3-01 | Common envelope and 14 FR-301 domain artifact types | `[x]` | M | strict typed construction covers Claim, Fact, Assumption, Inference, Proposition, Evidence, Uncertainty, Risk, Impact, Objective, Constraint, Alternative, Position and Critique; invalid combinations fail; canonical serialization/hash is byte-stable |
| T3-02 | Session/problem binding and proposition normalization | `[x]` | M | a session binds problem, versioned agent definitions, objectives, constraints and budget; proposition preserves original plus normalized form and canonicalizer version; ambiguous normalization cannot enter consensus |
| T3-03 | Phase 3 relational schema, ORM rows and tenant isolation | `[x]` | L | linear upgrades from `20260905_0004`; every tenant table has forced RLS and tenant-safe FKs; clean upgrade and `alembic check` pass; no later-phase table is added accidentally |
| T3-04 | Graph store contract and PostgreSQL write path | `[x]` | M | nodes resolve to existing typed rows; edges reject missing endpoints, cross-workspace links, disallowed self-loops and duplicate triples; artifact and projection share a transaction |
| T3-05 | Append-only, hash-chained reasoning ledger | `[x]` | M | concurrent appends produce one gapless per-session order; retries by event id are idempotent; payload/event hashes are deterministic; clean chain verifies and a changed row is detected |
| T3-06 | Atomic artifact commit, revise and withdraw use cases | `[x]` | M | one transaction commits artifact + event + graph projection or none; revision writes a new row and `SUPERSEDES` edge; physical delete and in-place content mutation fail in PostgreSQL |
| T3-07 | Tenant-scoped Phase 3 API and authored contracts | `[x]` | M | the T3-00-approved create/read flows enforce RBAC, idempotency and version conflicts; unsupported claims are explicit; OpenAPI validation and generated TypeScript client drift checks pass |
| T3-08 | Phase 3 acceptance and requirement traceability | `[x]` | M | FR-101…103 and FR-301…312 have code/tests/status evidence as agreed in T3-00; FR-101 walkthrough plus unit/property/contract/live PostgreSQL suites cover the required verification methods and preserve all Phase 1/2 gates |
| T3-09 | Phase 3 exit | `[x]` | S | full local CI equivalents, healthy Compose, schema-doc diff, anti-pattern checklist and state docs are green; remote CI passes before the phase is marked complete |

## Phase 4 — detailed execution plan

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T4-01 | Typed workflow client/worker ports, in-memory adapters and Temporal infrastructure adapters | `[x]` | M | no `Any` in public workflow signatures; client and worker registration are separate; start is idempotent by workflow id; Temporal health/start/duplicate/describe and real worker polling complete live; Compose/readiness and inherited gates are green |
| T4-02 | Session workflow and deterministic coordinator state machine | `[x]` | L | a bound draft starts through the separate `202` endpoint; every transition is deterministic and committed to PostgreSQL/ledger |
| T4-03 | Agent activities | `[x]` | L | all LLM/RAG/simulation/symbolic I/O runs outside workflow code with typed activity inputs/results |
| T4-04 | Pause, resume, cancel and human-in-the-loop signals | `[x]` | M | typed controls are idempotent, authenticated and interpreted by the workflow |
| T4-05 | Retry, timeout, idempotency, dead-letter and checkpoint policy | `[x]` | M | failures obey bounded declared policy without duplicate committed effects |
| T4-06 | Ledger to NATS to SSE realtime path | `[x]` | M | reconnect resumes from ledger sequence without loss or transport authority |
| T4-07 | Phase 4 exit browser recovery | `[x]` | M | browser closes mid-session and restores completed state from the ledger |
| T4-08 | Worker/activity recovery tests | `[x]` | M | worker crash and activity retry preserve exactly-once committed effects |

## Phase 5 — detailed execution plan

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T5-00 | Reconcile and freeze Phase 5 contracts | `[x]` | M | requirements, ports, RAG/memory architecture, data model, API ownership, fixture corpus and T5-01…09 acceptance criteria agree; no runtime schema is added before conflicts are resolved |
| T5-01 | Typed ingestion domain and deterministic structure-aware chunking | `[x]` | L | PDF, DOCX, TXT, Markdown, CSV, XLSX, JSON and HTML fixtures parse into normalized documents and byte-stable 800-token-target/150-token-overlap chunks with locators, warnings, hashes and pinned parser/chunker versions |
| T5-02 | Tenant-safe knowledge schema and repositories | `[x]` | L | linear migration adds namespaces, grants, sources, documents and chunks with composite workspace foreign keys, forced RLS, immutable provenance identity and no cross-workspace references; clean upgrade and `alembic check` pass |
| T5-03 | Durable ingestion activity and object lifecycle | `[x]` | M | bytes are digest-verified in object storage; retries are idempotent; parse/embed/index states and redacted failures are durable; unsupported media fails explicitly |
| T5-04 | UUID-backed pgvector index integration | `[x]` | M | vector entries resolve to stored chunks/documents/sources, pin embedding model/version and content hash, reject stale embeddings, preserve deterministic ordering; 345 offline tests and 6 authoritative live PostgreSQL tests pass |
| T5-05 | Hybrid retrieval and reranking | `[x]` | L | PostgreSQL lexical and vector candidates are grant/ACL-filtered in materialized pre-score relations, fused by deterministic RRF with recorded arm scores, reranked behind a strict port, and degrade explicitly; 352 offline tests and 2 focused live PostgreSQL tests pass |
| T5-06 | Namespace grants and retrieval audit | `[x]` | L | all six tiers validate workspace/human/agent/session subjects against PostgreSQL before scoring; agent sessions require `session_agents`; forged/empty scope fails closed; append-only forced-RLS audits persist text-free allowed/denied census and audit failure fails retrieval closed; 354 offline and 3 focused live PostgreSQL tests pass |
| T5-07 | Resolvable citations, manual evidence and source retraction | `[x]` | L | exact IDs, citation, ordered span, digests, timestamps and trust survive retrieval/reranking; PostgreSQL validates human evidence and full provenance before append; irreversible retraction excludes future retrieval while preserving old resolution and Phase 10 dependencies; 359 offline and 4 focused live PostgreSQL tests pass |
| T5-08 | Memory tiers and validated promotion | `[x]` | L | working/episodic/semantic/procedural scopes are explicit; direct semantic writes and SQL bypass fail; promotion records active human validator, evidence, caveats, review/supersession history; stale/archive facts never delete authoritative rows; 363 offline and 1 focused live PostgreSQL test pass |
| T5-09 | Phase 5 exit retrieval baseline | `[~]` | M | versioned synthetic baseline, digest/isolation/audit and FR-401…409 disposition complete; 370 offline and 40 live Compose-backed tests plus inherited local gates pass; exact-SHA CI pending |

## Phase 6 — detailed execution plan

T6-00 is blocking: Phase 4 already provides a provider-neutral agent-turn activity, but the approved
design still needs one executable contract for runtime/strategy composition, automatic decomposition,
durable `NO_EVIDENCE`, sealed mediation, attribution, injection and budget ownership.

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T6-00 | Reconcile and freeze Phase 6 contracts | `[x]` | M | `PHASE6_ACCEPTANCE`, requirements, agent model/protocols, ports and phase plan agree on authority, scope, evidence disposition, sealed context, output attribution, budgets and later-phase exclusions; links and traceability pass |
| T6-01 | Strict `AgentRuntime` and `ReasoningStrategy` ports | `[x]` | M | immutable SDK-free context and generic ports compose the Phase 4 turn activity; exact-version registry fails closed; deterministic test strategy and contract tests pass; position proposals require `CITED` or `NO_EVIDENCE`; focused evidence is 31 tests plus clean Ruff and strict mypy |
| T6-02 | Automatic structured problem decomposition | `[x]` | M | proposal-only service requires non-empty unique `PROPOSITION` output, original/normalized text, the pinned canonicalizer version and non-ambiguous normalization; mixed/request-bearing/malformed output fails before identity allocation or commit; focused evidence is 39 tests plus clean Ruff and strict mypy |
| T6-03 | Authorized reasoning-context assembly | `[x]` | L | immutable context binds active typed objectives/constraints, exact runnable definition/version, authorized retrieval provenance and unique active non-future artifacts; cross-scope/pin/subject/trace/namespace/result inconsistencies fail closed; round-1 `ASSESS` rejects artifacts before reads; zero-match remains distinct and retrieval failures propagate; focused evidence is 68 tests plus clean full Ruff and strict mypy |
| T6-04 | Proposal validation and atomic coordinator commit | `[x]` | L | whole bundles preflight before writes; coordinator derives retry-stable identities and atomically commits artifacts, graph nodes and attribution-rich ledger events in proposal order; exact retry is idempotent under a turn lock; every position is `CITED` or `NO_EVIDENCE`; hidden/fabricated/wrong-kind/inactive/future IDs produce no partial writes; evidence is 53 focused unit tests, one contract and 428 offline tests, with PostgreSQL coverage later passing in the complete T6-09 live suite |
| T6-05 | Five policy-analysis expert definitions | `[x]` | M | fiscal, macroeconomic, social-policy, infrastructure and risk definitions have workspace-scoped stable identities, distinct objectives/stances, literal digest-sealed packaged prompts staged by content-addressed object key and schema-valid deterministic mock outputs through the real activity; evidence is 16 focused and 435 offline tests plus clean full Ruff/format, strict mypy, wheel-resource, contract, traceability, link and whitespace gates |
| T6-06 | Sealed shared-pool multi-agent dispatch | `[x]` | L | sealed same-session/round/phase turns fan out through bounded proposal-only workers with no peer channel; input order survives completion races; per-turn timeout returns typed `ABSTAIN`/`TURN_TIMEOUT` while runtime failures propagate; evidence is 7 focused and 442 offline tests plus clean Ruff/format, strict mypy, contracts, traceability, links and whitespace gates |
| T6-07 | Orchestrator proposal policy | `[x]` | M | strict frozen orchestrator proposals can recommend decomposition, eligible-agent routing or an immediate next phase only; coordinator pins identity, enforces fixed order, records one retry-stable `POLICY` acceptance/rejection with `applied: false`, and exposes no mutation dependency; evidence is 22 focused and 464 offline tests plus clean 225-file Ruff/format/mypy, contracts, traceability, links and whitespace gates |
| T6-08 | Agent-set intervention, attribution, budgets and scale | `[x]` | L | append-only effective-round replacement/injection is lifecycle-lock serialized and ledger ordered; context and retrieval use effective membership; durable session/agent ceilings fail once with `BUDGET_EXHAUSTED`; a four-worker 20-agent fixture commits 20 claims in pinned order with complete attribution; evidence is 21 focused, 474 offline and complete 42-test live-suite coverage plus clean Ruff/format, strict mypy, migration SQL, contracts, traceability, links and whitespace |
| T6-09 | Phase 6 exit | `[x]` | M | EOL-stable prompt digests/client drift tests, 69 focused, 479 offline and 42 live backend tests, backend quality, complete Node 22 frontend including format and 22 tests, contracts, traceability, links, whitespace, anti-pattern review and Compose health are green; guaranteed XOR tamper fix at exact-SHA commit `6d671acffe7abd3e5b587042457f300e0c442adc` passed all six jobs in GitHub Actions run `34148649503` |

## Phase 7 — detailed execution plan

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T7-00 | Reconcile and freeze Phase 7 contracts | `[x]` | M | requirements, Critic role, exact taxonomy, target/authorship rules, response mapping, immutable resolution, sealed revision, request deferral, orchestration, explanation handoff and T7-01…08 criteria agree against Phase 6 SHA `6d671acffe7abd3e5b587042457f300e0c442adc`; no runtime schema added first |
| T7-01 | Strict Critic and response contracts | `[x]` | M | frozen values represent exactly ten FR-501 types and seven FR-503 dispositions; Critic bundles contain only new `OPEN` Critiques; mutation authority, aliases and invalid response shapes fail validation; evidence is 44 focused and 523 offline tests plus clean 231-file Ruff/mypy and repository gates |
| T7-02 | Shipped cross-cutting Critic definition | `[x]` | M | workspace-scoped immutable Critic has distinct adversarial objectives, LF digest-sealed packaged prompt and deterministic mock output attacking every artifact kind through the existing activity; wheel contains the exact 896-byte prompt with its frozen SHA-256 and no CR bytes |
| T7-03 | Authorized Critic context and bounded dispatch | `[x]` | M | active same-session non-future context remains inherited from the fail-closed assembler; Critic wrapper pins assignments, composes budgeted bounded dispatch, exposes no peer/write channel, distinguishes timeout, and records `CRITIC_INACTIVE` only on the third consecutive completed empty round; evidence is 8 focused tests |
| T7-04 | Atomic Critique commit and attack projection | `[x]` | L | exact assignment, target, visibility, lifecycle and duplicate attacks preflight before the existing transaction commits Critique, node, coordinator-derived qualified `ATTACKS`, events and attribution; shared commit path cannot bypass assignment; Critic and peer roles are phase-bound; exact retry is idempotent and all 14 target kinds plus invalid targets are covered; evidence is 86 focused, 565 offline and clean 238-file quality gates |
| T7-05 | Critique response and immutable resolution policy | `[x]` | L | target owner can issue all seven dispositions; stale/foreign responses fail; warrants and requests are validated; every resolution change appends a Critique version/event and preserves unresolved/disputed heads |
| T7-06 | Targeted revision and response lineage | `[x]` | L | sealed author-specific `REVISE` context yields one schema-valid same-owner/logical-id successor; target and Critique heads advance atomically with exact `SUPERSEDES` and `RESPONDS_TO`; conflicting retries fail closed |
| T7-07 | Critique/revision phase orchestration and explanation handoff | `[x]` | L | coordinator runs fixed `CRITIQUE` then `REVISE` ordering with stable commits; planted unsupported Claim becomes `EVIDENCE_GAP`; deterministic handoff includes every latest open/unresolved/disputed head and no omit path; evidence is 607 offline tests, one focused live PostgreSQL test, and clean 248-file Ruff/format/mypy plus compileall |
| T7-08 | Phase 7 exit | `[x]` | M | FR-205/501…504 proofs, 82 focused, 677 offline and 52 live tests, backend/frontend quality, contracts, migrations, traceability, links, whitespace, anti-pattern review and healthy Compose are green; exact SHA `25914b48e1c5140279720d1a4dfb66483cf744a3` passed all six jobs in GitHub Actions run `34667037521` |

## Phase 8 — Simulation & sandbox execution

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T8-00 | Contract tests for simulation types, engine protocol and orchestration | `[x]` | M | 36 tests covering `SimulationSpec`, `SimulationResult`, `ValidationReport`, `SimulationRunRecord`, port protocols, `compute_sensitivity_ranks` and async orchestration; all pass alongside existing 28 contract + 12 layering tests (76 total) |
| T8-01 | Simulation domain types split across layers | `[x]` | M | Port-level `SimulationSpec`, `SimulationResult`, enums and value objects in `app/ports/simulation.py` using local `_Frozen` base (no cross-layer import); domain adds `RunStatus`, `SimulationRunRecord`, `SimulationRunStore` and re-exports |
| T8-02 | `SimulationEngine` and `SandboxExecutionProvider` port protocols | `[x]` | M | `SimulationEngine` protocol with `run`, `validate`, `capabilities`; `SandboxExecutionProvider` with `execute`, `health`, `close`; `SandboxRequest`/`SandboxResult`/`SimulationCapabilities` value objects |
| T8-03 | `SimulationOrchestrator` application service | `[x]` | L | request → validate → run → rank sensitivity → store lifecycle; `TimeoutError` → `TIMEOUT`, generic → `FAILED`; `SimulationError` structured exception |
| T8-04 | `compute_sensitivity_ranks()` pure function | `[x]` | S | ranks by descending absolute index; handles empty input and negative indices |
| T8-05 | Alembic migration `20260909_0020` for simulation tables | `[x]` | M | `simulation_runs` and `simulation_results` tables with RLS, CHECK constraints, indexes on workspace+session and spec_hash; single Alembic head |

## Phase 9 — Consensus engine

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T9-01 | `ConsensusContext` assembly and consensus value objects | `[x]` | M | `ConsensusContext`, `ConsensusResult`, `ConsensusExplanation` and every supporting value object (`AgentPosition`, `EvidenceCitationInput`, `ObjectiveInput`, `DissentEntry`, `MinorityEntry`, `FeasibilityVerdict`, `StrategyConfig`) defined in `app/ports/consensus.py`; eight-member `ConsensusOutcome` enum matches FR-604 exactly |
| T9-02 | Shared feasibility gate | `[x]` | M | `feasibility_gate()` in `app/domain/consensus.py` implemented once and reused by every strategy; an infeasible alternative can never be ranked regardless of score (FR-602, FR-603) |
| T9-03 | `weighted`, `evidence_weighted`, `constraint_aware` strategies | `[x]` | L | each strategy in `app/application/consensus.py` reproduces its worked example in `docs/consensus-formalism/` verbatim (`WeightedStrategy`, `EvidenceWeightedStrategy`, `ConstraintAwareStrategy`) |
| T9-04 | Outcome classification | `[x]` | M | all eight FR-604 outcomes reachable: a session with no verified evidence returns `INSUFFICIENT_EVIDENCE` rather than a ranking; conflicting objectives yield `PARETO_SET` rather than a forced single winner (FR-607) |
| T9-05 | `ConsensusExplanation` emitted with every outcome | `[x]` | M | `ConsensusOrchestrator` persists result and a complete explanation (algorithm, version, formula, weights, thresholds, per-agent contributions, derivation trace) for every strategy call (FR-605) |
| T9-06 | `StrategyRegistry` refusing unregistered/undocumented strategies | `[x]` | S | registry rejects an unregistered strategy, a strategy without a formalism document (FR-608, S-1), and duplicate name/version pairs |

**Exit gate satisfied:** the three formalisms pass their worked examples as unit tests (13 new tests in
`backend/tests/unit/test_consensus.py`); a session with no verified evidence returns
`INSUFFICIENT_EVIDENCE` rather than a ranking; minority positions appear in the output and cannot be
suppressed through the API (FR-505, FR-506). Full suite 620 passed, 0 failed, 43 pre-existing unrelated
skips; Ruff and mypy clean. Merged to `master` at `b95f24b`.

## Phase 10 — Reasoning graph & traceability · **complete**

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T10-01 | Graph read APIs and traversals | `[x]` | L | `trace_backward`, `trace_forward`, `subgraph` on `ReasoningGraphStore` use tenant/session-scoped recursive CTEs; cycle-safe, bounded `max_depth`, opaque query-bound cursor pagination (100 default/200 cap), deterministic ordering, independent depth `truncated` and `next_cursor` signals; unit, live PostgreSQL traversal, migration-head and drift gates pass |
| T10-02 | Recommendation-to-source path query | `[x]` | M | `provenance_of(artifact)` uses bounded cycle-safe graph ancestry and resolves EVIDENCE to canonical source/document/chunk citations in one API call, with verification and current source status surfaced. Five focused provenance tests and the citation persistence test pass; live acceptance used an isolated disposable PostgreSQL 16/pgvector database and implementation SHA `e86e9ca24c06b8139a35d510a3c36b372f3499be`. |
| T10-03 | `TRACEABILITY.csv` generated from `# trace:` annotations | `[x]` | M | deterministic generation covers all 104 requirements from documentation, source, Python-test, and frontend-test annotations; strict malformed/unknown/node validation, semantic evidence audit, pytest collection, 673 offline tests, strict mypy, frontend gates, links, and generated-artifact drift checks pass |
| T10-04 | Impact analysis | `[x]` | L | Workspace-wide `impact_of(source)` exhausts paginated, bounded T10-01 forward traversals from every canonical citation root and reports completeness honestly; atomic retraction persists immutable exact-version dependency snapshots and inserts `SOURCE_RETRACTED` into the workspace outbox. Impact is exposure only: claims are not mutated or automatically contested. Authenticated idempotent retraction and report APIs use opaque IDs (completes FR-408). |

**Exit gate satisfied:** T10-01 through T10-04 are complete. From any recommendation, one API call
returns the chain to primary sources with verification states; deterministic `trace-check` covers all
104 requirements and fails the build on an orphan.

## Phase 11 — Neuro-symbolic · **complete**

| ID | Task | Status | Est | Acceptance |
| --- | --- | --- | --- | --- |
| T11-01 | Formalisation pipeline with `validation_status` | `[x]` | L | Closed typed AST; deterministic JCS hashing/rendering and structural/sort/unit validation; immutable source-pinned revisions, validation and human-decision facts; derived `CANDIDATE`, `VALIDATED`, `REJECTED`; only successful validation plus confirmation is enforceable; forced-RLS persistence, lifecycle outbox, idempotent API and FR-707 evidence pass |
| T11-02 | Z3 adapter behind `SymbolicReasoner` | `[x]` | L | Bounded isolated Z3 execution translates the complete closed AST with exact numbers and returns solver-neutral `SAT`, `UNSAT`, or first-class `UNKNOWN`; invalid input and solver failures fail closed, with no lifecycle or persistence side effects |
| T11-03 | Unsat cores and witness models | `[x]` | L | Solver-neutral exact typed witnesses and deterministic contradiction-sufficient AST-path cores; immutable exact-revision persistence with forced RLS, evidence-shape/hash constraints, idempotent replay, and no T11-04 side effects |
| T11-04 | `UNKNOWN` handling policy | `[x]` | M | Application-owned exhaustive `SAT → PROCEED`, `UNSAT → BLOCK`, `UNKNOWN → DEFER` policy; deterministic safe reason classification; persisted solver facts remain immutable; consensus preserves unresolved status and caps selected unknowns at conditional without treating them as satisfaction or violation |

T11-01 deliberately does not execute a solver, persist symbolic evaluation results, create result-derived
graph edges, or implement T11-02 through T11-04.

## Standing tasks

| ID | Task | Cadence |
| --- | --- | --- |
| TS-01 | Update memory bank + project state after every significant unit of work | every commit |
| TS-02 | Keep `memory-bank/api-contracts.md` and `docs/API_CONTRACTS.md` synced with code | every API change |
| TS-03 | Record every significant error in [ERRORS.md](ERRORS.md) with root cause + prevention | on occurrence |
| TS-04 | Write the formalism document for every consensus plugin before it registers | per plugin |
| TS-05 | Re-run the [ANTI_PATTERNS.md](../docs/ANTI_PATTERNS.md) checklist | every phase exit |
| TS-06 | Re-run the link and file-existence check | every docs change |
| TS-07 | Review open questions in [DECISIONS.md](DECISIONS.md) §Open | every phase start |

## Blocked / waiting

| ID | Item | Waiting on |
| --- | --- | --- |
| W-2 | Evaluation task suite | choice of domain(s) for the first experiments |
| W-3 | Second-vendor production validation | vendor credentials and budget; deployment follow-up, not a Phase 3 blocker, because Phase 2 portability was proven with two distinct compatible endpoints and the mock |

