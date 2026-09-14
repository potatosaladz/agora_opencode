# Collective Reasoning Platform (working codename: **Agora**)

> A research-grade, production-oriented platform for **structured collective reasoning
> and formal consensus among heterogeneous AI agents**.

The platform is **not** an LLM chatbot, a group-chat application, a LangChain wrapper,
a majority-voting system, or an orchestrator LLM that summarizes other LLM outputs.

It exists to investigate a single question:

> **Can heterogeneous agents — with different expertise, objectives, evidence,
> assumptions, risks, uncertainty and constraints — construct a defensible collective
> recommendation, and can the platform formally explain when, why and to what extent
> consensus is or is not achieved?**

---

## Core design commitments

| Commitment | What it means concretely |
| --- | --- |
| Structured reasoning, not transcripts | Claims, evidence, assumptions, risks, uncertainty, objectives, constraints, alternatives and critiques are first-class, versioned, machine-readable entities. |
| Epistemic discipline | LLM output never silently becomes `FACT` or `EVIDENCE`. Evidence requires provenance. Consensus history never auto-promotes to knowledge. |
| Deterministic control, semantic suggestion | A deterministic Workflow Coordinator owns state, ordering, retries and consensus invocation. The Orchestrator LLM only *proposes*; policy decides. |
| Pluggable consensus | Consensus is a versioned research subsystem behind `ConsensusStrategy`. No algorithm is hard-coded into platform semantics. |
| Explainable backward, reconstructable forward | Every recommendation traces to claims → evidence → sources, and every session reconstructs from an append-only event ledger. |
| Disagreement is data | Minority positions, unresolved conflicts and infeasible alternatives are preserved and surfaced, never summarized away. |
| Provider independence | LLM, vector store, object store, event bus, workflow engine, symbolic reasoner, simulation engine and consensus strategy are all adapters behind ports. |

---

## Repository layout

```text
.
├── README.md                  ← you are here
├── CHANGELOG.md               ← human-readable change history
├── memory-bank/               ← durable, agent-facing project memory
├── project/                   ← fast-recovery planning + state + handoff
├── docs/                      ← normative architecture & research specs
│   ├── adr/                   ← Architecture Decision Records
│   └── consensus-formalism/   ← required formal docs per consensus plugin
├── backend/                   ← Python application and container image
├── docker-compose.yml         ← development stack
└── frontend/                  ← React + strict TypeScript operational skeleton
```

Phases 0 and 1 are complete. Backend, frontend, authored contracts, development Compose stack, and
gating CI exist; GitHub Actions run `33923240340` provides remote Phase 1 acceptance. See
[project/CURRENT_STATE.md](project/CURRENT_STATE.md).

---

## Run the development stack

```bash
cp .env.example .env        # fill all three local-only values
docker compose up --build --wait
curl http://localhost:8000/ready
# UI: http://localhost:3000
docker compose down         # add -v only when intentionally deleting local data
```

Published ports bind to `127.0.0.1` only. PostgreSQL migrations and MinIO bucket creation run as
idempotent one-shot jobs before the backend starts. Never commit `.env`.

---

## Where to start reading

