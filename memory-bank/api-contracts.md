# API & Contract Registry (memory bank)

**Last updated:** 2026-09-14 · **Contract baseline:** `v1` (through Phase 14 T14-05)
**Normative source:** [../docs/API_CONTRACTS.md](../docs/API_CONTRACTS.md) and
[../docs/API.md](../docs/API.md); activity delivery semantics are in
[../docs/ORCHESTRATION_POLICY.md](../docs/ORCHESTRATION_POLICY.md). This file is the quick-reference digest and the
synchronization checklist. If code and this file disagree, **both are wrong** — fix them
in the same commit.

---

## 1. Contract versioning rules

1. Every externally persisted payload carries `schema_version` (integer, starts at 1).
2. `schema_version` is a **contract** revision. Artifact `version` is an **entity**
   revision. They are independent and must never be conflated.
3. Additive optional fields → minor doc label only (e.g. `v1.1`). Removing, renaming or
   re-typing a field, or changing semantics → bump `schema_version` and write a migration
   note. Never mutate an old schema in place.
4. Event payloads are immutable once written to the ledger. A changed event shape means a
   new `event_type` or a new `payload_schema_version`, plus a reader accepting both.
5. REST responses use the stable envelope in [API_CONTRACTS.md §3](../docs/API_CONTRACTS.md). Breaking
   the envelope breaks every client.
6. The authored `contracts/openapi.yaml` is authoritative as of T1-13. FastAPI's generated OpenAPI
   and documentation routes are disabled so they cannot become an implicit public surface.

## 2. Common artifact envelope (all reasoning entities)

```json
{
  "id": "uuidv7",
  "schema_version": 1,
  "workspace_id": "uuidv7",
  "session_id": "uuidv7",
  "owner_actor_class": "HUMAN | AGENT | SERVICE | POLICY",
  "owner_actor_id": "uuidv7",
  "artifact_type": "CLAIM",
  "version": 1,
  "status": "ACTIVE | SUPERSEDED | WITHDRAWN",
  "supersedes_id": "uuidv7 | null",
  "created_at": "2026-09-04T10:15:00Z",
  "updated_at": "2026-09-04T10:15:00Z",
  "provenance": { "origin": "LLM | HUMAN | RETRIEVAL | SIMULATION | SYMBOLIC | IMPORT", "reference": "…" },
  "source_references": [],
  "confidence": { "kind": "scalar", "value": 0.74 },
  "parent_relationships": [],
  "metadata": {},
  "content_hash": "sha256:…"
}
```

## 3. Entity contract index

| Contract | Doc § | Phase |
| --- | --- | --- |
| `AgentDefinition` / `AgentVersion` | 3 | 2 |
| `LLMConfiguration` (secret is a **reference**, never a key) | 4 | 2 |
| `ReasoningSession` / `SessionState` | 5 | 3–4 |
| `Proposition` (normalized + `original_statement`) | 6 | 3 |
| `Claim`, `Fact`, `Assumption`, `Inference` | 6 | 3 |
| `Evidence` (provenance + `verification_status`) | 7 | 3, 5 |
| `Uncertainty` (typed, distribution-capable) | 8 | 3 |
| `Risk`, `Impact` | 8 | 3 |
| `Objective`, `Constraint` (hard / soft / non-negotiable) | 9 | 3 |
| `Alternative` | 6 | 3 |
| `Position` | 6 | 3 |
| `Critique` | 6 | 3, 7 |
| `CritiqueAssignment`, `CritiqueResponseProposal`, `ArtifactRevisionProposal` | API_CONTRACTS §4.4 | 7 |
| `CritiqueResponseRequest`, `CritiqueResponseResult` | API_CONTRACTS §4.4 | 7 |
| `FormalizationRevision`, `FormalizationValidation`, `FormalizationDecision` | API_CONTRACTS §4.2 | 11 |
| `SimulationRequest`, `SimulationResult` | 12 | 8 |
| `SymbolicEvaluation`, `ConstraintReport` | 13 | 11 |
| `ConsensusResult`, `ConsensusExplanation` | 15 | 9 |
| `Recommendation`, `Decision` | 16 | 9–10 |
| `ReasoningEvent` (ledger) | 17 | 3 |
| `OrchestratorProposal`, `CoordinatorProposalContext`, `OrchestratorDecision` | AGENT_PROTOCOLS §3.1 | 6 |
| `GraphNode`, `GraphEdge` | 18 | 3, 10 |
| `MetricDefinition`, `MetricValue` | 19 | 13 |
| `Experiment`, `ExperimentRun` | 20 | 13, 16 |
| `AuditRecord` | 21 | 13 |
| `ReplayRequest`, `ReplayResult`, `ReplayManifestRef` | API_CONTRACTS T14-05 | 13–14 |
| `ReproducibilityManifest` | 22 | 13 |
| `LearningEvent`, `KnowledgePromotion` | 23 | 5, 16 |

