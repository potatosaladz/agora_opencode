# Auditability

**Version:** 1.4 · **Status:** design; ledger, retrieval, T5-08 memory-history and Phase 13 audit subsets implemented
**Storage:** `reasoning_events` (append-only ledger), `retrieval_attempts` and memory promotion/lifecycle
facts, `access_log` and `audit_anchors` (implemented subsets)
([DATA_MODEL.md §11](DATA_MODEL.md)) · **Requirements:** FR-301 … FR-305, NFR-006, NFR-010 ·
**ADR:** [ADR-019](adr/ADR-019-append-only-event-ledger.md)

## 1. The three questions

An auditable system answers these without reconstruction or guesswork:

1. **What happened, in what order?** — the ledger.
2. **Who or what made it happen?** — actor on every event, no exceptions.
3. **Who saw what?** — the access log, including the reads nobody acted on.

A design that answers only (1) is a log, not an audit trail. Most systems stop there.

<!-- trace: NFR-006 -->
## 2. The ledger

| Property | Mechanism |
| --- | --- |
| Append-only | `REVOKE UPDATE, DELETE` on `reasoning_events`; a trigger rejects any `UPDATE` |
| Total order per session | ledger append locks and increments `session_ledger_heads` inside the committing transaction |
| Tamper evidence | `prev_hash` + `event_hash` chain; a gap or rewrite breaks the chain |
| Daily anchor | Phase 13 writes each session-day's head hash to `audit_anchors` and external WORM storage |
| Completeness | every state change is either an event or derived from events; a column that changes without an event is a defect |
| Causality | `causation_id` / `session_id` / `round` place any event in the workflow |

Events are written in the same database transaction as the state they describe. There is no
window in which a fact exists without its record, and no record of a fact that does not exist
(NFR-006).

Activity retry exhaustion is itself auditable. Bootstrap and session-control workflows append
`ACTIVITY_DEAD_LETTERED` while atomically moving the lifecycle projection to `FAILED`. Its payload records
activity type, stable operation ID, Temporal retry state, and policy termination reason; it deliberately
omits exception messages and provider payloads. A caller-preallocated failure event ID makes replay exact,
and `causation_id` links control failures to the requested transition event. See
[ORCHESTRATION_POLICY.md](ORCHESTRATION_POLICY.md).

## 3. Actors

Every event carries `actor = {id, class}` where class ∈ `HUMAN`, `AGENT`, `SERVICE`, `POLICY`.

| Class | Examples | May commit |
| --- | --- | --- |
| `HUMAN` | reviewer, workspace admin | anything permitted by scope, including `FACT` and promotion |
| `AGENT` | an LLM agent turn | artifacts within its role; proposals only for status transitions |
| `SERVICE` | coordinator, retrieval, solver | deterministic derivations, evaluations, index writes |
| `POLICY` | budget guard, feasibility gate | blocks and terminations, never content |

`POLICY` exists so that "nobody decided this, the rule did" is a recorded fact rather than an
inference. A blocked action is an event too: audits of suppression matter more than audits of
action.

<!-- trace: FR-807 -->
## 4. Access logging

Reads are logged when they touch artifacts outside the reader's own session, knowledge entries,
audit exports, agent definitions with prompts, or cross-namespace retrieval results.

`access_log` records `principal_class`, `principal_id`, `actor_class`, `resource_kind`,
`resource_id`, `action`, `result`, `scope_ids`, `source_ip`, `trace_id`, `recorded_at`
([DATA_MODEL.md §11.1](DATA_MODEL.md)). Retrieval results are logged at chunk level, so "did this
person see this document" is answerable ([RAG_ARCHITECTURE.md §9](RAG_ARCHITECTURE.md)).

T13-02 implements the Phase 13 `access_log` substrate that answers Q7: caller-scoped, append-only,
forced-RLS rows for reads of `RECOMMENDATION` resources (`AuditResourceKind` / `AuditAction`).
Other kinds and actions are added by wiring without schema change.

Volume control: reads inside a session the principal participates in are sampled at a configured
rate, and the rate itself is recorded. Sampling never applies to writes, denials, exports or
cross-workspace attempts.

