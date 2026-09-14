# ADR-019: Append-only hash-chained event ledger

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 3
**Requirements:** FR-301 … FR-305, NFR-003, NFR-006

## Context

The platform's distinguishing claim is that a past recommendation can be interrogated. That requires a
record that cannot be quietly edited — including by the operators, including by a bug that "corrects"
an earlier row.

## Decision

`reasoning_events` is append-only: `UPDATE` and `DELETE` are revoked from every application role and
rejected by trigger. A per-session `session_ledger_heads` row is locked and incremented inside the
committing transaction; rollback therefore consumes no sequence and committed `ledger_seq` values are
gapless. The ledger, not EventBus or NATS, assigns this only ordering key.

Actor classes are exactly `HUMAN`, `AGENT`, `SERVICE`, `POLICY`. Each row stores mandatory
`prev_hash`, `payload_hash` and `event_hash`, forming a per-session chain. Canonicalization and the
complete hash preimage are normative in [DATA_MODEL.md §11.0](../DATA_MODEL.md). Sequence 1 uses the
declared zero hash sentinel. A retrying event id is idempotent only if the complete preimage matches;
a mismatch is an integrity error. Daily anchoring remains Phase 13 work, not a Phase 3 dependency.

## Consequences

**Positive.** "Has anything changed since it was written" becomes a query (audit Q8). Replay is
possible because the record of what happened is the thing that happened. Corrections are additive and
attributable, so a mistake becomes data.

**Negative.** The table only grows; partitioning and archival policy are mandatory, not optional
([DATA_MODEL.md §15](../DATA_MODEL.md)). No in-place fixes means a bad write is corrected by a compensating
event, which is more verbose than an update. Chain verification adds a hash per write.

**Neutral.** Every projection (graph, metrics, search index) is derived from the ledger, so a
projection can be dropped and rebuilt — a freedom that most systems give up without noticing.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Mutable rows plus an audit trigger | the trigger can be disabled by the same role that writes the row |
| Soft deletes with `deleted_at` | still allows an `UPDATE` that rewrites history |
| External log service as truth | a second consistency domain, and the ledger needs to join with artifacts |
| Event sourcing replacing current-state tables | adopted for events, rejected for state: reads need current state, so projections exist alongside |

## Links

[AUDITABILITY.md](../AUDITABILITY.md) · [REPRODUCIBILITY.md](../REPRODUCIBILITY.md) ·
[DATA_MODEL.md §11](../DATA_MODEL.md) · [ADR-001](ADR-001-postgres-source-of-truth.md)