## 4. Event contract index (`event_type` values)

```text
session:   SESSION_CREATED SESSION_INITIALIZED AGENT_SELECTED AGENT_JOINED SESSION_COMPLETED
           SESSION_FAILED ACTIVITY_DEAD_LETTERED SESSION_CANCELLED SESSION_PAUSED SESSION_RESUMED
problem:   PROBLEM_DEFINED PROBLEM_DECOMPOSED
artifact:  PROPOSITION_CREATED CLAIM_PROPOSED EVIDENCE_ADDED ASSUMPTION_ADDED RISK_IDENTIFIED
           UNCERTAINTY_UPDATED OBJECTIVE_DECLARED CONSTRAINT_DECLARED ALTERNATIVE_DEFINED
challenge: CLAIM_SUPPORTED CLAIM_CHALLENGED CRITIQUE_CREATED CRITIQUE_RESPONDED CLAIM_REVISED
           POSITION_UPDATED
policy:    ORCHESTRATOR_PROPOSAL_ACCEPTED ORCHESTRATOR_PROPOSAL_REJECTED
membership: SESSION_AGENT_REPLACED SESSION_AGENT_INJECTED
retrieval: RAG_REQUESTED RAG_COMPLETED RAG_FAILED
sim:       SIMULATION_REQUESTED SIMULATION_STARTED SIMULATION_COMPLETED SIMULATION_FAILED
symbolic:  CONSTRAINT_EVALUATED CONSTRAINT_VIOLATED SYMBOLIC_EVALUATION_COMPLETED
consensus: CONSENSUS_CALCULATED CONSENSUS_REACHED PARTIAL_CONSENSUS NO_CONSENSUS DEADLOCK
           CONVERGENCE_EVALUATED ALTERNATIVE_SCORED
human:     HUMAN_EVIDENCE_INJECTED HUMAN_CONSTRAINT_ADDED HUMAN_OBJECTIVE_MODIFIED
           HUMAN_OVERRIDE HUMAN_APPROVAL_GRANTED HUMAN_APPROVAL_DENIED
resource:  BUDGET_EXHAUSTED ROUND_LIMIT_REACHED TIMEOUT_EXCEEDED
mcp:       TOOL_CALLED TOOL_CALL_FAILED TOOL_APPROVAL_REQUIRED
memory:    KNOWLEDGE_CANDIDATED KNOWLEDGE_VALIDATED KNOWLEDGE_PUBLISHED KNOWLEDGE_DEPRECATED
```

Every event carries `id`, `workspace_id`, `session_id`, per-session `ledger_seq`, `event_type`,
`recorded_at`, `actor_class`, `actor_id`, `round`, `payload_schema_version`, `payload`,
`correlation_id`, optional `causation_id`, and mandatory `payload_hash`, `prev_hash`, `event_hash`.
Actor classes are `HUMAN`, `AGENT`, `SERVICE`, `POLICY`; ADR-019 and DATA_MODEL §11.0 define
allocation, canonicalization and exact hash preimage.

T6-07 proposal decisions use stable policy `orchestrator-coordinator-policy@1`. Both event types
record proposal hash and content, pinned orchestrator attribution, rule and `applied: false`;
acceptance does not itself execute routing, phase advancement, decomposition, or any state mutation.

