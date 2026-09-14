# API Contracts and the Frontend/Backend Boundary

**Version:** 1.2 · **Status:** design; Phase 7 through T7-04 internal Critic subset implemented
**Services:** `web-ui` ↔ `api-gateway` ([ADR-010](adr/ADR-010-react-vite-frontend.md),
[ADR-012](adr/ADR-012-clean-architecture-ports-adapters.md)) · **Endpoints:** [API.md](API.md)
**Requirements:** NFR-014, NFR-010, FR-101 … FR-110

## 1. What the boundary is for

The boundary exists so that the UI can be rewritten, the database can be re-sharded, and the
workflow engine can be swapped without any of them noticing. It is also the last place where the
platform's promises about permissions and provenance can be enforced before pixels.

Three rules hold it together:

- **B-1** The client sees **domain resources**, never database rows. No foreign keys, no join
  tables, no column names, no storage hints.
- **B-2** The client never decides what is permitted. It may hide a button; the server rejects
  the call. UI-side authorisation is a courtesy, not a control (NFR-010).
- **B-3** Every value the client renders as evidence, support, trust or confidence arrives with
  the metadata that says what kind of thing it is ([EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md)
  E-4). A bare number is a contract violation.

## 2. Contract artefacts

| Artefact | Location | Generated or authored | Consumed by |
| --- | --- | --- | --- |
| OpenAPI 3.1 document | `contracts/openapi.yaml` | authored, validated in CI | both sides |
| JSON Schemas for DTOs | `contracts/schemas/*.json` | authored | codegen, contract tests |
| Event schema | `contracts/events/*.json` | authored | SSE/WebSocket clients, replay tooling |
| TypeScript types | `frontend/src/api/types.ts` | **generated**, never hand-edited | web-ui |
| Python DTO models | `services/*/contracts/*.py` | **generated** | services |
| Error code list | `contracts/errors.yaml` | authored | both sides, docs |

Codegen runs in CI; a diff between the committed generated files and a fresh generation fails
the build. This is the only mechanism that keeps a hand-written client honest.

<!-- trace: FR-305 -->
## 3. Resource envelope

Phase 3 exposes resources only through `/api/v1/sessions`, `/api/v1/sessions/{id}`,
`/api/v1/sessions/{id}/artifacts`, `/api/v1/artifacts/{id}`, `/api/v1/artifacts/{id}/revisions` and
`/api/v1/artifacts/{id}/withdrawals`. Session creation returns `201` with a
fully bound `DRAFT` session. Phase 4 adds the separate idempotent
`POST /api/v1/sessions/{id}/start`, returning `202` after the durable engine accepts the start;
T4-02 owns that endpoint and its transaction boundary. API validates
RBAC, tenancy, ids, artifact invariants, idempotency and `If-Match`. UI does not infer permission or
epistemic state: it renders server-provided permissions and must show `unsupported: true` on claims.

Phase 10 adds `GET /api/v1/artifacts/{id}/provenance`. It uses the same read-role and tenant-hidden
`404` policy, exposes the exact root and ancestor artifact versions, and returns bounded graph traversal
metadata plus citation snapshots/current source status for EVIDENCE nodes.

`GET /api/v1/sessions/{id}` reads authoritative state from PostgreSQL's session lifecycle
projection. Temporal execution descriptions are operational diagnostics only and never overwrite
or replace that projection.

T4-04 adds authenticated, idempotent `pause`, `resume`, `cancel`, `human-input`, and deprecated
`terminate` compatibility operations. Each returns `202` after Temporal accepts a typed signal. The
workflow serially interprets it and is the only caller of the lifecycle transition activity; that
activity atomically updates PostgreSQL and appends the ledger event. `Idempotency-Key` plus request
content derives stable command/event identities, so HTTP replay, signal redelivery, and activity retry
cannot duplicate committed effects. `terminate` maps to typed cancellation.

