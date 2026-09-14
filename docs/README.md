# Documentation Index

**Baseline:** Phase 0 architecture · **Last updated:** 2026-09-06
**Status:** approved as D-13; implementation status is tracked in `project/CURRENT_STATE.md`

This directory is the normative specification. Code must conform to it; when code and
docs disagree, both are wrong until one of them is fixed.

## Document conventions

| Marker | Meaning |
| --- | --- |
| **MUST / MUST NOT** | hard requirement; violating it blocks the phase exit gate |
| **SHOULD** | required unless a written exception exists in `project/DECISIONS.md` |
| **MAY** | genuinely optional |
| *(research)* | explicitly out of MVP scope; must not leak into core code |
| `§n` | section reference within the same file |

Every document opens with **Version**, **Last reviewed**, **Status** and links to its
companion documents. Terminology is defined once, in
[STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) and
[CONSENSUS_MODEL.md](CONSENSUS_MODEL.md), and reused everywhere else. Anti-patterns are
recorded in [ANTI_PATTERNS.md](ANTI_PATTERNS.md) with the document that forbids them.

## Reading order

**New to the project (about 30 minutes)**

1. [../README.md](../README.md) — what this is and is not
2. [ARCHITECTURE.md](ARCHITECTURE.md) — the eight diagrams and the three invariants
3. [MVP_BOUNDARY.md](MVP_BOUNDARY.md) — what we build first and what we refuse
4. [REQUIREMENTS.md](REQUIREMENTS.md) — testable requirements
5. [../memory-bank/activeContext.md](../memory-bank/activeContext.md) — current state

**Implementing the backend**

[DATA_MODEL.md](DATA_MODEL.md) → [PORTS.md](PORTS.md) →
[API_CONTRACTS.md](API_CONTRACTS.md) → [API.md](API.md) →
[STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) →
[REASONING_GRAPH.md](REASONING_GRAPH.md) → [AGENT_MODEL.md](AGENT_MODEL.md) →
[AGENT_PROTOCOLS.md](AGENT_PROTOCOLS.md) → [TESTING.md](TESTING.md) →
[EXTENDING.md](EXTENDING.md)

**Consensus, metrics, research**

[CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) → [consensus-formalism/](consensus-formalism/) →
[METRICS.md](METRICS.md) → [EXPERIMENTATION.md](EXPERIMENTATION.md) →
[REPRODUCIBILITY.md](REPRODUCIBILITY.md) → [RESEARCH_NOTES.md](RESEARCH_NOTES.md) →
[NEURO_SYMBOLIC.md](NEURO_SYMBOLIC.md) → [MARL_MODEL.md](MARL_MODEL.md)

**Security and operations**

[SECURITY.md](SECURITY.md) → [THREAT_MODEL.md](THREAT_MODEL.md) →
[MCP_SECURITY.md](MCP_SECURITY.md) → [DEPLOYMENT.md](DEPLOYMENT.md) →
[DOCKER_SWARM.md](DOCKER_SWARM.md) → [OBSERVABILITY.md](OBSERVABILITY.md)

## Inventory

### Core architecture

| Document | Normative for |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | service boundaries, state ownership, eight diagrams, authority split |
| [REQUIREMENTS.md](REQUIREMENTS.md) | functional and non-functional requirements, IDs, verification |
| [DATA_MODEL.md](DATA_MODEL.md) | tables, columns, constraints, indexes, migrations |
| [PORTS.md](PORTS.md) | port signatures, semantics, adapter obligations |
| [API.md](API.md) | HTTP surface, resources, status codes, streaming |
| [API_CONTRACTS.md](API_CONTRACTS.md) | payload schemas, event types, versioning |
| [ORCHESTRATION_POLICY.md](ORCHESTRATION_POLICY.md) | bounded activity retries/timeouts, stable operation IDs, dead-letter and checkpoint semantics |
| [MVP_BOUNDARY.md](MVP_BOUNDARY.md) | in-scope / out-of-scope, scope-change protocol |

### Reasoning model