T6-08 membership events carry exact old/new definition IDs as applicable, effective round, actor,
correlation and reason. The append-only membership row shares the event ID and replays in ledger order.
`BUDGET_EXHAUSTED` records session/agent scope, durable usage and ceiling and is also the terminal lifecycle
event. These are internal transaction-scoped contracts; no HTTP endpoint was added in T6-08.

T7-05/T7-06 responses are internal transaction-scoped contracts. The response request stores the exact
proposal plus complete pinned strategy/prompt/provider/token/cost/raw-output attribution and canonical hash.
The result stores the seven-disposition status/resolution mapping and committed successor/event IDs. Exact
retry returns that result; conflicting identity or stale heads fail. `REVISE` creates both immutable heads
with coordinator-derived `SUPERSEDES`, `RESPONDS_TO`, and, for a Critique target, `ATTACKS` relationships.
Evidence intent is `EVIDENCE_REQUESTED`; simulation intent is `SIMULATION_DEFERRED`.

## 5. HTTP conventions

```text
Base:            /api/v1
Auth:            Bearer access token; identity/workspace/role from AccessTokenVerifier
Envelope (ok):   {"data": …, "meta": {"request_id", "schema_version"}}
Envelope (err):  RFC 9457 problem+json with code, detail, trace_id, retryable
Pagination:      ?limit=&cursor=   (opaque cursors; never offsets on the ledger)
Idempotency:     Idempotency-Key header on all state-creating POSTs
Concurrency:     If-Match / ETag on versioned artifacts
Formalisation:   POST/GET /api/v1/formalizations; revisions/validations/confirmations/rejections
Phase 3 writes:  POST sessions; POST artifacts; POST artifact revisions/withdrawals
Phase 4 start:   POST /api/v1/sessions/{id}/start -> 202 (T4-02; separate from 201 create)
T14 dissent:     GET /api/v1/sessions/{id}/dissent (complete latest persisted minority + open critique view)
T14 register:    GET /api/v1/sessions/{id}/assumptions (complete assumption/constraint/uncertainty history)
T14 explanation: GET /api/v1/sessions/{id}/explanation (complete persisted decision explanation; no recompute)
SSE:             GET /api/v1/sessions/{id}/events/stream   (Last-Event-ID supported)
WS:              /api/v1/ws/sessions/{id}   (bidirectional control only where required)
```

Resource families: `auth`, `workspaces`, `agents`, `llm-providers`, `sessions`,
`propositions`, `claims`, `evidence`, `knowledge`, `rag`, `critiques`, `simulations`,
`formalizations`, `consensus`, `metrics`, `experiments`, `audit`, `mcp`, `system`.

The T14 dissent read has no filter/omission parameters. It chooses the latest consensus result by
`(round,id)`, exposes majority context without support/dissent scores, hydrates minority warrants from
artifact authority and includes every open/unresolved/disputed Critique handoff head. Public IDs and
tenant-hidden `404` are mandatory. `evaluated` plus `empty_reason` distinguishes no result, a result whose
explanation is unavailable, and an evaluated result with no dissent.

The T14 assumption-register read has no filter/omission parameters and returns every lifecycle revision
of every `ASSUMPTION`, `CONSTRAINT`, and `UNCERTAINTY` in deterministic kind/logical-id/version/id order.
It composes direct graph evidence/dependents, recommendations and unresolved Critique handoff heads. Exact
constraint formalizations and latest persisted symbolic evaluations are public; `SAT`/`UNSAT`/`UNKNOWN`
map to `PROCEED`/`BLOCK`/`DEFER`, while missing formalization/evaluation is explicit `DEFER`. All identifiers
are public and missing or cross-tenant sessions are hidden as `404`.

The T14 decision-explanation read has no filter/omission parameters. It composes the latest persisted
consensus by `(round,id)`, exact JSON-aware explanation, rank/id-ordered recommendations, all alternatives,
authoritative register and Critique handoff data, and selected-alternative provenance. Required sections
remain present for `NO_CONSENSUS_RESULT` and `EXPLANATION_UNAVAILABLE`. Numeric values carry explicit
kind/version/caveat metadata, weakest-evidence rationale uses recorded facts only, and public IDs plus
tenant-hidden `404` are mandatory.

