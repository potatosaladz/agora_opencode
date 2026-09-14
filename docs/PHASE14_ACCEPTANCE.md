# Phase 14 Acceptance Contract

**Version:** 1.0 · **Status:** frozen · **Phase:** 14
**Baseline:** Phase 13 complete through T13-04
**Requirements:** UI/exposure verification of existing FR-305, FR-504…FR-506, FR-605, FR-609,
FR-705, FR-708, FR-802, FR-804, FR-805, FR-807, FR-808, FR-901, NFR-003, NFR-004, NFR-005,
NFR-006, NFR-010, NFR-014 and NFR-019; ownership remains with the phases assigned in
[REQUIREMENTS.md](REQUIREMENTS.md)

## 1. Authority and boundary

Phase 14 makes existing reasoning, provenance, dissent, assumptions, explanations, replay and audit
capabilities interrogable through the authenticated React UI. It does not replace their domain services,
ports, repositories or persistence. PostgreSQL and the existing caller-scoped services remain authoritative;
the frontend renders server state and does not derive consensus, metrics, audit answers or graph truth.

The authoritative task order is:

1. T14-01 — Graph View
2. T14-02 — Dissent View
3. T14-03 — Assumption Register
4. T14-04 — Explanation Panel
5. T14-05 — Replay Controls
6. T14-06 — Audit Search

All six tasks are open. Each task must preserve generated API type drift checks, deny-by-default
authentication, tenant isolation, accessible non-visual equivalents and responsive desktop/mobile use.
Earlier-phase requirements cited below are verification dependencies, not reassigned implementation
ownership.

## 2. T14-01 — Graph View

**Objective:** let an authenticated reviewer inspect a bounded, authoritative reasoning subgraph and
understand node and edge semantics without reconstructing relationships in the browser.

**Dependencies:** Phase 3 graph projection and transaction boundary; Phase 10
`ReasoningGraphStore.subgraph()` traversal and provenance reads; Phase 4 session recovery and SSE; ADR-010.

**IN SCOPE**

- expose the existing `ReasoningGraphStore.subgraph()` through `POST /api/v1/graph/subgraph`;
- reuse `ReasoningTransaction.graph` through a thin authenticated API boundary;
- enforce tenant/session scope, public-id translation and radius, edge-filter, page-size and cursor
  validation;
- preserve deterministic public node/edge ordering and return independent `truncated` and `next_cursor`;
- add a code-split Graph View that renders only authoritative server graph data;
- provide an accessible textual equivalent, keyboard-operable node selection and visible edge semantics;
- provide loading, error and empty states, pagination/truncation disclosure and responsive desktop/mobile
  behavior.

**OUT OF SCOPE**

- T14-02 Dissent View, T14-03 Assumption Register, T14-04 Explanation Panel, T14-05 Replay Controls and
  T14-06 Audit Search;
- metric computation or metric-profile UI;
- new graph repositories, persistence, migrations or graph databases;
- new consensus, symbolic, MARL, replay, manifest, ledger, provenance or audit infrastructure;
- client-side reconstruction of graph authority or a second durable/client graph store.

**Acceptance criteria**

1. The authored OpenAPI contract and generated TypeScript client define the authenticated subgraph request
   and response, including session, non-empty roots, radius `0..5`, optional edge filters, page size
   `1..200`, cursor, deterministic nodes/edges, `truncated` and `next_cursor`.
2. The HTTP boundary delegates to `ReasoningTransaction.graph.subgraph()` and adds no repository,
   persistence or migration.
3. Missing, malformed, cross-workspace or cross-session roots fail closed; cursors are query-bound and
   malformed or mismatched cursors are rejected.
4. Repeated requests over unchanged data return nodes then edges in the existing deterministic order;
   pagination and depth truncation are disclosed independently.
5. The code-split Graph View renders the returned node and edge types without collapsing `SUPPORTS`,
   `OPPOSES`, `CONTRADICTS`, `ATTACKS` or other semantics into an aggregate judgment.
6. Every visual graph has a textual equivalent; node selection is keyboard operable; focus and selection
   are not communicated by color alone.