T4-05 fixes activity execution semantics in
[ORCHESTRATION_POLICY.md](ORCHESTRATION_POLICY.md). Bootstrap and session-control failures that reach a
final Temporal `ActivityError` attempt an idempotent `ACTIVITY_DEAD_LETTERED` event and terminal `FAILED`
transition. Failure event IDs are allocated before workflow execution or signal delivery. Payload schema
version 1 contains `from`, `to`, and `failure` with `activity_type`, stable `operation_id`, Temporal
`retry_state`, and `termination_reason = "ACTIVITY_POLICY_EXHAUSTED"`. It excludes raw exception text and
provider data. PostgreSQL lifecycle plus ledger remain authoritative; Temporal status is diagnostic.

T4-06 streams `GET /api/v1/sessions/{id}/events/stream` as authenticated SSE. SSE `id` is the
PostgreSQL `ledger_seq`; `Last-Event-ID` takes precedence over `since`. NATS publication occurs only
after commit and wakes the gateway, which re-reads PostgreSQL before emitting. Transport loss therefore
cannot remove, reorder, or invent committed facts.

Every read resource is wrapped in a uniform envelope:

```jsonc
{
  "data": { "id": "art_01H…", "kind": "CLAIM", "attributes": { … } },
  "meta": {
    "version": 4,
    "workspace_id": "ws_01H…",
    "created_at": "2026-09-04T10:12:44Z",
    "owner": { "id": "agent_01H…", "class": "AGENT" },
    "lifecycle_status": "ACTIVE",
    "provenance": { "complete": false, "missing": ["source_reference"] },
    "permissions": ["artifacts:read", "artifacts:validate"],
    "trace": null
  }
}
```

- `meta.permissions` lists what the **caller** may do to this resource, computed server-side. The
  UI renders affordances from it; it does not infer them.
- `meta.provenance` is always present on artifacts. `complete: false` must be rendered, not
  swallowed ([EXPLAINABILITY.md](EXPLAINABILITY.md)).
- `meta.trace` is nullable in Phase 3. Phase 10 supplies the canonical "why" URL; the UI must not
  synthesize one while it is null.
- `data.kind` is one of the 14 FR-301 values. `meta.lifecycle_status` is exactly `ACTIVE`,
  `SUPERSEDED` or `WITHDRAWN`; kind-specific verification/review state stays in attributes.

## 4. Mutations

| Rule | Detail |
| --- | --- |
| Proposal vs commit | Phase 3 session/artifact creation commits synchronously and returns `201`; Phase 4 workflow-triggering operations return `202` |
| Idempotency | `Idempotency-Key` required on all `POST`s that create billable or ledgered state |
| Optimistic concurrency | revision/withdrawal `POST`s require `If-Match` with `meta.version`; mismatch → `409 VERSION_CONFLICT` with current version |
| No partial updates | Phase 3 has no `PATCH`; revision sends a complete replacement artifact and withdrawal only changes lifecycle status |
| Reason required | any mutation that changes epistemic status, resolves a critique, or overrides a recommendation requires a `reason` with at least one cited artifact id |

### 4.1 Phase 3 request ownership

`POST /api/v1/sessions` accepts exactly `problem_statement`, one or more
`agent_definition_ids`, one or more inline `objectives`, an inline `constraints` array (possibly
empty), and `budget = {max_rounds, max_tokens, max_usd, deadline_at?}`. Each objective/constraint is
an `ArtifactCreate` below. Workspace, user, ids, versions, lifecycle, hashes and timestamps are
server-owned. The response is the committed session with bound artifact ids.

`ArtifactCreate` accepts exactly `kind`, `payload`, `provenance`, `source_references`,
`parent_relationships`, optional `confidence`, and `metadata`. `POST .../revisions` accepts the same
complete content plus a non-empty `reason`; kind and logical id remain server-owned from the target.
`POST .../withdrawals` accepts exactly non-empty `reason` and `warrant_artifact_ids`. All three write
operations require `Idempotency-Key`; revision and withdrawal additionally require `If-Match`.

