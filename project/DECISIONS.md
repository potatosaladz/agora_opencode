# Decisions

**Purpose:** the running log of choices that are *not* architecture-level (those are ADRs) but that a
reader needs in order to not re-litigate them. Newest first.
**Rule:** a decision that changes who may commit an artifact, adds a stateful service, or moves a trust
boundary belongs in [../docs/adr/](../docs/adr/README.md), not here.
**Numbering:** `D-01 … D-19` here are *process and scope* decisions. Technical decisions below the ADR
threshold (`D-021` upward) live in [../memory-bank/decisions.md](../memory-bank/decisions.md); the two
ranges never overlap.

## Format

```text
D-nn · date · decision (one line) · status: accepted | superseded by D-mm | open
Context  — what forced it
Choice   — what was decided, and why this and not that
Impact   — documents and phases affected
```

---

## Accepted

| ID | Date | Decision | Impact |
| --- | --- | --- | --- |
| D-19 | 2026-09-05 | T4-01 is a typed client-only `WorkflowEngine` boundary: worker registration stays in worker composition; draft creation remains `POST /sessions` → `201`; T4-02 adds separate `POST /sessions/{id}/start` → `202`; PostgreSQL session status remains authoritative and Temporal status is diagnostic | [../docs/PORTS.md §2](../docs/PORTS.md), [../docs/API.md §4.1](../docs/API.md), [../docs/adr/ADR-001](../docs/adr/ADR-001-postgres-source-of-truth.md) |
| D-01 | 2026-09-04 | Documentation is the normative source; code conforms to docs, and where they disagree both are wrong until one is fixed | all of Phase 0 |
| D-02 | 2026-09-04 | Phase 0 stops at documentation. No `backend/`, `frontend/`, migrations, compose files or tests are generated before architecture approval | [../memory-bank/activeContext.md](../memory-bank/activeContext.md) §4 |
| D-03 | 2026-09-04 | The feasibility gate lives in the coordinator, implemented once, and no consensus strategy may bypass or disable it | [../docs/consensus-formalism/README.md](../docs/consensus-formalism/README.md) |
| D-04 | 2026-09-04 | Strategy files are named by strategy id (`weighted.md`), not by a `*-consensus.md` suffix | consensus-formalism index |
| D-05 | 2026-09-04 | The hash chain is described as **tamper-evident**, never as *immutable*; the platform cannot make claims about a database it administers | [../docs/AUDITABILITY.md](../docs/AUDITABILITY.md), [../docs/adr/ADR-019](../docs/adr/ADR-019-append-only-event-ledger.md) |
| D-06 | 2026-09-04 | No single composite score is ever presented as the quality of a recommendation; profiles and frontiers instead | [../docs/METRICS.md](../docs/METRICS.md) |
| D-07 | 2026-09-04 | Model-generated text is never evidence. `SYNTHETIC` trust level carries weight 0.0 in every strategy | [../docs/EPISTEMIC_MODEL.md](../docs/EPISTEMIC_MODEL.md) |
| D-08 | 2026-09-04 | Phase numbering is defined once by the roadmap in [../README.md](../README.md) and [PLAN.md](PLAN.md); every `Phase:` field in every document must match it | fixed in T0-11 |
| D-09 | 2026-09-04 | Research-track items are scheduled in Phase 16 and never appear in an MVP phase's dependency graph | [PLAN.md](PLAN.md) sequencing |
| D-10 | 2026-09-04 | `project/` holds state and plans; `memory-bank/` holds durable memory; `docs/` holds the specification. A fact lives in exactly one of the three and is linked, not copied | repository layout |
| D-11 | 2026-09-04 | The `WorkflowEngine` port gets an `inmemory` adapter so Phase 1 can run before Temporal lands in Phase 4. Additive, not a change to ADR-003 | [../docs/adr/ADR-003](../docs/adr/ADR-003-temporal-durable-workflow.md) |
| D-12 | 2026-09-04 | Codename *Agora* is cosmetic and non-load-bearing; it may be renamed at any time without architectural impact | root README |
| D-13 | 2026-09-04 | **Phase 0 approved by the project owner** ("continue" on 2026-09-04). The T0-12 gate is closed and Phase 1 implementation is authorised | [TASKS.md](TASKS.md) T0-12, [PLAN.md](PLAN.md) Phase 1 |
| D-14 | 2026-09-04 | Toolchain verified on the development host rather than assumed; where a documented command does not work on Windows it is recorded with its workaround, not silently adapted | [../memory-bank/techContext.md](../memory-bank/techContext.md) §6 |
| D-15 | 2026-09-04 | `api`, `workflow-worker`, `reasoning-worker`, `rag-worker`, `simulation-worker` and `mcp-gateway` are **deployment roles over a single `backend/` package**, not separate packages or repositories. One import tree, one lockfile, one test suite; entrypoints and Dockerfile build args select the role. This follows [techContext.md §3](../memory-bank/techContext.md) and prevents six copies of every port drifting apart | [../docs/ARCHITECTURE.md §2.1](../docs/ARCHITECTURE.md), `backend/` layout |
| D-16 | 2026-09-04 | The `services/*/contracts/*.py` path in [API_CONTRACTS.md §2](../docs/API_CONTRACTS.md) is read as forward-looking. Generated Python DTOs land in `backend/app/contracts/` until a second deployable package genuinely needs its own | Phase 1 layout; docs drift logged as E-01 |
| D-17 | 2026-09-05 | Phase 3 is split into T3-00…T3-09; T3-00 reconciles the conflicting design contracts before runtime code. Phase 3 implements the FR-301 taxonomy and required session/ledger/graph-write prerequisites, not every entity assigned to later phases | [PLAN.md](PLAN.md) Phase 3, [TASKS.md](TASKS.md) |
| D-18 | 2026-09-05 | Phase 3 freezes exactly 14 artifact kinds in one versioned envelope; opinion is `Position`, hypothesis is a typed `Claim`, and `Fact` uses opaque source references until Phase 5. Draft session creation is synchronous and Temporal-free; ledger order comes from a locked per-session head and hashes use RFC 8785 JCS over the exact DATA_MODEL preimages | [../docs/DATA_MODEL.md](../docs/DATA_MODEL.md) §§5–6, 9, 11; [../docs/adr/ADR-019-append-only-event-ledger.md](../docs/adr/ADR-019-append-only-event-ledger.md) |