7. Loading, API error, empty graph, additional-page and depth-truncated states are explicit on desktop and
   mobile.
8. Focused API, PostgreSQL traversal, generated-contract, frontend client, component, accessibility and
   responsive tests pass while existing graph/provenance behavior remains unchanged.

**Requirement mappings:** verifies UI/exposure aspects of FR-805, NFR-004, NFR-010 and NFR-019. Their
implementation ownership remains Phases 10, 1/12 and 13 as recorded in `REQUIREMENTS.md`.

**Ownership:** API — this task owns only `POST /api/v1/graph/subgraph` and its authored/generated contract.
Frontend — this task owns the code-split Graph View and its interaction/accessibility states. Persistence —
none. Migration — none.

## 3. T14-02 — Dissent View

**Objective:** make minority positions, opposing evidence and unresolved disagreements visible and
navigable without suppressing or averaging them.

**Dependencies:** T14-01 navigation primitives; Phase 7 critique handoff; Phase 9 consensus result,
minority and dissent structures; existing artifact/provenance reads.

**IN SCOPE**

- authenticated read API composition only where existing public contracts do not expose the durable
  dissent/minority structures;
- an inline Dissent View showing every minority position, unresolved/open/disputed critique, opposing
  evidence, agent attribution, warrant and explicit empty reason;
- navigation from dissent entries to existing artifacts and Graph View roots;
- labels that distinguish support from probability, confidence and consensus outcome.

**OUT OF SCOPE**

- graph traversal or Graph View reimplementation;
- new consensus strategies, recomputation, suppression controls, critique resolution or metric
  computation;
- assumption, complete explanation, replay or audit-search presentation owned by T14-03…06.

**Acceptance criteria**

1. A fixture containing majority and minority positions renders every minority/dissent entry inline and
   provides no API or UI parameter that can omit it.
2. Each entry identifies its agent, position/polarity, warrant or explicit absence, and unresolved critique
   state, with working artifact/graph navigation.
3. Empty dissent distinguishes "none recorded" from "not evaluated"; support values use the metric profile
   context and are never presented as a lone score.
4. Keyboard, screen-reader, desktop/mobile and authenticated tenant-isolation tests pass.

**Requirement mappings:** verifies presentation of existing FR-504, FR-505, FR-506, FR-609, FR-901,
NFR-005 and NFR-019 capabilities. Ownership remains Phases 7, 9, 10 and 13.

**Ownership:** API — read-only exposure/composition of existing dissent facts if required. Frontend —
Dissent View and navigation. Persistence — none. Migration — none.

## 4. T14-03 — Assumption Register

**Objective:** let reviewers inspect the assumptions and constraints on which conclusions depend, including
challenge and symbolic status, without converting uncertainty into a pass/fail claim.

**Dependencies:** T14-01 graph navigation; Phase 3 assumption/constraint artifacts; Phase 7 critiques;
Phase 10 provenance; Phase 11 symbolic evaluations and conservative UNKNOWN policy.

**IN SCOPE**

- authenticated read composition for session assumptions and constraints when existing artifact reads are
  insufficient;
- a register with artifact identity/version/status, attribution, dependents, critiques, provenance and
  exact symbolic state where available;
- navigation to related artifacts, constraints, provenance and Graph View roots;
- explicit rendering of `UNKNOWN` as not determined with policy action `DEFER`.

**OUT OF SCOPE**

- graph reimplementation, artifact mutation, formalization authoring, solver execution or policy changes;
- consensus recomputation, metric computation, replay controls or audit search.

**Acceptance criteria**

1. Active, superseded and withdrawn assumptions/constraints are distinguishable and deterministically
   ordered; missing analyses are explicit.
2. Dependents, active critiques and available provenance/symbolic facts navigate to their authoritative
   views.
3. `SAT`, `UNSAT` and `UNKNOWN` retain their exact meanings; `UNKNOWN` is never rendered as satisfied,
   violated, green or red.
4. Focused tenant-isolation, keyboard, screen-reader and responsive tests pass.

**Requirement mappings:** verifies presentation of existing FR-311, FR-504, FR-705, FR-708, FR-805,
NFR-005, NFR-010 and NFR-019 capabilities. Ownership remains Phases 3, 7, 10 and 11.