| Phase 3 operation | Allowed workspace roles |
| --- | --- |
| create session/artifact/revision/withdrawal | `ADMIN`, `RESEARCHER` |
| read session/artifact | `ADMIN`, `RESEARCHER`, `OPERATOR`, `VIEWER` |

Internal agent/service proposals call the same application use cases with explicit actor identity;
they do not acquire a human bearer role or bypass kind-specific commit rules.

### 4.2 T11-01 formalisation lifecycle

Formalisation resource paths use the stable logical `frm_...` identifier. `GET
/api/v1/formalizations/{formalization_id}` returns the current head unless an immutable `revision` query
selector is supplied, and returns an `ETag` equal to the selected revision number. All workspace roles may
read; only `ADMIN` and `RESEARCHER` may mutate. Tenant-hidden resources return the standard `404`.

Every formalisation `POST` requires `Idempotency-Key`. Revision, validation, confirmation, and rejection
also require `If-Match` for the current head; stale requests return `409 VERSION_CONFLICT`. Exact replay
returns the stored response with `Idempotency-Replayed: true`; a changed request under the same key is a
conflict. Creation and revision requests carry a closed typed AST, explicit symbol declarations, canonical
rendering, limitations, fidelity notes, and exact artifact-revision references.

`validation_status` is response-derived from immutable validation and human-decision facts:

- new revision or successful deterministic validation only → `CANDIDATE`;
- failed deterministic validation or explicit human rejection → `REJECTED`;
- successful validation for the exact AST plus human confirmation → `VALIDATED`.

`enforceable` is exactly `validation_status == VALIDATED`, never separately mutable. A new content revision
has no inherited validation or decision. `ConstraintPayload.formal_status` remains legacy metadata and is
not consulted. T11-01 performs no solver execution or result persistence.

### 4.3 Phase 6 orchestrator proposal boundary

T6-07 adds an internal application contract, not an HTTP endpoint. `OrchestratorProposal` accepts
only `DECOMPOSE`, `ROUTE`, or `ADVANCE_PHASE` recommendations and carries immutable workspace,
session, orchestrator-definition/version, turn, correlation, causation, round and phase pins.
Unknown fields and mutation/transition action names fail schema validation.

Coordinator-owned `CoordinatorProposalContext` supplies exact pins, current phase, eligible routing
definitions, policy actor, policy version and UTC decision time. Deterministic policy appends one
`ORCHESTRATOR_PROPOSAL_ACCEPTED` or `ORCHESTRATOR_PROPOSAL_REJECTED` ledger event with actor class
`POLICY`; accepted decisions explicitly carry `applied: false`. No proposal decision writes an
artifact, changes lifecycle state, signals a workflow, or dispatches an agent.

### 4.4 Phase 6 coordinator membership and budget boundary

T6-08 adds internal application contracts, not HTTP endpoints. An authorized caller supplies an immutable
membership request with workspace/session, `REPLACE | INJECT`, exact definition IDs, effective round,
human actor, correlation, reason, event ID and UTC timestamp. Policy permits replacement only before round
1 and injection only for the next round, requires an active workspace definition, prevents duplicate
logical-agent versions, and appends `SESSION_AGENT_REPLACED` or `SESSION_AGENT_INJECTED` atomically with
the append-only membership row. Retries with identical event content are idempotent.

`BudgetedAgentTurnDispatcher` reads durable session and per-definition token/USD totals before dispatch and
after provider accounting. A reached ceiling atomically transitions the lifecycle to `FAILED` with one
`BUDGET_EXHAUSTED` event containing scope, definition ID when applicable, usage and ceiling. It never turns
budget exhaustion into an empty proposal round.

### 4.4 Phase 7 Critic and response boundary

T7-01 adds internal application contracts, not HTTP endpoints. `CritiqueAssignment` is a frozen,
versioned coordinator-owned allowlist carrying workspace/session, Critic definition/version, turn,
correlation, causation, round and unique target artifact IDs. A Critic still returns the existing
`ProposalBundle`; `validate_critic_bundle` restricts that bundle to assigned, exact, non-duplicate
`CRITIQUE` proposals with `resolution: OPEN`. Non-Critique output, response-time resolution, position
confidence/disposition, evidence requests and simulation requests fail closed.

