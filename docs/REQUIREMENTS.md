<!-- trace: NFR-009 -->
# Requirements

**Version:** 1.0 (Phase 0) · **Status:** approved design baseline (D-13)
**Traceability:** every requirement has an ID, a priority, an owning phase and a
verification method. Phase exit gates reference these IDs
([../project/PLAN.md](../project/PLAN.md)).

**Priority:** `P0` MVP-blocking · `P1` required for the research claim · `P2` valuable,
deferrable · `R` research track, explicitly outside MVP.
**Verification:** `T` automated test · `U` UI walkthrough · `M` metric threshold ·
`A` audit query · `D` documentary review at the phase gate.

<!-- trace: FR-101, FR-108 -->
## 1. Problem framing and sessions

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-101 | A user MUST be able to define a complex problem in natural language and open a reasoning session for it | P0 | 3 | U |
| FR-102 | A session MUST bind, at creation, to a problem statement, agent set, objective set, constraint set and resource budget | P0 | 3 | T |
| FR-103 | The system MUST decompose a problem into structured `Proposition` sub-questions, not prose | P0 | 3 | T |
| FR-104 | A session MUST be pausable, resumable, cancellable and restartable by a user | P0 | 4 | U |
| FR-105 | A session MUST continue to completion if the browser closes or the API restarts | P0 | 4 | T |
| FR-106 | Reopening a session MUST restore full state from PostgreSQL plus replay of missed events | P0 | 4 | U |
| FR-107 | Every session MUST terminate with exactly one explicit termination reason | P0 | 4 | T |
| FR-108 | A user MUST be able to change the agent set before round 1 and inject agents mid-session as a recorded event | P1 | 6 | U |
| FR-109 | Sessions MUST be isolated per workspace; no cross-workspace read of any artifact | P0 | 1 | T |

<!-- trace: FR-205 -->
## 2. Agents

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-201 | Agents MUST be declarative versioned records: identity, domain, objectives, constraints, knowledge namespaces, reasoning strategy, LLM config reference, tool permissions, budget | P0 | 2 | T |
| FR-202 | An agent definition referenced by a session MUST become immutable; changes create a new version | P0 | 2 | T |
| FR-203 | Agents MUST run as logical instances in a shared worker pool; one container per agent is forbidden | P0 | 6 | D |
| FR-204 | The platform MUST ship the five policy-analysis agents: fiscal, macroeconomic, social policy, infrastructure, risk | P0 | 6 | U |
| FR-205 | A Critic role MUST exist and MUST be able to attack any artifact type | P0 | 7 | T |
| FR-206 | An Orchestrator LLM MUST be able to propose routing and next actions and MUST NOT mutate platform state directly | P0 | 6 | T |
| FR-207 | The Workflow Coordinator MUST own all state transitions deterministically | P0 | 4 | T |
| FR-208 | Agents MUST NOT communicate with each other except through the coordinator | P0 | 6 | T |
| FR-209 | Initial assessments MUST be produced without cross-agent context | P0 | 6 | T |
| FR-210 | Every agent output MUST carry agent id, definition version, model, prompt version, round and timestamp | P0 | 6 | T |
| FR-211 | Agent count MUST scale to at least 20 logical agents per session within budget limits | P1 | 6 | M |

