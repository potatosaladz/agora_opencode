<!-- trace: FR-206 -->
# ADR-013: Coordinator holds authority; the orchestrator only proposes

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 4
**Requirements:** FR-201 … FR-212, FR-601, NFR-003, NFR-006

## Context

An LLM orchestrator is attractive: it can read the state of a deliberation and decide, flexibly, what
should happen next. It is also non-deterministic, un-auditable in its reasoning, and unable to
guarantee that a rule — feasibility before ranking, sealed first round, budget limits — is ever
obeyed. A pure rule engine has the opposite problem: brittle in the face of unusual sessions.

## Decision

Split the roles. The **orchestrator** (which may be an LLM, a heuristic, or a learned policy) proposes
the next action. The **coordinator** — deterministic code inside the durable workflow — decides, and
its decision is an event. No policy invariant lives in the orchestrator.

## Consequences

**Positive.** Every hard rule is testable and every deviation is recorded. The orchestrator can be
replaced, ablated or trained without touching correctness, which is exactly what the MARL research
track needs ([MARL_MODEL.md §2](../MARL_MODEL.md)). Audit answers "why did this happen" with a
decision event naming the rule that fired.

**Negative.** The coordinator's rule set is the system's real personality, and it takes judgement to
keep it small. Flexibility is capped by what the coordinator permits — a creative orchestrator can be
throttled by policy.

**Neutral.** Refusals of proposals become first-class data, which turns out to be interesting in
itself.

## Alternatives considered

| Option | Why not |
| --- | --- |
| LLM orchestrator with authority | cannot guarantee FR-602 or FR-209; unauditable termination |
| Rules only | brittle, and forecloses the learned-policy research question entirely |
| Both, authority unclear | the worst option: an invariant that sometimes applies is worse than none |

## Links

[ARCHITECTURE.md §3](../ARCHITECTURE.md) · [AGENT_PROTOCOLS.md](../AGENT_PROTOCOLS.md) ·
[CONSENSUS_MODEL.md §1](../CONSENSUS_MODEL.md) · [AUDITABILITY.md §3](../AUDITABILITY.md)