`CritiqueResponseProposal` pins responder definition/version, Critique id/version and target id/version.
Its disposition is exactly `ACCEPT | PARTIALLY_ACCEPT | REJECT_WITH_JUSTIFICATION | REVISE |
REQUEST_EVIDENCE | REQUEST_SIMULATION | ABSTAIN`. The strict field matrix allows only the one effect
required by that disposition: remaining issue, unique warrants, target revision proposal, evidence query,
or deferred simulation request. `ArtifactRevisionProposal` is replacement-only: unlike artifact creation it
may validate an existing `FACT` or `EVIDENCE` kind, but it has no identity, lineage or persistence authority.

T7-02 ships one workspace-scoped Critic definition and digest-pinned LF prompt through the existing
provider-neutral activity. T7-03 composes authorized reasoning context, bounded shared-pool dispatch and
durable budget checks; only a third consecutive completed empty Critic round emits `CRITIC_INACTIVE`,
while timeout remains `TURN_TIMEOUT`. T7-04 validates exact assignment pins before the existing atomic
proposal committer derives one hash-covered `ATTACKS` relationship and retry-stable graph edge for every
accepted Critique. The edge qualifier carries Critique type and severity. The shared agent commit path
requires the exact coordinator assignment, so callers cannot bypass target authorization. Agents cannot
provide graph-edge identity or bypass the transaction boundary.

T7-05/T7-06 add internal application contracts, not HTTP endpoints. `TurnExecutionResult` carries the
proposal plus complete provider/model/token/cost/raw-output metadata from activity-backed strategies;
deterministic strategies are normalized to an explicit metadata-free, zero-accounting result. A sealed
author-specific `REVISE` context and `CritiqueResponseCommand` must match every response pin. The
coordinator locks the response identity and current Critique/target heads, requires the target's `AGENT`
owner, validates active visible warrants and revision references, then maps every disposition to an
immutable Critique successor. `REVISE` additionally appends one same-kind, same-logical-id, same-owner target
successor. The coordinator—not model output—derives `ATTACKS`, `SUPERSEDES`, and `RESPONDS_TO`.

`critique_response_requests` stores the exact strict proposal, complete attribution, timestamp and content
hash; `critique_response_results` stores the explicit disposition outcome and committed effect IDs. Both are
append-only, forced-RLS records. They commit with artifact versions, graph edges and the retry-stable
`CRITIQUE_RESPONDED` event in one caller-owned transaction. An exact retry returns the prior result;
identity reuse with different content and stale heads fail closed. `REQUEST_EVIDENCE` records durable intent
with `EVIDENCE_REQUESTED`; it does not assert retrieval success. `REQUEST_SIMULATION` records
`SIMULATION_DEFERRED` and never executes Phase 8 work.

### 4.5 Phase 5 retrieval and memory boundary

`POST /sources` accepts exactly one acquisition arm: multipart bytes or an allowed server-fetch URL.
Both arms require `namespace`, `title`, `media_type`, declared SHA-256, and `Idempotency-Key`; optional
origin metadata includes publisher, source timestamp, citation and license. The response is `202` with
public source and operation IDs. Replays return the original IDs. Ingestion status is explicit:
`PROCESSING | READY | FAILED | RETRACTED`; parser warnings and index degradation are data, not success
masking. Source bytes are never returned by this API.

`POST /sessions/{id}/retrievals` requires a non-empty list of typed namespace refs, query, `final_k`,
token budget and `expected_match`. It returns `202`; the operation result carries query hash,
requested/searched namespaces, index/embedding/reranker versions, arm counts, degradation and ordered
candidate citations. Candidate text is untrusted. `NO_MATCH` is a successful result only when retrieval
ran correctly. Failed expected-match retrieval produces durable `RAG_FAILED`; authorization and
permission-filter failures fail closed without namespace census.