<!-- trace: FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, FR-308, FR-309, FR-310, FR-311 -->
## 3. Structured reasoning artifacts

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-301 | Reasoning MUST be typed artifacts: Claim, Fact, Assumption, Inference, Proposition, Evidence, Uncertainty, Risk, Impact, Objective, Constraint, Alternative, Position, Critique | P0 | 3 | T |
| FR-302 | Every artifact MUST be versioned; revision MUST create a new version linked by `SUPERSEDES` | P0 | 3 | T |
| FR-303 | No artifact MAY be destructively deleted; withdrawal sets status `WITHDRAWN` | P0 | 3 | T |
| FR-304 | Every Claim MUST declare supporting and opposing evidence references, possibly empty | P0 | 3 | T |
| FR-305 | A Claim with no evidence MUST render visibly flagged as unsupported | P0 | 3 | U |
| FR-306 | Propositions MUST store both the normalized form and the original natural-language statement | P0 | 3 | T |
| FR-307 | Objectives MUST be typed, weighted and permitted to conflict; conflicts MUST be representable | P0 | 3 | T |
| FR-308 | Constraints MUST be typed `HARD`, `SOFT` or `NON_NEGOTIABLE` and MUST be machine-evaluable | P0 | 3 | T |
| FR-309 | Uncertainty MUST carry a type (`EPISTEMIC`, `ALEATORIC`, `MODEL`, `MEASUREMENT`, `SEMANTIC`, `STRATEGIC`) and a distribution where available | P1 | 3 | T |
| FR-310 | Risks MUST carry probability, impact, uncertainty and affected objectives | P1 | 3 | T |
| FR-311 | Assumptions MUST be explicit, attributable and challengeable by the Critic | P0 | 3 | T |
| FR-312 | The data model MUST distinguish fact, claim, assumption, inference, opinion and hypothesis — not only in prompts | P0 | 3 | D |

<!-- trace: FR-102, FR-103, FR-312 -->
### 3.1 Phase 3 acceptance boundary (frozen)

- FR-101 is jointly owned: `POST /api/v1/sessions` and `GET /api/v1/sessions/{id}` are the
  backend contract; the Phase 3 UI supplies one accessible problem/session form and visibly renders
  unsupported claims. T3-08 verifies the full browser walkthrough. Durable execution and browser-close
  recovery remain Phase 4.
- FR-102 means a newly created `DRAFT` session atomically stores the original problem statement,
  pinned agent-definition ids, objective artifact ids, constraint artifact ids and resource budget.
  Missing or cross-workspace references reject the whole request.
- FR-103 means decomposition writes versioned `PROPOSITION` artifacts with original and normalized
  statements plus canonicalizer version. Phase 3 exposes create/read operations; automatic LLM
  decomposition belongs to Phase 6.
- FR-312 uses first-class `FACT`, `CLAIM`, `ASSUMPTION`, `INFERENCE` and `POSITION` artifacts.
  Opinion is `POSITION`; hypothesis is `CLAIM` with `claim_type = HYPOTHESIS`. These encodings are
  persisted and validated, not prompt conventions.
- Phase 3 evidence and facts carry opaque source provenance values. Phase 5 adds source, document and
  chunk resolution for FR-401…409; Phase 3 MUST NOT create foreign keys to those later-phase tables.

## 4. Evidence, RAG and knowledge

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-401 | The system MUST ingest PDF, DOCX, TXT, Markdown, CSV, XLSX, JSON and HTML | P0 | 5 | T |
| FR-402 | Evidence MUST carry provenance: source, document, page or section, chunk, content hash, retrieved timestamp, source timestamp, trust level | P0 | 5 | T |
| FR-403 | Evidence MUST carry a verification status; LLM-generated text MUST NOT be auto-classified as evidence or fact | P0 | 5 | T |
| FR-404 | Retrieval MUST be hybrid with reranking and MUST be permission-filtered before similarity scoring | P0 | 5 | T |
| FR-405 | Knowledge MUST be namespaced: global, workspace, domain, agent, session, historical | P0 | 5 | T |
| FR-406 | Promotion of session output into durable knowledge MUST require an explicit validation step | P0 | 5 | T |
| FR-407 | A user MUST be able to inject evidence manually, attributed to the human | P0 | 5 | U |
| FR-408 | Retracting a source MUST produce an impact report over every dependent claim | P1 | 10 | A |
| FR-409 | Retrieval failure MUST be recorded as `RAG_FAILED`, never as a silent empty result | P0 | 5 | T |

