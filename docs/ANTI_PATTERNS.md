# Anti-Patterns

**Version:** 1.0 · **Status:** design
**Purpose:** name the ways this project can succeed at looking right while failing at being right.
Each entry states the temptation, the damage, a detection signal, and the alternative. Cited by
[TESTING.md](TESTING.md) and by the phase gates in [../project/PLAN.md](../project/PLAN.md).

## 1. Epistemic

| # | Pattern | Temptation | Damage | Detection | Alternative |
| --- | --- | --- | --- | --- | --- |
| AP-1 | **Single score** | one number is comparable, sortable, dashboard-able | collapses the trade-offs that *are* the finding | `test_fr901_no_aggregate_field_anywhere`; UI review | the metric profile, dimension by dimension |
| AP-2 | **Confidence laundering** | a model's `0.9` looks like a probability | readers act on it as one; calibration becomes unmeasurable | grep for `confidence` typed as probability; E-4 lint | declared subjective strength with its basis (CF-1) |
| AP-3 | **Citation theatre** | EP-01 evidence coverage is a gate metric | every claim gets one weak citation; coverage rises, warrant falls | EP-01 up while EP-03 down | show EP-01 and EP-03 as a pair, always |
| AP-4 | **Consensus as correctness** | agreement feels like validation | the platform's central claim inverts | outcome class labelled "support", never "accuracy" | separate support from warrant; keep the minority report |
| AP-5 | **LLM-as-judge for verification** | cheap, fluent, scales | a model certifies a model; V-2 violated | status-transition events with `actor.class = AGENT` committing | human, fetched source, or symbolic evaluation |
| AP-6 | **Transcript as memory** | "just embed past conversations" | unattributable, unversioned claims seep into future reasoning | memory writes outside `promote` | four tiers plus the promotion workflow |
| AP-7 | **Chain-of-thought as explanation** | it looks like reasoning | explains the model, not the argument; a privacy and gaming surface too | any stored field containing raw reasoning | the artifact graph and `explain()` structure |
| AP-8 | **Absence as refutation** | an empty retrieval reads as "no evidence exists" | the platform asserts claims about the world it cannot support | `NO_MATCH` conflated with `RAG_FAILED` | report namespaces searched, query and index version |
| AP-9 | **Silent idealization** | "should" becomes `<=` because the solver needs it | normative force lost; the constraint looks checked | empty `modality` on a hard constraint | keep modality; encode soft constraints with retraction handles |
| AP-10 | **Premature formalization** | formalizing feels rigorous | garbage ASTs with confident outputs | `RR-07` climbing, rung-4 failures | refuse; keep the statement a `CLAIM` |

## 2. Architectural

| # | Pattern | Damage | Alternative |
| --- | --- | --- | --- |
| AP-11 | **God coordinator** — every rule inlined in the workflow | untestable, un-pluggable, and every change risks the ledger | behaviour behind ports; the coordinator holds authority, not policy detail |
| AP-12 | **Adapter leakage into `core/`** | the port abstraction becomes decorative; NFR-014 dies | import-lint forbids `core/` → `adapters/` |
| AP-13 | **Redis as truth** | silent data loss presented as correctness | Redis is working state only ([ADR-009](adr/ADR-009-redis-ephemeral-only.md)) |
| AP-14 | **Dual source of truth** — a cache or table that disagrees with the ledger | two answers to one question | derive from the ledger; caches are rebuildable |
| AP-15 | **Workflow logic in the gateway** | sessions break on reconnect; no durability | the gateway is stateless; the workflow engine owns state |
| AP-16 | **Prompt sprawl in YAML** | unversioned behaviour no test covers | prompts are versioned artifacts with hashes, in the registry |
| AP-17 | **Schema edit without an event** | the audit trail stops being a trail | migration that backfills events, or reject the change |
| AP-18 | **Two writers to the ledger** | total order lost, replay impossible | single active coordinator ([DOCKER_SWARM.md §6](DOCKER_SWARM.md)) |

## 3. Process

| # | Pattern | Damage | Alternative |
| --- | --- | --- | --- |
| AP-19 | **"Done" without a trace row** | the state file and the code diverge — the exact failure this reconciliation exists to fix | TR-1: `implemented` in green CI before any done claim |
| AP-20 | **Docs presented as shipped** | trust in the documents collapses, and they stop being read | a status field per document: `draft` / `design` / `implemented` |
| AP-21 | **Phase skipping** | later phases inherit invisible prerequisites and stall | phase gates with explicit exit criteria |
| AP-22 | **Benchmark chasing** | the platform optimises a leaderboard instead of defensibility | the evaluation suite compares *configurations*, not vendors |
| AP-23 | **Refactor-by-rewrite mid-phase** | two half-finished designs coexist | a phase may pause for a rewrite; it may not run both |
| AP-24 | **Fixing a metric instead of a behaviour** | the gaming table becomes a to-do list | change the behaviour, then the metric |

## 4. Interface

| # | Pattern | Damage | Alternative |
| --- | --- | --- | --- |
| AP-25 | **Dissent behind a collapsed panel** | FR-506 satisfied in the API, defeated in practice | dissent inline in the recommendation view (X-4) |
| AP-26 | **Green on `UNKNOWN`** | an unresolved solver question reads as a pass | "not determined", visually distinct from both states (X-5) |
| AP-27 | **Sparkline from n = 1** | implies a trend that does not exist | show n, or show a point |
| AP-28 | **A tooltip as the only explanation** | the structure becomes undiscoverable | the "why" affordance is a first-class view (X-7) |
| AP-29 | **Colour as the only carrier of epistemic status** | inaccessible; status becomes decoration | text label plus colour, never colour alone |

## 5. Research

| # | Pattern | Damage | Alternative |
| --- | --- | --- | --- |
| AP-30 | **Metric shopping** | run 20 metrics, report the 2 that moved | pre-registered primary and guard metrics; ST-3 |
| AP-31 | **Cross-version pooling** | results describe no reproducible system | per-version reporting; invalidated cells excluded |
| AP-32 | **Dropping failed sessions** | survivorship bias in the headline | failure rate is a primary outcome |
| AP-33 | **Narrative before the table** | the conclusion is written first | report template order enforced |
| AP-34 | **Hiding a null result** | the next person repeats the experiment | null results published in [RESEARCH_NOTES.md](RESEARCH_NOTES.md) |

## 6. The meta-pattern

Almost every entry above is one thing: **optimising the measure instead of the goal**. The
platform's design choices — no composite score, mandatory caveats, dissent that cannot be omitted,
verification a model cannot perform on itself — exist to make that substitution hard to do by
accident and impossible to do quietly.

When a change makes a number look better without making a recommendation more defensible, it is an
anti-pattern regardless of how good the release notes read.

## 7. Related

[STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) · [CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) ·
[METRICS.md](METRICS.md) · [EXPLAINABILITY.md](EXPLAINABILITY.md) · [TESTING.md](TESTING.md) ·
[MVP_BOUNDARY.md](MVP_BOUNDARY.md)

