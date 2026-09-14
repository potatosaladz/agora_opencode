# Project Brief

**Project:** Collective Reasoning Platform (working codename *Agora*)
**Classification:** research-grade, production-oriented platform
**Current phase:** Phase 0 — Requirements & Architecture
**Brief version:** 1.0 · **Last reviewed:** 2026-09-04

---

## 1. Mission

Build a modular multi-agent orchestration platform, deployed on Docker Swarm, for:

> **Structured collective reasoning and consensus formation among heterogeneous
> domain-specialist AI agents.**

Agents reason explicitly with structured, machine-readable entities — assessments,
propositions, claims, facts, evidence with provenance, assumptions, risks,
uncertainty, objectives, conflicting objectives, hard / soft / non-negotiable
constraints, alternatives, causal relationships, impacts, counterarguments,
criticisms, simulations, preferences, confidence, recommendations and unresolved
disagreements.

Reasoning is **never** reduced to a chat transcript.

## 2. The research question

Whether heterogeneous agents possessing different expertise, objectives, evidence,
assumptions, risks, uncertainty and constraints — including conflicting objectives —
can construct a **defensible** collective recommendation, and whether the platform can
**formally explain when, why and to what extent consensus is or is not achieved**.

The platform is not designed to make multiple LLMs agree.

## 3. What this system explicitly is NOT

| Misreading | Why it is wrong |
| --- | --- |
| An LLM chatbot | No free-form chat is the unit of state; artifacts are typed entities. |
| A group-chat application | Domain agents never talk to each other directly; all interaction is routed, logged and structured. |
| Several prompts talking to each other | Reasoning is versioned, constraint-checked and evidence-tracked. |
| A LangChain wrapper | No framework dependency in the domain layer; ports/adapters throughout. |
| A majority-voting system | Consensus is a pluggable formal subsystem over normalized propositions and alternatives, gated by hard-constraint feasibility. |
| An orchestrator LLM summarizing outputs | The orchestrator LLM only *proposes*; a deterministic coordinator decides. |

## 4. Primary users

- **Researchers** running controlled experiments (critic on/off, consensus algorithm A/B,
  LLM-only vs neuro-symbolic) over reproducible configurations and datasets.
- **Domain analysts / operators** configuring agents, objectives and constraints, and
  driving live reasoning sessions.
- **Decision makers** consuming executive explanations and recommendations.
- **Auditors / reviewers** tracing any recommendation back to original sources.

## 5. Non-negotiable design principles

Optimize for: modularity, extensibility, durability, traceability, explainability,
auditability, reproducibility, security, testability, scientific experimentation,
high availability, fault recovery, provider independence.

When forced to choose between *more features* and *clear abstractions, durable state,
traceability, testability* — choose the latter.

## 6. Scientific output obligation

Every completed session must be able to answer: what problem was evaluated; which
agents participated and what expertise each represented; which alternatives were
considered; what evidence was used; which assumptions were made; what risks were
identified; what uncertainty remained; which objectives conflicted; which hard
constraints applied; what claims were challenged; what changed after critique; which
simulations ran; which alternatives became infeasible; how consensus was calculated;
whether consensus was actually achieved; what minority opinions remain; why the
recommendation was selected; what questions remain open; and whether the result is
traceable, auditable and reproducible.

## 7. MVP in one sentence

Prove the architecture end-to-end: four heterogeneous agents, structured claims and
evidence, an orchestrator workflow, a critic loop, basic RAG, basic simulation,
baseline constraint-aware consensus, durable sessions surviving browser closure,
history, a basic provenance graph, basic metrics, and a central UI.

MVP success criteria (18 items) are enumerated in [../docs/MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md#9-mvp-demonstration-success-criteria).

## 8. Explicitly out of MVP scope

MARL policy training, formal epistemic logic as a runtime dependency, dedicated graph
databases, RDF/JSON-LD export, advanced consensus algorithms (Nash bargaining, belief
aggregation, MARL consensus), autonomous fine-tuning, and production stateful HA
topologies. These are Research Extensions or Future work.

## 9. Fixed technology decisions

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, asyncio, httpx /
OpenAI-compatible SDK abstraction; React + TypeScript + Vite with TanStack Query and
React Flow; Temporal (behind `WorkflowEngine`); NATS JetStream (behind `EventBus`);
PostgreSQL as system-of-record; pgvector (behind `VectorStore`); MinIO/S3 (behind
`ObjectStore`); Redis for ephemeral concerns only; graph stored in PostgreSQL (behind
`ReasoningGraphStore`); Z3 as the initial symbolic reasoner; Docker Swarm as the
deployment target (Compose for local development).

Rationale and rejected alternatives: [../docs/adr/](../docs/adr/).

## 10. Governance

Changes to this brief, to fixed technology decisions, or to any architectural
contradiction resolution require a new or revised ADR recorded in
[decisions.md](decisions.md) and [../project/DECISIONS.md](../project/DECISIONS.md).