**Ownership:** API — read-only register composition if required. Frontend — Assumption Register and related
navigation. Persistence — none. Migration — none.

## 5. T14-04 — Explanation Panel

**Objective:** provide one consistent "why" interaction for consensus and recommendations, showing both
supporting and undermining structure and making the weakest evidence discoverable.

**Dependencies:** T14-01 Graph View, T14-02 Dissent View and T14-03 Assumption Register; Phase 9 consensus
explanations; Phase 10 provenance; Phase 13 audit and metric catalogues; EXPLAINABILITY.md.

**IN SCOPE**

- authenticated consensus/recommendation explanation read exposure where existing public contracts are
  incomplete;
- a reusable panel containing outcome, strategy/version/parameters, drivers, inhibitors, conditions,
  counterfactuals, absent evidence, minority report, unresolved critiques, provenance links and caveats;
- explicit empty reasons and recursive navigation through the established Graph, Dissent and Assumption
  views;
- weakest-evidence identification from verification, provenance, opposition and caveat facts already held
  by the platform.

**OUT OF SCOPE**

- generating explanations with an LLM, inventing counterfactuals, consensus recomputation or new metric
  values;
- replacing provenance/audit/reasoning services;
- replay controls and general audit search.

**Acceptance criteria**

1. Every required explanation section is present; empty sections state why they are empty.
2. Dissent is inline, all numbers carry kind/unit/version/caveats as applicable, and support is never called
   probability, confidence or a composite score.
3. The fixture's weakest evidence can be reached from the recommendation in one consistent "why" path and
   links terminate at authoritative artifacts or source citations without orphans.
4. Deterministic ordering, tenant isolation, generated-contract, keyboard, screen-reader and responsive
   tests pass.

**Requirement mappings:** verifies presentation of existing FR-504, FR-505, FR-605, FR-609, FR-804,
FR-805, FR-901, NFR-005 and NFR-019 capabilities. Ownership remains Phases 7, 9, 10 and 13.

**Ownership:** API — read-only consensus/recommendation explanation composition if required. Frontend — the
reusable Explanation Panel and recursive "why" navigation. Persistence — none. Migration — none.

## 6. T14-05 — Replay Controls

**Objective:** expose the existing STRICT, TOLERANT and LIVE replay semantics without weakening their
identity, verification or historical-immutability guarantees.

**Dependencies:** T14-04 explanation presentation; Phase 13 `SessionReplayService`, exact-version registry,
finalized run manifests and replay lineage.

**IN SCOPE**

- authenticated API exposure of existing replay requests/results and exact manifest references;
- controls that explain the three modes before execution and display status, first mismatch, ordered
  tolerant differences or fresh LIVE linkage as returned by existing services;
- explicit confirmation for operations that launch fresh LIVE execution;
- navigation from replay results to the source session, manifest and explanation views.

**OUT OF SCOPE**

- redesigning replay engines, mode semantics, manifests, MARL verification or implementation registries;
- mutating historical sessions, calling external providers during STRICT, or claiming TOLERANT as VERIFIED;
- new replay persistence unless a separately approved contract proves existing finalized manifests and
  lineage insufficient.

**Acceptance criteria**

1. API requests bind exact source session and finalized manifest id/version/hash and delegate to the
   existing replay service.
2. STRICT, TOLERANT and LIVE remain visibly distinct; STRICT never exposes an external-call path,
   TOLERANT never claims VERIFIED, and LIVE identifies the fresh linked run.
3. Historical input/result identities remain immutable and cross-workspace requests fail closed.
4. Focused mode, generated-contract, keyboard, screen-reader and responsive tests pass.

**Requirement mappings:** verifies UI/API exposure of existing FR-808, NFR-003, NFR-010, NFR-014 and
NFR-019 capabilities. Ownership remains Phases 13, 1/12 and 18 as recorded in `REQUIREMENTS.md`.

**Ownership:** API — authenticated replay service exposure only. Frontend — Replay Controls and result
presentation. Persistence — existing manifest/lineage persistence only; no new persistence by default.
Migration — none by default.