<!-- trace: FR-501, FR-502, FR-503, FR-504, FR-505, FR-506 -->
## 5. Critique and disagreement

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-501 | Critiques MUST be typed: `EVIDENCE_GAP`, `LOGICAL_FALLACY`, `HALLUCINATED_SOURCE`, `MEASUREMENT_ERROR`, `MODEL_MISUSE`, `CONSTRAINT_IGNORED`, `CONFLICT_OF_INTEREST`, `ALTERNATIVE_OMITTED`, `UNCERTAINTY_UNDERSTATED`, `CAUSAL_OVERCLAIM` | P0 | 7 | T |
| FR-502 | Every critique MUST carry severity and a target artifact reference | P0 | 7 | T |
| FR-503 | Agents MUST be able to respond `ACCEPT`, `PARTIALLY_ACCEPT`, `REJECT_WITH_JUSTIFICATION`, `REVISE`, `REQUEST_EVIDENCE`, `REQUEST_SIMULATION`, `ABSTAIN` | P0 | 7 | T |
| FR-504 | Unresolved critiques MUST appear in the final explanation, never be dropped | P0 | 7 | U |
| FR-505 | The platform MUST preserve dissenting positions, minority reports and unresolved disagreements | P0 | 9 | T |
| FR-506 | Suppressing a minority position MUST be impossible through the API | P0 | 9 | T |

<!-- trace: FR-604, FR-605, FR-609 -->
## 6. Consensus

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-601 | Consensus MUST be computed by a pluggable `ConsensusStrategy` behind a stable port | P0 | 9 | D |
| FR-602 | Hard-constraint feasibility MUST be evaluated before any ranking | P0 | 9 | T |
| FR-603 | An infeasible alternative MUST NOT be selectable regardless of score | P0 | 9 | T |
| FR-604 | Outcomes MUST include `FULL_CONSENSUS`, `PARTIAL_CONSENSUS`, `CONDITIONAL_CONSENSUS`, `PARETO_SET`, `NO_CONSENSUS`, `DEADLOCK`, `INSUFFICIENT_EVIDENCE`, `INFEASIBLE` | P0 | 9 | T |
| FR-605 | Every result MUST carry a `ConsensusExplanation`: algorithm, version, formula, weights, thresholds, per-agent contributions, derivation trace | P0 | 9 | T |
| FR-606 | Semantic disagreement MUST be assessed on structured propositions, not string equality | P0 | 9 | T |
| FR-607 | Conflicting objectives MUST produce a Pareto analysis rather than a forced single winner | P1 | 9 | T |
| FR-608 | Every strategy MUST have a formal document in `docs/consensus-formalism/` before it is selectable | P0 | 9 | D |
| FR-609 | Consensus support values MUST always be reported with the metric profile, never as a lone number | P0 | 13 | U |

## 7. Simulation and symbolic reasoning

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-701 | Agents MUST be able to request a simulation; the coordinator MUST run it as a durable activity | P0 | 8 | T |
| FR-702 | Simulation results MUST carry engine, engine version, spec hash, seed, run count, intervals, sensitivity, validity domain | P0 | 8 | T |
| FR-703 | Simulation output MUST be classified as evidence about the model, not evidence about the world | P0 | 8 | D |
| FR-704 | Untrusted simulation code MUST run through `SandboxExecutionProvider` with no network and bounded resources | P0 | 8 | T |
| FR-705 | Hard constraints MUST be evaluated by a symbolic reasoner returning `SAT`, `UNSAT` or `UNKNOWN` | P0 | 11 | T |
| FR-706 | Every violation MUST produce a trace: rule, natural-language origin, validation status, inputs, evaluation, verdict | P0 | 11 | T |
| FR-707 | A natural-language constraint MUST NOT become an enforceable rule without recorded validation | P0 | 11 | T |
| FR-708 | Solver `UNKNOWN` MUST be surfaced as unknown, never as satisfaction or violation | P0 | 11 | T |

