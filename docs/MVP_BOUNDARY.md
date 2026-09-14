# MVP Boundary

**Version:** 1.0 · **Status:** agreed
**Purpose:** decide what "done" means for the MVP, and keep the research track from colonising it.

## 1. The MVP in one sentence

A team runs a multi-agent deliberation on a hard, contested question and can defend the resulting
recommendation under interrogation: every claim traces to evidence, every disagreement is
visible, every constraint is checked, and the whole session replays.

If a feature does not serve that sentence, it is not MVP.

## 2. In / out

| Area | In MVP | Out of MVP *(research or later)* |
| --- | --- | --- |
| Agents | 3–6 heterogeneous LLM agents, versioned definitions, roles incl. Critic | learned agent policies, agent self-modification, MARL training |
| Protocol | sealed round 1, critique, rebuttal, revision | market mechanisms, delegation chains, voting with proxies |
| Structure | full artifact taxonomy, normalized propositions | automatic ontology learning |
| RAG | hybrid retrieval, six namespaces, permission pre-filter, provenance on every hit | GraphRAG, learned fusion, multimodal embeddings |
| Graph | Postgres property graph, 12 edge types, impact traversal | graph neural features, learned edge weights |
| Symbolic | Z3 for linear arithmetic + UF, unsat cores, assumption retraction | non-linear, induction, probabilistic logic |
| Simulation | deterministic, Monte-Carlo, system dynamics in a sandbox | agent-based, calibration, optimisation loops |
| Consensus | `weighted`, `evidence_weighted`, `constraint_aware` + feasibility gate | deliberative, Bayesian pooling, prediction markets |
| Metrics | the catalogue in [METRICS.md](METRICS.md) | composite scores — **never**, in any phase (FR-901) |
| UI | session view, graph explorer, provenance drill-down, dissent panel, intervention | mobile, dashboards, collaboration chat |
| Deployment | Docker Swarm, single-region, manual failover | Kubernetes, multi-region, autoscaling |
| Trust | append-only ledger, audit export, RBAC, RLS | external attestation, formal verification of the platform |
| Memory | four tiers, explicit promotion | automatic learning from history |
| Experiments | replay, A/B of strategies and agent sets, seeds | hyperparameter search at scale |

## 3. Acceptance criteria

The MVP is done when all of these pass. Each is testable; none is a judgement call.

| # | Criterion | Verification |
| --- | --- | --- |
| A-1 | A 4-agent session on a real contested task reaches a terminal consensus outcome | scripted end-to-end test |
| A-2 | Every committed `CLAIM` either has a `SUPPORTS`/`OPPOSES` edge or is rendered as unsupported | graph query returns zero unlabelled claims |
| A-3 | `EP-02 provenance completeness = 1.0` for all cited evidence | metric assertion |
| A-4 | Retracting a source durably lists every dependent claim without mutating it | integration test (FR-408) |
| A-5 | A hard-constraint violation blocks the recommendation even when support is maximal | feasibility-gate test (FR-602) |
| A-6 | Solver `UNKNOWN` surfaces as unresolved, never as satisfied | property test (FR-708) |
| A-7 | Dissent appears in the API response with no parameter that omits it | contract test (FR-506) |
| A-8 | A session replayed from the ledger reproduces byte-identical artifacts | replay harness (NFR-003) |
| A-9 | Three consensus strategies on the same inputs produce three stored, comparable results | API assertion (S-3) |
| A-10 | A non-permitted principal cannot read another workspace's artifact through any path | RLS test suite (FR-109) |
| A-11 | A human intervention mid-session is recorded and changes the trajectory | end-to-end test (FR-801) |
| A-12 | No endpoint, DTO, UI component or DB column exposes a composite quality score | grep + schema + UI review (FR-901) |
| A-13 | Prompt-injection payload in a retrieved document cannot cause a tool call | red-team suite (FR-1003) |
| A-14 | The stack deploys and recovers from a killed worker on a single-node Swarm | chaos drill |

## 4. Non-goals for the MVP

| Non-goal | Why stated |
| --- | --- |
| Being right | the platform measures defensibility, not truth; a well-run session can reach a wrong conclusion on thin evidence, and must say so |
| Replacing the decision-maker | FR-801: humans decide, the platform shows the work |
| Maximising agreement | agreement is an outcome, never a target (DH-02) |
| Supporting every model | one OpenAI-compatible provider plus one local engine is enough to prove the abstraction (FR-206) |
| Benchmark leadership | the evaluation suite exists to compare configurations, not to win a leaderboard |
| General knowledge base | knowledge entries are promoted, validated outputs — not a wiki |

## 5. Scope-change protocol

1. Propose in [../project/PLAN.md](../project/PLAN.md) with the criterion it would improve.
2. Show what leaves if this enters — the table in §2 is zero-sum.
3. Record the decision in [../project/DECISIONS.md](../project/DECISIONS.md) and, if architectural,
   as an ADR.
4. Update this document, [docs/README.md](README.md) and `memory-bank/tasks.md` in the same commit.

A new ADR is required for: a new stateful service, a new trust boundary, a change to who may
commit an artifact, or any relaxation of §4.

## 6. Exit criteria for the research track

A research item moves into the MVP only when it has: a formal specification, an implementation
behind an existing port, an experiment showing it beats the current default on the evaluation
suite with ≥ 5 seeds, a metric that detects its failure mode, and a rollback that is configuration
only. Anything less stays a plugin.

## 7. Related

[REQUIREMENTS.md](REQUIREMENTS.md) · [RESEARCH_NOTES.md](RESEARCH_NOTES.md) ·
[../project/PLAN.md](../project/PLAN.md) · [EXTENDING.md](EXTENDING.md)