## 7. T14-06 — Audit Search

**Objective:** let authorized reviewers ask the existing eight audit questions and inspect chain integrity
without creating a parallel audit subsystem.

**Dependencies:** T14-01…05 navigation; Phase 13 `AuditQueryService`, `AccessAuditService`,
`ChainVerificationService`, `access_log`, `audit_anchors` and reasoning ledger.

**IN SCOPE**

- authenticated `audit:read` API exposure of Q1…Q8 with typed parameters/results, bounded queries and
  pagination where applicable;
- an Audit Search interface organized by the eight authored questions rather than raw table access;
- links from answers to existing Graph, Dissent, Assumption, Explanation and Replay views;
- visible chain-integrity, altered/unaltered and incomplete/not-applicable states;
- access logging of audit reads using the existing audit substrate.

**OUT OF SCOPE**

- replacement audit storage, mutable audit records, raw unrestricted SQL search or privileged RLS bypass;
- nightly anchor scheduling, external WORM anchor storage, signed export bundles or invented Q2/Q3/Q5
  events;
- replay-engine, consensus or graph redesign.

**Acceptance criteria**

1. Each Q1…Q8 operation delegates to the existing typed Phase 13 service and preserves deterministic,
   tenant-scoped behavior.
2. Q7 remains bounded strictly before recommendation acceptance; Q8 uses existing chain verification and
   never treats history-table presence alone as integrity.
3. Audit reads are authorized, caller-scoped and themselves recorded through existing access logging;
   cross-workspace and malformed requests fail closed.
4. The UI states the selected question, parameters, answer basis, completeness/integrity state and working
   links to related views; empty results explain why.
5. Focused Q1…Q8 API, authorization, pagination, access-log, keyboard, screen-reader and responsive tests
   pass without replacing existing audit tests.

**Requirement mappings:** verifies UI/API exposure of existing FR-802, FR-807, NFR-006, NFR-010 and
NFR-019 capabilities. Ownership remains Phases 10, 13 and 1/12.

**Ownership:** API — authenticated Q1…Q8 read/search exposure and existing access-audit composition.
Frontend — Audit Search and cross-view navigation. Persistence — reuse `access_log`, `audit_anchors` and
the ledger only. Migration — none.

## 8. Scripted Phase 14 usability fixture

The phase fixture is a completed, tenant-scoped session with:

- one majority recommendation and at least one preserved minority position from a different agent;
- at least one unresolved or disputed Critique linked to the recommendation path;
- one supporting evidence item with stronger verification and complete source provenance;
- one weaker evidence item that is explicitly identifiable by lower verification, incomplete provenance,
  opposing evidence or a recorded caveat, without a UI-computed aggregate score;
- one material assumption with dependents and an available symbolic state, including an `UNKNOWN` case;
- a finalized reproducibility manifest with recorded STRICT/TOLERANT results and valid source lineage;
- durable facts sufficient for Q1…Q8 and a clean audit chain.

The scripted reviewer starts from the session/recommendation UI with no internal-system briefing and must:

1. identify the minority position and its author/warrant;
2. identify the weakest evidence and state the visible reason it is weakest;
3. navigate to that evidence's provenance and the material assumption it supports;
4. distinguish an unresolved symbolic `UNKNOWN` from satisfaction or violation;
5. identify the replay mode/result and inspect the relevant audit answer and chain-integrity state.

The script passes only when steps 1 and 2 are completed from the UI alone without database access,
developer tools or facilitator explanation, all links resolve under the reviewer's permissions, and no
required dissent/evidence section is hidden behind an initially collapsed control. The fixture and script
are frozen now; passing evidence belongs to implemented T14-01…06 and must not be claimed during this
planning reconciliation.

## 9. Phase exit

Phase 14 exits only when all six tasks are complete and the scripted fixture proves that a reviewer with no
knowledge of the internals can identify the minority position and weakest evidence from the UI alone.
Backend/frontend quality, authored/generated contracts, tenant isolation, accessibility, responsive
behavior, traceability, documentation links, Compose deployment and exact-SHA remote CI must also pass.