## 8. Human intervention, audit, explanation

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-801 | A human MUST be able to pause, resume, inject evidence, amend constraints, modify objectives, request simulation or critique, request another round, reject a recommendation, override an outcome and cancel | P0 | 10 | U |
| FR-802 | Every human action MUST be an event with actor, timestamp and payload | P0 | 10 | A |
| FR-803 | Overrides MUST be labelled as overrides in every downstream view | P0 | 10 | U |
| FR-804 | The system MUST provide four explanation views: executive, expert, formal, machine-readable | P0 | 10 | U |
| FR-805 | A user MUST be able to navigate backward from any recommendation to its original sources | P0 | 10 | U |
| FR-806 | A user MUST be able to navigate forward from any source to every dependent recommendation | P1 | 10 | U |
| FR-807 | The audit trail MUST be append-only and MUST NOT be writable through the application API | P0 | 13 | T |
| FR-808 | Every session MUST produce a reproducibility manifest | P0 | 13 | T |

## 9. Experiments, metrics, learning

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-901 | Metrics MUST be reported as a multi-dimensional profile; a single aggregate quality score MUST NOT exist | P0 | 13 | T |
| FR-902 | Every metric MUST declare formula, inputs, range, direction, interpretation and caveats | P0 | 13 | D |
| FR-903 | Users MUST be able to define experiments varying agents, strategies, models, prompts, consensus algorithms, retrieval configs and budgets | P0 | 16 | U |
| FR-904 | Experiment runs MUST be reproducible from their manifest, subject to the documented determinism limits | P0 | 16 | T |
| FR-905 | The platform MUST support ablation of any single component | P1 | 16 | T |
| FR-906 | The MARL view MUST expose an observation/action/reward interface and record trajectories, without making MARL a runtime dependency of the MVP | R | 12 | T |
| FR-907 | Learning MUST be conservative: promotion of experience into knowledge requires validation, never automatic self-modification | P0 | 16 | T |

## 10. External integration

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| FR-1001 | MCP tools MUST be reachable only through `mcp-gateway` with an explicit allowlist | P0 | 15 | T |
| FR-1002 | Tool output MUST be treated as untrusted data with provenance, never as instructions | P0 | 15 | T |
| FR-1003 | Write-capable or untrusted tools MUST sit behind an approval gate | P0 | 15 | T |
| FR-1004 | Every tool call MUST be audited with arguments, result hash, latency and actor | P0 | 15 | A |
| FR-1005 | LLM providers MUST be swappable through configuration without domain-code changes | P0 | 2 | T |

## 11. Non-functional requirements

