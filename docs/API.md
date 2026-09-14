# API

**Version:** 1.0 · **Status:** design · **Base path:** `/api/v1`
**Service:** `api-gateway` ([ARCHITECTURE.md §2](ARCHITECTURE.md)) ·
**Boundary contract:** [API_CONTRACTS.md](API_CONTRACTS.md) · **Requirements:** FR-101 … FR-110,
NFR-007, NFR-010

## 1. Conventions

| Concern | Rule |
| --- | --- |
| Style | resource-oriented JSON over HTTPS; no GraphQL in MVP |
| Auth | `Authorization: Bearer <access token>`; scopes per §2 |
| Tenancy | derived from the token's `workspace_id`; never a request parameter (FR-109) |
| Idempotency | every state-changing call accepts `Idempotency-Key`; replay returns the original result |
| Concurrency | optimistic: `If-Match: <version>` on mutable resources, `409 CONFLICT` on mismatch |
| Pagination | cursor-based `?limit=&cursor=`, response carries `next_cursor`; max `limit` 200 |
| Time | RFC 3339 UTC everywhere |
| IDs | ULID strings prefixed by resource (`ses_`, `art_`, `evt_`) |
| Errors | RFC 9457 problem+json with a machine `code` from the taxonomy in [API_CONTRACTS.md §6](API_CONTRACTS.md) |
| Versioning | path version `/api/v1`; additive changes only within a version (NFR-014) |
| Latency | reads p95 ≤ 300 ms excluding LLM time (NFR-007) |

Writes never block on model inference. A call that triggers reasoning returns `202` with a
workflow handle, and the client follows the event stream.

## 2. Scopes

| Scope | Grants |
| --- | --- |
| `sessions:read` / `sessions:write` | view and create sessions, read rounds |
| `artifacts:read` / `artifacts:write` | view artifacts; propose artifacts |
| `artifacts:validate` | move epistemic status, confirm formalizations (FR-907) |
| `knowledge:promote` | promotion workflow (FR-406) |
| `agents:manage` | agent definitions, versions, budgets |
| `consensus:run` | trigger consensus evaluation and strategy comparison |
| `intervene:write` | human turns, overrides (FR-801) |
| `audit:read` | ledger, export, who-saw-what queries |
| `admin:config` | workspace settings, retention, thresholds |

A token carries the narrowest set that works; the UI requests scopes per screen rather than one
omnibus token.

## 3. Resource map

```text
/workspaces
  /agents                      /agent-definitions/{id}/versions
  /sessions                    /sessions/{id}/rounds/{n}
    /artifacts                 /artifacts/{id}/provenance
                               /artifacts/{id}/impact
    /propositions              /propositions/{id}/disagreement
    /evidence                  /evidence/{id}/verify
    /critiques                 /critiques/{id}/resolve
    /consensus                 /consensus/{id}/explain
    /recommendation            /recommendation/override
    /simulations               /simulations/{run_id}
    /metrics                   /metrics/profile
    /events            (SSE)   /events?since=<seq>
  /knowledge                   /knowledge/{id}/promotions
  /sources                     /sources/{id}/retract
  /experiments                 /experiments/{id}/runs
  /audit/export                /audit/access
/graph/paths                   /graph/subgraph
```

## 4. Endpoints

<!-- trace: FR-101 -->
### 4.1 Sessions and rounds

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `POST` | `/sessions` | atomically create a fully bound draft session | Phase 3: `201`; workflow start is Phase 4 |
| `POST` | `/sessions/{id}/start` | idempotently enqueue the bound draft for durable execution | Phase 4: `202`; T4-02 implementation |
| `GET` | `/sessions` | list, filter by state/agent/date | cursor |
| `GET` | `/sessions/{id}` | state, config, budget, phase | |
| `GET` | `/sessions/{id}/rounds/{n}` | full round detail | |
| `POST` | `/sessions/{id}/human-input` | typed human directive | idempotent; workflow emits `HUMAN_DIRECTIVE` |
| `POST` | `/sessions/{id}/pause` · `/resume` · `/cancel` | lifecycle | authenticated, idempotent Temporal signals; cancel is terminal and never deletes |
| `POST` | `/sessions/{id}/terminate` | legacy cancellation alias | deprecated compatibility path; maps to typed cancel |

Creation and execution are separate operations. `POST /sessions` remains a synchronous atomic
resource creation returning `201`; it never starts Temporal. The future start operation returns
`202` after Temporal accepts the idempotent start command. Session reads always return PostgreSQL
state; Temporal execution status is operational diagnostics, not an API lifecycle authority.
Control responses return `202` when Temporal accepts the signal and include the current PostgreSQL
projection. Clients read the session resource to observe the workflow-interpreted transition.