| Document | Normative for |
| --- | --- |
| [STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) | artifact taxonomy, evidence rules, terminology |
| [REASONING_GRAPH.md](REASONING_GRAPH.md) | node and edge types, traversal, provenance |
| [AGENT_MODEL.md](AGENT_MODEL.md) | agent definition, roles, lifecycle, versioning |
| [AGENT_PROTOCOLS.md](AGENT_PROTOCOLS.md) | interaction protocol, envelopes, rounds |
| [CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) | consensus subsystem, outcomes, explanations |
| [MARL_MODEL.md](MARL_MODEL.md) | agents-as-policies view, trajectories, reward design |
| [NEURO_SYMBOLIC.md](NEURO_SYMBOLIC.md) | neural/symbolic split, formalization safety |
| [EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md) | belief, justification, uncertainty semantics |
| [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md) | ingestion, indexing, retrieval, namespaces |
| [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) | memory tiers, promotion, decay |
| [SIMULATION_ARCHITECTURE.md](SIMULATION_ARCHITECTURE.md) | engines, specs, validation, sandboxing |

### Quality, trust, research

| Document | Normative for |
| --- | --- |
| [METRICS.md](METRICS.md) | metric catalogue, profiles, no-single-score rule |
| [EXPERIMENTATION.md](EXPERIMENTATION.md) | experiments, ablations, comparisons |
| [REPRODUCIBILITY.md](REPRODUCIBILITY.md) | manifests, pinning, replay, determinism limits |
| [AUDITABILITY.md](AUDITABILITY.md) | audit records, queries, retention |
| [EXPLAINABILITY.md](EXPLAINABILITY.md) | explanation objects and views |
| [TRACEABILITY.md](TRACEABILITY.md) | backward and forward chains, impact analysis |
| [PHASE3_ACCEPTANCE.md](PHASE3_ACCEPTANCE.md) | T3-08 walkthrough, verification layers and observed gates |
| [PHASE5_ACCEPTANCE.md](PHASE5_ACCEPTANCE.md) | T5-09 baseline, FR-401–409 disposition and pending exit gates |
| [PHASE6_ACCEPTANCE.md](PHASE6_ACCEPTANCE.md) | T6-00 authority, agent runtime, evidence, mediation and budget contract |
| [PHASE7_ACCEPTANCE.md](PHASE7_ACCEPTANCE.md) | T7-00 Critic, response, immutable resolution, revision and explanation-handoff contract |

### Security and operations

| Document | Normative for |
| --- | --- |
| [SECURITY.md](SECURITY.md) | authN/authZ, secrets, data protection, SDLC controls |
| [THREAT_MODEL.md](THREAT_MODEL.md) | assets, trust boundaries, STRIDE, mitigations |
| [MCP_SECURITY.md](MCP_SECURITY.md) | tool allowlists, injection, approval gates |
| [DEPLOYMENT.md](DEPLOYMENT.md) | environments, configuration, migration, backup |
| [DOCKER_SWARM.md](DOCKER_SWARM.md) | stacks, networks, secrets, scaling, HA limits |
| [OBSERVABILITY.md](OBSERVABILITY.md) | secure logs, Prometheus metrics, OpenTelemetry lifecycle and verification |
| [TESTING.md](TESTING.md) | test tiers, determinism, contract tests, gates |

### Guidance and research record

| Document | Normative for |
| --- | --- |
| [EXTENDING.md](EXTENDING.md) | adding agents, strategies, metrics, adapters |
| [ANTI_PATTERNS.md](ANTI_PATTERNS.md) | forbidden designs and how to detect them |
| [RESEARCH_NOTES.md](RESEARCH_NOTES.md) | open questions, literature, hypotheses |
| [adr/](adr/) | 20 architectural decisions with rejected alternatives |
| [consensus-formalism/](consensus-formalism/) | per-strategy formal specifications |

## Maintenance rules

1. A change that alters behaviour must change the document that specifies it.
2. New terminology is added to `STRUCTURED_REASONING.md` before it is used elsewhere.
3. New architectural choices require an ADR; reversals supersede the old ADR rather than
   editing it.
4. Every phase exit runs the consistency checklist in
   [../project/CURRENT_STATE.md](../project/CURRENT_STATE.md).
5. Documents never claim implemented behaviour. Status lines say *design*, *implemented*
   or *verified*, and only `memory-bank/progress.md` may assert the last two.
6. Cross-links are relative. A broken link is a build failure once the docs linter lands
   in Phase 1.

