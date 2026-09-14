# Phase 6 Acceptance Contract

**Version:** 1.0 · **Status:** frozen for T6-00 · **Phase:** 6
**Requirements:** FR-108, FR-203, FR-204, FR-206, FR-208…FR-211, NFR-009; automatic execution of the FR-103
decomposition contract

<!-- trace: FR-103, FR-206 -->
## 1. Boundary

Phase 6 turns pinned declarative agent definitions into coordinator-mediated, typed proposals. It
adds domain-expert reasoning behavior, not new authority: agents and the orchestrator may propose;
only deterministic application policy may allocate artifact identities, validate references, commit
artifacts, append ledger events, or advance workflow state.

Phase 6 includes:

- automatic decomposition into existing versioned `PROPOSITION` artifacts;
- strict `AgentRuntime` and `ReasoningStrategy` ports over the Phase 4 agent-turn activity;
- the five policy-analysis expert definitions and their pinned prompt artifacts;
- sealed independent round-1 assessment, deterministic fan-out/commit ordering, and abstention;
- typed orchestrator routing proposals with deterministic accept/reject policy;
- pre-round-1 agent-set changes and recorded mid-session injection;
- per-session and per-agent token/cost enforcement;
- complete output attribution and a deterministic 20-logical-agent acceptance fixture.

Phase 6 excludes Critic behavior and revision rounds (Phase 7), simulation (Phase 8), consensus
(Phase 9), graph traversal (Phase 10), metric catalogue and replay manifests (Phase 13), and
real-domain comparative experiments (Phase 16). W-2 therefore does not block this phase.

<!-- trace: FR-208, FR-209, FR-210, NFR-009 -->
## 2. Executable contract choices

### Agent runtime and strategy

`AgentRuntime` is a stateless application boundary. It resolves one pinned definition, invokes the
selected versioned `ReasoningStrategy`, and returns a typed execution result containing the proposal bundle.
T7-05 added this result envelope to preserve provider/accounting metadata; deterministic Phase 6 strategies
are normalized to metadata-free, zero-accounting results. `ReasoningStrategy` consumes a
complete immutable context and produces proposals; neither port writes PostgreSQL, signals Temporal,
publishes NATS messages, or calls another agent.

The Phase 4 `AgentTurnRunner` is a prerequisite activity implementation, not the Phase 6 runtime
port. Phase 6 composes it behind the new ports rather than duplicating provider, prompt-digest, raw
trace, or usage-accounting logic.

### Evidence disposition

Every proposed `POSITION` carries exactly one closed disposition:

- `CITED`: `evidence_ids` is non-empty and every ID resolves to an eligible evidence artifact;
- `NO_EVIDENCE`: `evidence_ids` is empty and the position remains explicitly unsupported.

`NO_EVIDENCE` is not an evidence artifact and never occupies an evidence UUID field. On commit, the
coordinator copies the disposition into hash-covered envelope metadata and the ledger payload. The
existing Phase 3 `PositionPayload.evidence_ids` schema remains unchanged. Missing disposition,
`CITED` with an empty list, `NO_EVIDENCE` with IDs, or an unresolved/fabricated ID fails validation
before any artifact write.

### Sealed assessment and mediation

Round 1 `ASSESS` inputs contain the problem, session objectives and constraints, the acting agent's
own definition and authorized knowledge, and no artifact or output from another agent. Agents have no
peer transport. The coordinator fans out logical turns through the shared worker pool, then commits
accepted bundles in stable pinned-agent order rather than completion order.

### Attribution and budgets

Each accepted output records agent definition ID and version, strategy name and version, provider
model, prompt reference and digest, round, phase, turn ID, correlation/causation IDs, raw call artifact
reference, UTC commit timestamp, and token/cost usage. Session budget checks happen before dispatch and
after durable usage accounting. A breached ceiling produces the existing explicit
`BUDGET_EXHAUSTED` termination reason; it cannot become an empty round or silent skip.

<!-- trace: FR-108, FR-203, FR-204, FR-211 -->
## 3. Requirement disposition

| Requirement | Phase 6 proof |
| --- | --- |
| FR-108 | pre-round replacement and mid-session injection are authorized, ledgered, and reflected only in later dispatches |
| FR-203 | 20 logical agents execute through bounded shared workers with no per-agent process or container |
| FR-204 | five distinct pinned domain-expert definitions and prompt digests produce schema-valid fixtures |
| FR-205 | Phase 7; Critic role remains outside this phase |
| FR-206 | orchestrator emits proposals only; a direct state mutation attempt fails |
| FR-207 | inherited Phase 4 coordinator authority remains unchanged |
| FR-208 | architecture/layering and runtime tests expose no agent-to-agent channel |
| FR-209 | round-1 assessment rejects unsealed or cross-agent-visible context |
| FR-210 | persisted output and event assertions cover every attribution field listed above |
| FR-211 | deterministic 20-agent fixture completes within configured worker and budget bounds |
| NFR-009 | token and USD ceilings are checked against durable usage and terminate explicitly |

Automatic decomposition closes the Phase 6 behavior deferred by the FR-103 clarification while the
already implemented Phase 3 row continues to own proposition representation and persistence.

## 4. Exit evidence

Phase 6 exits only when:

1. every emitted position validates and has one valid evidence disposition;
2. a fabricated evidence ID yields no artifact, graph projection, or success event;
3. sealed-assessment, no-peer-channel, stable-order, orchestrator-authority, injection, attribution,
   budget, and 20-agent fixtures pass;
4. five shipped expert definitions pass with the deterministic mock provider;
5. full inherited backend, frontend, contract, migration, link, traceability, Compose, and exact-SHA
   remote CI gates pass.