Each candidate citation includes source, document and chunk public IDs; source and chunk SHA-256;
exact locator/span offsets; source and retrieval timestamps; trust; and component scores. `POST
/sessions/{id}/evidence` accepts one such resolvable citation plus claim, relation, quote and weight,
attributes the verified human principal, and starts `UNVERIFIED`. It cannot classify model output as
evidence or fact.

`POST /knowledge/promotions` requires source artifact ID, target historical namespace, validator ID,
validation evidence, caveats and optional `review_by`. Only `knowledge:promote` may call it. Direct
semantic writes do not exist in HTTP. Retraction is additive through `POST /sources/{id}/retractions`;
old citations remain resolvable while new retrieval excludes the source.

| Phase 5 operation | Allowed workspace roles |
| --- | --- |
| ingest/retract source, promote knowledge | `ADMIN`, `RESEARCHER` |
| run retrieval, inject human evidence | `ADMIN`, `RESEARCHER`, `OPERATOR` |
| read source metadata/validated knowledge | `ADMIN`, `RESEARCHER`, `OPERATOR`, `VIEWER` subject to namespace grant |

## 5. Authentication and authorization

Only `GET /health` and `GET /ready` are public. Every other registered endpoint requires an
`Authorization: Bearer <token>` header. A successful verifier supplies a trusted principal containing
`subject`, `user_id`, `workspace_id`, and one canonical workspace role: `ADMIN`, `RESEARCHER`,
`OPERATOR`, or `VIEWER`.

Each protected route MUST declare its allowed roles in server-side policy metadata. Authentication is
evaluated before policy: missing, malformed, expired, invalid, or unconfigured token verification
returns `401 AUTH_REQUIRED` with `WWW-Authenticate: Bearer`; a valid principal with no route policy or
a role outside the route's allow-list returns `403 FORBIDDEN`. Client-supplied workspace or role values
never override the verified principal. Generated OpenAPI, Swagger UI, and ReDoc endpoints are disabled.

## 6. Error taxonomy

`application/problem+json`, always:

```jsonc
{ "type": "https://example.invalid/errors/provenance-missing",
  "title": "Provenance missing", "status": 422, "code": "PROVENANCE_MISSING",
  "detail": "evidence requires a non-empty source reference and locator",
  "instance": "/api/v1/sessions/ses_01H…/evidence",
  "trace_id": "req_01H…", "retryable": false }
```

| Code | HTTP | Retryable | Meaning |
| --- | --- | --- | --- |
| `VALIDATION_FAILED` | 400 | no | schema violation; `errors[]` lists JSON pointers |
| `UNKNOWN_FIELD` | 400 | no | strict mutation whitelist breached |
| `AUTH_REQUIRED` | 401 | no | missing or expired token |
| `FORBIDDEN` | 403 | no | scope or RLS denial |
| `COMMIT_FORBIDDEN` | 403 | no | principal class may not commit this transition (V-2) |
| `VERSION_CONFLICT` | 409 | no | `If-Match` mismatch |
| `IDEMPOTENCY_REPLAY` | 200 | — | key reused; original response returned |
| `NOT_FOUND` | 404 | no | absent **or** hidden by RLS — deliberately indistinguishable |
| `PROVENANCE_MISSING` | 422 | no | fact/evidence lacks required opaque source provenance; Phase 5 later resolves it |
| `BUDGET_EXCEEDED` | 402 | no | session or workspace budget spent |
| `RATE_LIMITED` | 429 | yes | `Retry-After` present |
| `PORT_UNAVAILABLE` | 503 | yes | an adapter failed; `degraded` names the port |
| `RAG_FAILED` | 503 | yes | retrieval unavailable, distinct from empty results (FR-409) |
| `WORKFLOW_UNREACHABLE` | 503 | yes | coordinator down; reads still served |
| `INTERNAL` | 500 | no | everything else; `trace_id` is the only handle |