### 4.2 Artifacts and reasoning

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/sessions/{id}/artifacts` | filter by `kind`, `author`, `status` | |
| `POST` | `/sessions/{id}/artifacts` | propose an artifact | `201` only after coordinator commit |
| `GET` | `/artifacts/{id}` | payload, provenance, edges | |
| `POST` | `/artifacts/{id}/revisions` | create complete replacement version | `If-Match`; `201`; old row becomes `SUPERSEDED` |
| `POST` | `/artifacts/{id}/withdrawals` | withdraw without deleting | `If-Match`; reason required; `200` |
| `GET` | `/sessions/{id}/propositions` | normalized propositions | |
| `GET` | `/propositions/{id}/disagreement` | position vector | FR-606 |

### 4.3 Formalisations

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `POST` | `/formalizations` | create an immutable candidate revision | `201`; `Idempotency-Key`; exact source artifact revision and premises; public `frm_...` logical ID |
| `GET` | `/formalizations/{id}` | read the current head or `?revision=` history | all workspace roles; returns `ETag`, authoritative `validation_status`, and derived `enforceable` |
| `POST` | `/formalizations/{id}/revisions` | append a complete replacement revision | `201`; `Idempotency-Key`; `If-Match`; predecessor validation and decisions never carry forward |
| `POST` | `/formalizations/{id}/validations` | record deterministic AST validation | `201`; `Idempotency-Key`; `If-Match`; no solver execution |
| `POST` | `/formalizations/{id}/confirmations` | record human confirmation | successful exact-revision validation required; nonblank reason |
| `POST` | `/formalizations/{id}/rejections` | record explicit human rejection | nonblank reason; immutable fact |

Only `validation_status = VALIDATED` is enforceable. Validation success without confirmation remains
`CANDIDATE`; validation failure or human rejection is `REJECTED`. The legacy constraint payload
`formal_status` is not authoritative. T11-01 does not expose SAT/UNSAT/UNKNOWN or solver-result routes.

### 4.4 Evidence, sources, knowledge

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `POST` | `/sessions/{id}/retrievals` | retrieve candidates for a session | `202`; explicit non-empty namespace refs; result read from returned operation URL |
| `POST` | `/sessions/{id}/evidence` | attach human-selected evidence to a claim | `201`; human attribution; `422 PROVENANCE_MISSING` without resolvable source/document/chunk (FR-402, FR-407) |
| `POST` | `/evidence/{id}/verify` | transition verification state | FR-403; LLM principals receive `403 COMMIT_FORBIDDEN` (V-2) |
| `POST` | `/sources` | acquire and ingest a source | `202`; `Idempotency-Key`; explicit namespace; bytes or server-fetched URL, never both |
| `GET` | `/sources/{id}` | source metadata and processing state | original digest and object ref remain stable |
| `POST` | `/sources/{id}/retractions` | retract a source and create its impact report | `201`; `Idempotency-Key`; reason required; retraction, exact-version dependencies and `SOURCE_RETRACTED` outbox event commit atomically |
| `GET` | `/impact-reports/{id}` | read an immutable source-impact report | tenant-scoped; explicit `COMPLETE`/`INCOMPLETE` and truncation state; affected claims, alternatives, consensus results and recommendations |
| `GET` | `/knowledge` | search validated semantic memory | explicit namespace refs; stale state is visible (FR-406) |
| `POST` | `/knowledge/promotions` | promote a session artifact | `201`; `knowledge:promote`; validator, evidence and target namespace required |

Source ingest and retrieval operations are durable activities. Parser, chunker, embedder and indexer have
no public callback routes. Operation reads expose durable state and redacted warnings, never object-store
credentials, raw provider errors or unauthorized namespace existence.

### 4.5 Critique, consensus, recommendation

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/sessions/{id}/critiques` | filter by type, severity, state | |
| `POST` | `/critiques/{id}/resolve` | accept / rebut / reject with warrant | FR-508 |
| `POST` | `/sessions/{id}/consensus` | run a strategy | body names strategy + parameters |
| `GET` | `/sessions/{id}/consensus` | all results including strategy comparisons | never averaged (S-3) |
| `GET` | `/consensus/{id}/explain` | structured explanation + minority report | FR-609 |
| `GET` | `/sessions/{id}/recommendation` | recommendation with dissent, gaps, caveats | FR-505; the minority report is not optional |
| `POST` | `/recommendation/override` | human override | emits `OVERRIDE`, original preserved (FR-803) |