1. [memory-bank/projectbrief.md](memory-bank/projectbrief.md) — mission, scope, non-goals.
2. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — all eight architecture diagrams.
3. [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — requirement catalogue with MVP classification.
4. [docs/MVP_BOUNDARY.md](docs/MVP_BOUNDARY.md) — what is and is not in the MVP.
5. [docs/PORTS.md](docs/PORTS.md) — the twenty extension-point contracts.
6. [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — entities and storage responsibilities.
7. [docs/CONSENSUS_MODEL.md](docs/CONSENSUS_MODEL.md) — consensus abstraction and outcomes.
8. [docs/adr/](docs/adr/) — the fixed architectural decisions.
9. [project/HANDOFF.md](project/HANDOFF.md) — for whoever continues this work.

---

## Recovery protocol (mandatory every session)

Context **will** be lost eventually — window exhaustion, IDE restart, model swap,
provider failure, or a two-week pause. Documented project state is therefore treated
as being **as important as source code**.

**Before** touching anything, read in this order:

```text
memory-bank/projectbrief.md   memory-bank/architecture.md   memory-bank/techContext.md
memory-bank/activeContext.md  memory-bank/progress.md       memory-bank/tasks.md
memory-bank/decisions.md      memory-bank/errors.md         memory-bank/api-contracts.md

project/CURRENT_STATE.md  project/PLAN.md  project/TASKS.md
project/DECISIONS.md      project/HANDOFF.md
```

```bash
git status
git log --oneline -10
```

Then determine: current phase → last completed task → active task → unresolved
decisions → known errors → last passing tests → next logical step.
**Do not modify code until the current state is understood.**

**After** every significant unit of work: run the relevant tests, then update
`memory-bank/activeContext.md`, `memory-bank/progress.md`, `memory-bank/tasks.md`,
`project/CURRENT_STATE.md`, `project/TASKS.md`, `CHANGELOG.md`, ADRs if architecture
changed, `memory-bank/errors.md` if a significant error occurred, and
`project/HANDOFF.md`.

**Never leave the repository in an undocumented state.**

---

## Development discipline

Work incrementally. The whole platform is never generated in one operation. Every
phase must end with something that is:

```text
BUILDABLE · TESTABLE · DOCUMENTED · RUNNABLE · RECOVERABLE
```

A small correct increment is always preferred over a large speculative one.

When forced to choose between **more features** and **clear abstractions, durable
state, traceability and testability** — choose the second.

---

## Roadmap at a glance

| Phase | Deliverable | Status |
| --- | --- | --- |
| 0 | Requirements, architecture, contracts, ADRs, MVP boundary | **Complete — approved (D-13)** |
| 1 | Project foundation: FastAPI + React skeletons, infra, health, auth skeleton | **Complete** |
| 2 | LLM provider abstraction + agent registry | **Complete** |
| 3 | Structured reasoning model + versioning + event ledger | **Complete** |
| 4 | Durable orchestration (Temporal) + live event stream | **Complete** |
| 5 | RAG + memory namespaces | **In progress — T5-09 local exit candidate** |
| 6 | Domain expert reasoning | **Complete** |
| 7 | Critic + revision loop | **In progress — T7-00 contract frozen** |
| 8 | Simulation | Not started |
| 9 | Baseline consensus engine | Not started |
| 10 | Reasoning graph + traceability | Not started |
| 11 | Neuro-symbolic (Z3) | Not started |
| 12 | MARL environment (definition, not training) | Not started |
| 13 | Trustworthiness: metrics, audit, replay, manifest | Not started |
| 14 | Full UI | Not started |
| 15 | MCP gateway + security | Not started |
| 16 | Research extensions | Not started |
| 17 | Swarm + hardening | Not started |

Details: [project/PLAN.md](project/PLAN.md).

---

## Anti-patterns (non-negotiable)

The platform must never:

- implement agents as chat personas, or reduce reasoning to a chat transcript;
- represent consensus as text majority voting, or let the Orchestrator LLM decide consensus;
- expose private LLM chain-of-thought, or treat LLM output as verified evidence;
- auto-promote session history to factual knowledge, or use LLM confidence as probability;
- hard-code one LLM provider, vector store, consensus algorithm, MARL library or symbolic reasoner;
- couple business logic to FastAPI, or use Redis as a persistent source of truth;
- mount the raw Docker socket into general services, or run one container per logical agent;
- claim stateful HA merely because `replicas > 1`;
- train complex MARL before defining the environment;
- force consensus, hide minority opinions, or silently resolve conflicting hard constraints;
- invent scientific validity for experimental metrics;
- store secrets in source code, skip tests because a feature is experimental,
  or continue development without updating project state.

Full list: [docs/ANTI_PATTERNS.md](docs/ANTI_PATTERNS.md).

---

## Status

**Phase 7 — Critic and revision loop complete.** T7-00 through T7-08 are complete. Final Phase 7 SHA
`25914b48e1c5140279720d1a4dfb66483cf744a3` passed all six jobs in GitHub Actions run
[`34667037521`](https://github.com/potatosaladz/agora/actions/runs/34667037521), including the complete
52-test live integration suite. See
[project/CURRENT_STATE.md](project/CURRENT_STATE.md).