## Open questions

Each must be answered before the phase that needs it. An unanswered question that blocks a phase is a
blocker, not a detail.

| ID | Question | Needed by | Current lean |
| --- | --- | --- | --- |
| Q-1 | Which two or three evaluation task domains does the first experiment suite use? | Phase 16 | policy analysis, engineering trade-off, clinical-adjacent (no diagnosis); Phase 5 uses a synthetic mechanics corpus per D-034 |
| Q-2 | **Resolved:** agents may bind distinct LLM configurations; the agent definition stores `llm_config_id` | Phase 2 | implemented in `5034e7b` |
| Q-3 | Is human-in-the-loop a role in the RBAC model or a separate principal type? | Phase 4 | separate principal: a human is not a permission set |
| Q-4 | What is the retention period for the ledger, and who authorises deletion? | Phase 13 | 7 years, ADMIN-only, deletion itself is an event |
| Q-5 | Does `CONDITIONAL_CONSENSUS` require explicit human acceptance to complete a session? | Phase 9 | yes, recorded as a first-class event |
| Q-6 | **Deferred production choice:** Phase 2 proved portability with two distinct OpenAI-compatible endpoints and the mock; second-vendor credentials remain operational follow-up, not a Phase 3 blocker | Phase 2 / deployment | no vendor selected |
| Q-7 | Is multi-tenancy a launch requirement or a Phase 17 concern? | Phase 1 | RLS is designed for it from day one; the UI may expose one tenant first |

## Rejected without an ADR

| Idea | Why it did not reach ADR status |
| --- | --- |
| Store the reasoning graph in Neo4j | ADR-007 already decides the store; a second graph engine was never seriously proposed |
| Use LangGraph for orchestration | the coordinator must own authority (ADR-013); a graph library would own it instead |
| Emit a single "quality score" per recommendation | forbidden by D-06; it is the fastest way to make a wrong answer look finished |
| Let the orchestrator LLM decide when consensus is reached | forbidden by ADR-013 and by the anti-pattern list; it is the core failure the design exists to prevent |