T11-01 formalisation writes require `Idempotency-Key`; all current-head lifecycle writes additionally
require `If-Match`. Reads expose derived `validation_status` and `enforceable`. Only an exact revision with
successful deterministic validation plus explicit human confirmation is `VALIDATED`/enforceable. The
legacy constraint payload `formal_status` is non-authoritative, and no solver outcomes exist in T11-01.

## 6. Port contract index

| Port | Defining method(s) | Phase |
| --- | --- | --- |
| `LLMProvider` | `generate`, `capabilities` | 2 |
| `WorkflowEngine` | T4-01: typed `start`, diagnostic `describe`, `health`, `close`; T4-04 adds typed controls | 4 |
| `WorkflowWorker` | lifecycle-only `run`, `shutdown`; definitions supplied by worker composition | 4 |
| `EventBus` | `publish`, `subscribe`, `read_from` | 1, 4 |
| `AgentRuntime` | `run_turn(context)` | 6 |
| `ReasoningStrategy` | `propose(context)` | 6 |
| `EffectiveMembershipStore` | `membership(workspace, session, round)` | 6 |
| `CoordinatorPolicyStore` | membership lock/history plus durable session/agent ceilings and usage | 6 |
| `ConsensusStrategy` | `evaluate` | 9 |
| `ConvergenceStrategy` | `evaluate` | 9 |
| `SymbolicReasoner` | `evaluate`, `check_consistency` | 11 |
| `SimulationEngine` | `run` | 8 |
| `Retriever` | `retrieve` | 5 |
| `Reranker` | `rerank` | 5 |
| `VectorStore` | `upsert`, `query`, `delete_namespace` | 1, 5 |
| `MemoryProvider` | `read`, `write`, `promote`, `expire` | 5 |
| `MetricPlugin` | `compute` | 13 |
| `MCPToolProvider` | `list_tools`, `invoke` | 15 |
| `ObjectStore` | `put`, `get`, `presign`, `delete` | 1 |
| `SecretProvider` | `resolve`, `store`, `redact` | 1, 2 |
| `AccessTokenVerifier` | `verify` → trusted workspace principal | 1 |
| `SandboxExecutionProvider` | `execute` | 8, 15 |
| `RealtimeGateway` | `publish`, `subscribe` | 4 |
| `ReasoningGraphStore` | `add_node`, `add_edge`, `trace_backward`, `subgraph` | 3, 10 |
| `CritiqueResponseStore` | `lock_response`, request/result get/add | 7 |

Full signatures, semantics, failure modes and idempotency expectations:
[../docs/PORTS.md](../docs/PORTS.md).

T14-01 exposes the existing `subgraph` operation as authenticated
`POST /api/v1/graph/subgraph`. Its structured body uses public session/root IDs, radius `0..5`, optional
closed edge filters, page size `1..200` and an opaque query-bound cursor. The response translates all graph,
artifact, session and workspace IDs to public forms and preserves deterministic ordering, `truncated` and
`next_cursor`. It adds no repository, persistence or migration.

## 7. Synchronization checklist (run at every phase exit)

- [ ] Every contract in §3 exists as a Pydantic model with `schema_version`.
- [ ] Every `event_type` in §4 is emitted by at least one code path or marked planned.
- [ ] Authored OpenAPI matches the implemented auth policy, envelope, error codes and status semantics.
- [ ] No secret material appears in any schema, example, log line or error body.
- [ ] `docs/API_CONTRACTS.md`, this file and `docs/API.md` updated in the same commit.
- [ ] Any breaking change has a migration note and a bumped `schema_version`.
- [ ] Port signatures in `docs/PORTS.md` match `backend/app/ports/*` exactly.

## 8. Current status

The Phase 1 HTTP foundation is executable: `/health`, `/ready`, `/metrics`, the problem envelope, bearer
verification port, verified workspace principal, and deny-by-default route RBAC exist. Only the two
probe routes are public; generated API documentation is disabled. The default verifier intentionally
accepts no tokens until a production IdP adapter is configured. OpenAPI validates, its three paths and
15 error codes are checked against backend sources, and `frontend/src/api/types.ts` regenerates with no
diff. Domain entity contracts above remain design-level and land with their owning phase (2+).