### 4.5 Simulation, metrics, graph, experiments, audit

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/sessions/{id}/simulations` | submit a spec; the validation report returns synchronously, the run is async |
| `GET` | `/simulations/{run_id}` | result bundle with convergence and sensitivity |
| `GET` | `/sessions/{id}/metrics/profile` | the metric profile — no composite score exists (FR-901) |
| `GET` | `/sessions/{id}/metrics` | raw `metric_values` with versions, inputs and caveats |
| `GET` | `/artifacts/{id}/provenance` | bounded backward reasoning ancestry plus canonical evidence citations and current source status |
| `POST` | `/graph/subgraph` | typed subgraph for a node set and depth |
| `POST` | `/graph/paths` | path between two artifacts |
| `POST` | `/experiments` | define a comparison |
| `GET` | `/experiments/{id}/runs` | per-cell results |
| `POST` | `/audit/export` | signed export bundle, async |
| `GET` | `/audit/access` | who-saw-what query |
| `GET` | `/health` · `/ready` | liveness and readiness, unauthenticated |

## 5. Event stream

`GET /api/v1/sessions/{id}/events/stream?since=<seq>` — Server-Sent Events, the default transport
([ADR-016](adr/ADR-016-realtime-gateway-sse-first.md)).

```text
id: 00000000000000000000042
event: ARTIFACT_COMMITTED
data: {"session_id":"ses_01H…","artifact_id":"art_01H…","kind":"CLAIM",
       "actor":"agent_01H…","ts":"2026-09-04T10:12:44Z","ledger_seq":42}
```

- `Last-Event-ID` on reconnect replays from the ledger; the stream is at-least-once and
  idempotent by `ledger_seq`.
- Events are the committed facts, never progress theatre. There is no "agent is thinking" event.
- Sensitive payload bodies are not streamed; clients fetch the artifact by id under their own
  permissions.
- WebSocket is available at `/ws/sessions/{id}` for the graph view; SSE remains the contract and
  WebSocket is a transport optimisation over the same event set.

## 6. Illustrative exchange

```http
POST /api/v1/sessions
Idempotency-Key: 7c1f…
{ "task": { "question": "Should we subsidise rooftop PV in region X?",
            "alternatives": ["flat subsidy", "tariff", "do nothing"],
            "constraints": ["within fiscal ceiling", "no regressive incidence"] },
  "agent_set": ["ag_analyst_v3","ag_econ_v2","ag_critic_v4","ag_legal_v1"],
  "protocol": "deliberative", "consensus_strategy": "constraint_aware",
  "budget": { "max_rounds": 6, "max_tokens": 400000 } }
→ 201 { "session_id": "ses_01H…", "status": "DRAFT", "version": 1 }
```

```http
GET /api/v1/consensus/cns_01H…/explain
→ 200 {
  "outcome": "CONDITIONAL_CONSENSUS",
  "ranking": [ { "alternative": "tariff", "support": 0.71 },
               { "alternative": "flat subsidy", "support": 0.44 } ],
  "feasibility": { "status": "SAT", "validated_formalizations": 4, "unknown": 1 },
  "conditions": [ { "assumption_id": "asm_01H…", "text": "grid capacity is not binding",
                    "dependents": 7 } ],
  "minority_report": [ { "agent": "ag_critic_v4", "position": "OPPOSE",
                         "warrant": ["art_01H…"], "would_change_mind": "evidence on incidence" } ],
  "unresolved_critiques": [ { "id": "crt_01H…", "type": "CAUSAL_OVERCLAIM", "severity": "HIGH" } ],
  "evidence_gaps": [ "no source on regional grid headroom" ],
  "strategy": { "id": "constraint_aware", "version": "1.1.0",
                "parameters": { "agreement_threshold": 0.66, "abstain_allowed": true } },
  "input_hash": "sha256:…", "caveats": [ "support is not probability" ] }
```

## 7. Rate limits and backpressure

| Class | Limit | On breach |
| --- | --- | --- |
| Reads | 600 req/min per principal | `429` with `Retry-After` |
| Session creation | 30/hour per workspace | `429`, queued above that with a visible position |
| LLM-triggering writes | governed by the session budget | `402 BUDGET_EXCEEDED` |
| Audit export | 5/day | `429` |

## 8. Related

[API_CONTRACTS.md](API_CONTRACTS.md) · [PORTS.md](PORTS.md) · [SECURITY.md](SECURITY.md) ·
[DATA_MODEL.md](DATA_MODEL.md) · [ARCHITECTURE.md §2](ARCHITECTURE.md)