Codes are additive. A code is never redefined, and never removed while a released client exists
(NFR-014).

## 7. Event contract

```jsonc
{ "ledger_seq": 42, "type": "ARTIFACT_COMMITTED", "ts": "2026-09-04T10:12:44Z",
  "actor": { "id": "agent_01H…", "class": "AGENT" },
  "session_id": "ses_01H…", "round": 3,
  "payload": { "artifact_id": "art_01H…", "kind": "CLAIM" },
  "schema_version": 1 }
```

- **EV-1** `ledger_seq` is monotonic per session and is the only ordering key. Clients MUST sort
  by it, not by `ts`.
- **EV-2** Delivery is at-least-once; consumers deduplicate on `ledger_seq`.
- **EV-3** `payload` carries ids, never nested bodies. Fetching a body is a separate,
  permission-checked read.
- **EV-4** A new event `type` is additive and must be ignorable by older clients. An unknown type
  MUST NOT crash a consumer — this is a required client test.
- **EV-5** `schema_version` increments only on a breaking change to an existing type, which then
  follows §8.
- **EV-6** The wire view deliberately maps ledger names: `event_type → type`,
  `recorded_at → ts`, `payload_schema_version → schema_version`, and the actor columns to nested
  `actor`. Hashes are verified server-side and omitted from the ordinary event stream.

## 8. Compatibility and deprecation

| Change | Class | Process |
| --- | --- | --- |
| Add optional field, add endpoint, add enum value on the *response* side | additive | ship |
| Add required request field | breaking | new version or a transitional default with a deprecation window |
| Remove or rename a field | breaking | deprecate → dual-write → remove |
| Change a field's meaning | **always breaking**, even if the type matches | forbidden without a version bump |

Deprecation mechanics: `Deprecation` and `Sunset` response headers, a `deprecated: true` entry in
the OpenAPI document, a dated row in [../CHANGELOG.md](../CHANGELOG.md), and a metric counting
calls per deprecated field. Removal happens no earlier than one minor release after the count
reaches zero.

## 9. Contract testing

| Test | Where | Asserts |
| --- | --- | --- |
| Schema conformance | CI, both sides | every response validates against `contracts/schemas/` |
| Consumer-driven contracts | CI | each UI screen's expectations recorded as a consumer pact; provider runs them |
| Golden files | CI | a fixed session fixture renders byte-stable JSON for the 12 primary endpoints |
| Error taxonomy | CI | every `code` in `errors.yaml` is reachable and documented, and vice versa |
| Event replay | CI | the ledger fixture replayed through the event contract yields the same `ledger_seq` ordering |
| Permission matrix | CI | each scope × endpoint combination returns the documented status, including `403` and `404` indistinguishability |
| Type generation | CI | generated TypeScript and Python match the committed artefacts |

The UI is forbidden from reading fields not present in the OpenAPI document; a strict build flag
makes an unknown field a compile error, which is what keeps §7 meaningful.

## 9. What must never cross the boundary

| Never | Because |
| --- | --- |
| Model chain-of-thought or raw completions | NFR-011; also unaccountable |
| Provider credentials, API keys, internal connection strings | FR-1005 |
| Database row shapes, foreign keys, internal ids that are not resources | B-1 |
| A composite quality score | FR-901 — there is no such field to send |
| A number without its `meta` (type, version, inputs, caveats) | NFR-019 |
| Suppressed dissent | FR-505/FR-506 — the minority report has no "omit" parameter |
| Server-side trust decisions pre-baked into the UI | B-2 |
| Prompt text as a user-visible explanation | [EXPLAINABILITY.md](EXPLAINABILITY.md) |

## 10. Related

[API.md](API.md) · [PORTS.md](PORTS.md) · [ARCHITECTURE.md §2](ARCHITECTURE.md) ·
[SECURITY.md](SECURITY.md) · [TESTING.md](TESTING.md) · [EXTENDING.md](EXTENDING.md) ·
[ORCHESTRATION_POLICY.md](ORCHESTRATION_POLICY.md)