T5-06 implements retrieval-specific access evidence in `retrieval_attempts`. Each row records stable attempt
and trace IDs, principal class/ID, query hash, requested/searched namespace IDs, returned chunk IDs and
content hashes, result census, versions, outcome and degradation. It deliberately contains no query or chunk
Denials are appended before raising and successful reads before return. Expected-match zero results and
authorization/lexical/vector infrastructure failures append `RAG_FAILED`; ordinary zero-match results
remain successful only when caller did not declare an expected match. Audit append failure fails retrieval
closed. Forced RLS, revoked public mutation privileges and rejecting update/delete trigger make the table
append-only through application roles. General `access_log` remains the later broader contract.

T5-08 persists semantic-memory authority as append-only forced-RLS entry, promotion, evidence and lifecycle
facts. Deferred constraints prevent an entry without validated promotion and a promotion without evidence;
stale/archive transitions add facts rather than rewriting or deleting prior authority. General memory-read
access logging remains API/composition work.

<!-- trace: FR-903 -->
## 5. The eight questions

The audit application services (`app.application.audit`) answer each of these in one typed query,
for any session (Phase 14 exposes them over HTTP):

| # | Question | Path |
| --- | --- | --- |
| Q1 | Why is this claim in the record? | `ARTIFACT_COMMITTED` → `causation_id` → turn |
| Q2 | Who changed this epistemic status, and on what warrant? | revision writes (`ARTIFACT_COMMITTED` / `ARTIFACT_REVISED` / `ARTIFACT_WITHDRAWN`) with `actor`, `supersedes_id`, `warrant_artifact_ids` |
| Q3 | What did the agents see at round *n*? | lifecycle projection + bound agent definitions + round-filtered `AGENT_TURN_COMPLETED` |
| Q4 | Was a dissent suppressed? | every `consensus_results` round row carries all positions; absence is impossible |
| Q5 | Why did the session end? | terminal `session_lifecycles` state + last ledger event |
| Q6 | Which strategy and parameters produced this ranking? | `consensus_results.strategy_version` + `input_hash` |
| Q7 | Who accessed this recommendation before it was accepted? | `access_log` filtered by resource, bounded strictly before `recommendations.created_at` |
| Q8 | Has anything been altered since it was written? | `ChainVerificationService`: recompute each `audit_anchors` day-head from the ledger + `reasoning_ledger.verify` |

Q8 is what separates an audit trail from a history table, so verification is exposed on demand
through `ChainVerificationService.chain_integrity`; a nightly job that runs it and anchors each
session-day is infra follow-up.

## 6. Export bundle

`POST /audit/export` produces a signed, self-describing bundle:

```text
manifest.json      session id, time range, requester, purpose, bundle hash, signature
ledger.jsonl       every event in ledger_seq order
artifacts.jsonl    every committed artifact with payload and edges
metrics.jsonl      metric_values with versions and inputs_hash
provenance.csv     flattened claim → evidence → source table
replay/            manifest sufficient to re-run under REPLAY_STRICT
README.md          how to verify the chain and reproduce the session
```

Exports are logged, watermarked with the requester, and cannot include data the requester could
not read: the export runs under the caller's RLS context, not a privileged one.

## 7. Retention and legal hold

Retention defaults follow [DATA_MODEL.md §15](DATA_MODEL.md). A legal hold sets
`retention_exempt = true` and blocks archival and purge jobs for that session. Holds are `POLICY`
events naming the actor who set them; releasing a hold is as auditable as imposing one.

## 8. Limits, stated plainly

| Limit | Consequence |
| --- | --- |
| Actions, not intentions | an actor can satisfy every rule and still be wrong; audit shows basis, not motive |
| Provider inference is not observable | the request and returned text are recorded, not what the model did with it (NFR-011) |
| Anchoring assumes the anchor store survives | anchors go to two independent stores, so single-store compromise is detectable |
| Volume | high-cardinality read logging is sampled; §4 states exactly where |
| Audit is not oversight | a trail nobody reads is decoration — hence HO-01 and HO-04 in [METRICS.md](METRICS.md) |

## 9. Related

[TRACEABILITY.md](TRACEABILITY.md) · [REPRODUCIBILITY.md](REPRODUCIBILITY.md) ·
[EXPLAINABILITY.md](EXPLAINABILITY.md) · [SECURITY.md](SECURITY.md) ·
[DATA_MODEL.md §11](DATA_MODEL.md) · [ORCHESTRATION_POLICY.md](ORCHESTRATION_POLICY.md)