| ID | Requirement | P | Ph | V |
| --- | --- | --- | --- | --- |
| NFR-001 | **Durability.** A session survives any single stateless-service restart with no loss of committed artifacts | P0 | 4 | T |
| NFR-002 | **Recoverability.** RPO ≤ 24 h and RTO ≤ 4 h for the MVP stack, stated honestly rather than implied by replica counts | P0 | 17 | D |
| NFR-003 | **Determinism.** Given the same manifest and mock provider, replay reproduces artifact ids, ordering and consensus output byte-for-byte | P0 | 13 | T |
| NFR-004 | **Traceability.** Any recommendation resolves to its sources within 5 API traversions | P0 | 10 | M |
| NFR-005 | **Explainability.** Every consensus outcome renders a complete explanation without extra user queries | P0 | 10 | U |
| NFR-006 | **Auditability.** 100 % of state-changing actions appear in the ledger; a CI test asserts no mutation path bypasses it | P0 | 13 | T |
| NFR-007 | **Latency.** API reads p95 < 300 ms excluding LLM time; SSE delivery p95 < 1 s after ledger commit | P1 | 17 | M |
| NFR-008 | **Throughput.** ≥ 20 concurrent sessions and ≥ 100 logical agents in flight on the reference dev stack | P1 | 17 | M |
| NFR-009 | **Cost control.** Per-session token and cost ceilings enforced; breach terminates with `BUDGET_EXHAUSTED` | P0 | 6 | T |
| NFR-010 | **Security.** Least privilege, workspace isolation, no secrets in logs or payloads, OWASP ASVS L2 alignment | P0 | 1, 12 | T |
| NFR-011 | **Privacy.** No chain-of-thought storage; only structured artifacts and explicit rationale | P0 | 3 | D |
| NFR-012 | **Portability.** Replacing any adapter requires no change outside the composition root | P0 | 1 | D |
| NFR-013 | **Interoperability.** The reasoning model MUST be exportable to JSON-LD without schema surgery | P1 | 10 | T |
| NFR-014 | **Extensibility.** Adding an agent, consensus strategy or metric requires no edit to core workflow code | P0 | 18 | D |
| NFR-015 | **Observability.** Every port call emits a span; correlation spans request → workflow → activity → LLM → artifact | P0 | 1 | T |
| NFR-016 | **Testability.** Domain logic runs with zero network dependencies using in-memory adapters | P0 | 1 | T |
| NFR-017 | **Accessibility.** Frontend meets WCAG 2.1 AA for the views used in the evaluation task | P2 | 19 | U |
| NFR-018 | **Documentation.** Every phase exit leaves docs and memory-bank synchronized; CI checks links and Mermaid fences | P0 | all | T |
| NFR-019 | **Scientific integrity.** No metric or claim may be reported without its inputs, version and caveats | P0 | 13 | D |
| NFR-020 | **Graceful degradation.** Provider outage, retrieval failure and solver timeout produce structured degraded states, never silence | P0 | 4 | T |

## 12. Constraints (not requirements)

- Deployment target is Docker Swarm, not Kubernetes; Kubernetes-specific abstractions are
  out of scope ([ADR-011](adr/ADR-011-docker-swarm-deployment.md)).
- Single-node stateful services in the MVP stack; HA is a separate architecture
  ([ADR-020](adr/ADR-020-stateful-ha-boundary.md)).
- Python 3.12+ backend, React + TypeScript frontend
  ([ADR-010](adr/ADR-010-react-vite-frontend.md)).
- No proprietary LLM lock-in; OpenAI-compatible endpoints only
  ([ADR-006](adr/ADR-006-openai-compatible-llm-abstraction.md)).

## 13. Requirement coverage gates

| Phase | Must satisfy |
| --- | --- |
| 1 | NFR-010 (partial), NFR-012, NFR-015, NFR-016 |
| 2 | FR-1005, FR-201, FR-202 |
| 3 | FR-101, FR-102, FR-103, FR-301 … FR-312 |
| 4 | FR-104 … FR-107, FR-207, NFR-001, NFR-020 |
| 5 | FR-401 … FR-409 |
| 6 | FR-108, FR-203, FR-204, FR-206, FR-208 … FR-211, NFR-009 |
| 7 | FR-501 … FR-504 |
| 8 | FR-701 … FR-704 |
| 9 | FR-505, FR-506, FR-601 … FR-609 |
| 10 | FR-408, FR-801 … FR-806, NFR-004, NFR-005 |
| 11 | FR-705 … FR-708 |
| 12 | FR-906, NFR-010 |
| 13 | FR-807, FR-808, FR-901, FR-902, NFR-003, NFR-006, NFR-019 |
| 14 | — |
| 15 | FR-1001 … FR-1004 |
| 16 | FR-903, FR-904, FR-905, FR-907 |
| 17 | NFR-002, NFR-007, NFR-008 |
| 18 | NFR-014 |
| 19 | NFR-017 |
| 20 | NFR-013, NFR-018 |

Any `P0` requirement that cannot be met is a **stop condition** for the phase, recorded in
[../project/ERRORS.md](../project/ERRORS.md) with a proposed scope or design change — never
silently dropped.



