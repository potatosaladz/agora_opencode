# Durable Orchestration Policy

**Version:** 1.0 · **Status:** T4-05 implemented · **Last reviewed:** 2026-09-06
**Requirements:** FR-104 … FR-107, FR-207, NFR-001, NFR-020 · **ADRs:**
[ADR-001](adr/ADR-001-postgres-source-of-truth.md),
[ADR-003](adr/ADR-003-temporal-durable-workflow.md),
[ADR-019](adr/ADR-019-append-only-event-ledger.md)

## 1. Authority and delivery model

Temporal provides durable, at-least-once activity execution. It does not become the domain source of
truth. A session checkpoint is the PostgreSQL `session_lifecycles` row (`state`, `round`,
`last_event_id`) plus the corresponding hash-chained `reasoning_events` prefix. Temporal visibility is
diagnostic only.

Every retried activity receives byte-equivalent typed input. State-changing input carries an
API/workflow-preallocated event UUID; agent turns carry a workflow-preallocated `turn_id`. No activity
generates its own operation identity. The stable Temporal activity id is:

```text
{session_id}:{activity_type}:{idempotency_key}
```

The PostgreSQL transaction either commits the effect and its ledger event together or commits neither.
Exact event-ID replay returns the original result; reuse with different semantic content is an integrity
failure. Agent-turn call accounting uses `turn_id` as its caller-supplied call UUID and applies the same
exact-replay rule.

## 2. Declared policies

| Activity class | Attempt timeout | Total schedule budget | Attempts | Backoff | Heartbeat |
| --- | ---: | ---: | ---: | --- | --- |
| short PostgreSQL state/ledger commit | 15 s | 300 s | 10 | 1 s exponential ×2, capped at 30 s | none; transaction is short and atomic |
| LLM/agent turn | 120 s | 300 s | 3 | 1 s exponential ×2, capped at 30 s | timeout 30 s; emitted every 15 s |
| source ingestion | 300 s | 900 s | 3 | 1 s exponential ×2, capped at 30 s | timeout 30 s; emitted every 15 s |

`schedule_to_close` is the total retry budget. No activity relies on an SDK default or has unlimited
attempts. Future retrieval, simulation and symbolic activities MUST declare a reviewed policy before
registration; long work MUST heartbeat and respond to cancellation.

## 3. Failure taxonomy

| Source failure | Temporal type | Retry | Outcome after policy |
| --- | --- | --- | --- |
| `PermanentPortError`, invalid typed payload, illegal lifecycle transition, ledger integrity failure | `AGORA_PERMANENT_ACTIVITY_FAILURE` | no | bootstrap/control workflow dead-letters; other callers receive final failure |
| `TransientPortError` | `AGORA_TRANSIENT_ACTIVITY_FAILURE` | bounded | bootstrap/control workflow dead-letters if exhausted |
| unexpected activity exception | `AGORA_TRANSIENT_ACTIVITY_FAILURE` | bounded | bootstrap/control workflow dead-letters if exhausted |
| cancellation | Temporal cancellation | no translation | cancellation propagates; child task is canceled and drained |

Failure details expose only the exception class and, for a port error, the port name. Raw exception text,
provider payloads and secrets are not copied into Temporal history.

## 4. Dead-letter semantics

For implemented bootstrap and session-control workflow paths, “dead letter” means a durable
`ACTIVITY_DEAD_LETTERED` ledger event and terminal `FAILED` lifecycle transition, not a second message
queue. Agent-turn execution has bounded policy and idempotent call accounting, but is not yet dispatched
by this bootstrap workflow; its future caller MUST apply equivalent terminal handling. Schema-version-1
dead-letter payload contains:

```json
{
  "from": "RUNNING",
  "to": "FAILED",
  "failure": {
    "activity_type": "commit_session_control_transition",
    "operation_id": "{session_id}:{activity_type}:{idempotency_key}",
    "retry_state": "MAXIMUM_ATTEMPTS_REACHED",
    "termination_reason": "ACTIVITY_POLICY_EXHAUSTED"
  }
}
```

The failure event UUID is allocated before workflow execution or signal delivery. The event records no
unredacted exception message. Its `causation_id` points to the failed state event when one exists. The
workflow attempts this transition after Temporal reports the activity's final `ActivityError`, then
re-raises the original failure so Temporal diagnostics and PostgreSQL agree that execution did not
complete normally.

## 5. Checkpoint and recovery rules

1. Resume from the last committed PostgreSQL lifecycle/ledger checkpoint; never infer a domain state from
   an activity attempt or Temporal visibility.
2. A worker crash before commit causes a retry with the same operation identity.
3. A worker crash after commit but before acknowledgement causes exact replay and no duplicate effect.
4. `recorded_at` is assigned by the committing activity and excluded from event retry identity; all
   semantic event fields must match.
5. A conflicting identity is permanent and is dead-lettered; it is never overwritten.
6. NATS publication is downstream transport and cannot participate in checkpoint authority (T4-06).

Source ingestion applies the same authority rule outside session lifecycle. A caller-allocated operation
UUID binds the complete typed input hash. `knowledge_ingestion_operations` records attempt count plus
independent acquire/parse/embed/index checkpoints and safe failure taxonomy. A post-commit activity retry
returns the original source, document and chunk IDs; a conflicting retry is permanent. Original bytes
remain content-addressed in object storage, but PostgreSQL—not MinIO or Temporal visibility—owns progress.

Recovery tests that kill workers and force post-commit acknowledgement loss remain the T4-08 exit proof;
T4-05 fixes the policy and executable invariants they must verify.