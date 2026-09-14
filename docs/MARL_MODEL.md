<!-- trace: FR-906, NFR-003, NFR-006, NFR-010, NFR-011, NFR-019 -->
# Deterministic MARL Environment and Trajectories

**Version:** 2.0 · **Status:** normative Phase 12 implementation contract *(research track; no training)*
**Phase:** 12 · **Requirement:** FR-906 · **Migration:** `20260912_0024` · **Ports:**
`MarlEnvironment`, `MarlTrajectoryStore` ([PORTS.md §14](PORTS.md))

## 1. Scope and invariants

Phase 12 exposes a deterministic observation/action/reward environment over the existing coordinator. It
records trajectories and verifies replay; it does **not** train, promote, or execute a learned production
policy. The rule-based coordinator remains authoritative and MARL is not on the MVP runtime critical path.

The following are invariants, not configuration:

- **P12-1 — advisory only.** A policy proposes an action. Only the coordinator accepts or rejects it and
  performs workflow transitions. A policy never writes artifacts, chooses a consensus outcome, changes
  epistemic status, or bypasses authorization, budget, lifecycle, or feasibility checks.
- **P12-2 — feasibility before preference.** `SAT → PROCEED`, `UNSAT → BLOCK`, and `UNKNOWN → DEFER` are
  applied before action ranking or reward. No reward can compensate for `UNSAT`; `UNKNOWN` is never positive
  assurance and caps a selected alternative at `CONDITIONAL_CONSENSUS`.
- **P12-3 — committed inputs only.** Observations and rewards use structured committed state, never prompts,
  raw model text, chain-of-thought, mutable current-state inference, or transport order.
- **P12-4 — exact arithmetic.** Authoritative values contain integers, reduced rational pairs, canonical
  decimal strings, enums, booleans, UUIDs, and hashes. Binary floating point is forbidden.
- **P12-5 — immutable capture.** Every observation records a session-ledger watermark and an immutable source
  census captured in the same caller-owned transaction. Rows without ledger sequence are never queried later
  to pretend they describe historical state.
- **P12-6 — no silent gaps.** A transition is complete or the episode receives an explicit incomplete marker.
  Missing reward input is represented by a typed neutral contribution and reason, never an invented metric.
- **P12-7 — deterministic bytes.** Canonical identity, hashing, ordering, JSONL export, and replay rules below
  are normative. Timestamps are recorded facts, not ordering inputs.

## 2. Decision boundary and step semantics

A **decision boundary** occurs only when the coordinator is between authoritative actions: all effects from
its preceding action have flushed, no worker proposal is being committed, and the transaction can lock the
session ledger head. The coordinator calls Phase 12 immediately before selecting its next action. There is no
background sampler.

Inside that transaction the capture service:

1. locks `session_ledger_heads` for the session;
2. sets watermark `W = (next_seq - 1, head_hash)` and resolves the event id at that sequence (`null` only for
   an empty genesis ledger);
3. snapshots all observation and reward inputs, including exact physical row ids/hashes and ordered census
   values;
4. appends the observation and optional advisory proposal/decision rows without committing; and
5. returns the accepted coordinator action, if any, for execution through the existing workflow.

The next decision boundary closes the preceding transition. Therefore transition `t` is:

`(O_t, proposed_action_t?, coordinator_decision_t, executed_action_t?, O_(t+1), R_t, terminal_t)`.

The post-observation watermark must be greater than or equal to the pre-observation watermark. It may be
equal only for a rejected/no-op proposal that caused no authoritative event. A session may have one active
Phase 12 episode per `(environment_version, policy_id, policy_version, seed)`; concurrent capture of the same
next decision index serializes on the ledger-head lock and exact retry returns the existing rows.

The production integration point is the coordinator decision service, after proposal/critique/revision or
consensus effects commit and before the next route is selected. Capture from polling, SSE, mutable session
projections, or `created_at` windows is prohibited.

## 3. Exact values, identity, canonicalization, and order

### 3.1 Exact values

A rational is JSON `{ "numerator": n, "denominator": d }`, where `n` is an integer, `d > 0`,
`gcd(abs(n), d) = 1`, the denominator is positive, and zero is exactly `0/1`. Addition, subtraction,
multiplication, comparison, clipping, and scalarization operate on arbitrary-precision integers and reduce
after every operation. Canonical decimal strings follow the existing plain-decimal rule: no exponent, no
leading plus, no insignificant trailing zero, and `-0` becomes `0`. Decimal inputs are converted to rationals
exactly; no rounding occurs in Phase 12.

### 3.2 Deterministic identity

`episode_id`, `observation_id`, `proposal_id`, `decision_id`, `transition_id`, component ids, credit ids, and
terminal ids are UUIDv5. The namespace is the session UUID and the UTF-8 name is:

`agora:marl:v1:<entity-kind>:<environment-version>:<policy-id>:<policy-version>:<seed>:<decision-index>[:<metric-name>]`.

The seed is a signed 64-bit integer. The baseline/no-policy adapter uses policy id `coordinator-baseline`,
version `1`, and still records a seed. Caller-supplied IDs that do not equal this derivation fail closed.

All hash fields are lowercase `sha256:` plus SHA-256 over existing `canonical_json` bytes (RFC 8785/JCS
UTF-16 key ordering, UTF-8, no floats). Hash preimages exclude database surrogate timestamps unless the
schema explicitly names a timestamp as a captured fact. Arrays are sorted before hashing by the rules below;
JSON object insertion order is never authority.

### 3.3 Stable order

- observations, decisions, and transitions: `decision_index` ascending;
- artifact/source census: `(kind, logical_id UUID bytes, version, physical id UUID bytes)`;
- graph facts: `(edge_type, from artifact UUID bytes, to artifact UUID bytes, edge UUID bytes)`;
- positions: `(target UUID bytes, agent-definition UUID bytes, round, physical id UUID bytes)`;
- critiques: `(creation_ledger_seq, physical id UUID bytes)`;
- agents: agent-definition UUID bytes;
- reward components: the fixed order in §6.1;
- credit: `(component ordinal, status ordinal, source_kind, source_id UUID bytes)`.

## 4. Observation contract

`MarlObservationV1` is a frozen schema with:

| Field | Contract |
| --- | --- |
| identity | `observation_id`, `episode_id`, `decision_index >= 0`, `schema_version = 1`, `environment_version` |
| scope | `workspace_id`, `session_id`, `round >= 0`, coordinator phase enum |
| watermark | `ledger_seq >= 0`, nullable `event_id`, `event_hash`; genesis uses sequence 0 and `GENESIS_HASH` |
| budget | maximum and consumed rounds/tokens/USD; integers and canonical decimal strings only |
| critiques | counts by `LOW, MEDIUM, HIGH, BLOCKING` plus ordered latest-head records and resolution |
| evidence/provenance | ordered eligible-artifact and claim census, resolvable citation snapshots, gaps, and hashes |
| disagreement | ordered latest position records and the frozen round-2 dissent baseline, when eligible |
| consensus | latest exact consensus id/input hash, outcome, ordered rank scores, flip-distance inputs, and feasibility verdicts |
| agent load | per pinned agent: completed calls, input tokens, output tokens, cost; all cumulative at the boundary |
| terminal | `false` at a decision opportunity; terminal observations carry the terminal reason and no proposed next action |
| sources | ordered `ObservationSourceV1` records from §8 |
| hashes | `sources_hash`, `features_hash`, `observation_hash` |

The observation is global environment state. It is not an individual agent prompt and does not weaken sealed
round-one visibility. Policy adapters receive only this schema. Unknown fields, duplicate identities,
noncanonical decimals/rationals, unsorted arrays, source hashes that do not match their canonical snapshots,
or a watermark inconsistent with the locked ledger head are rejected.

## 5. Advisory action contract

The closed `MarlActionV1` union is:

| Kind | Required payload | Coordinator validation |
| --- | --- | --- |
| `SPEAK` | `agent_definition_id`, `turn_type` | active membership, phase, budget, role, and visibility |
| `REQUEST_RETRIEVAL` | requesting agent, non-empty purpose, target artifact ids, namespace ids | grants, ACLs, budget, and retrieval policy |
| `REQUEST_SIMULATION` | requesting agent, exact simulation spec id/hash | sandbox policy, engine support, and budget |
| `END_ROUND` | non-empty reason code | round policy and outstanding mandatory work |
| `TERMINATE` | non-empty proposed reason code | lifecycle and explicit termination policy |
| `ESCALATE_TO_HUMAN` | reason code and optional target ids | configured human gate and authorization |

Every action carries `schema_version = 1`, deterministic `proposal_id`, observation id/hash, policy id/version,
seed, and canonical `action_hash`. `MarlActionDecisionV1` records `ACCEPTED`, `REJECTED`, or `NO_PROPOSAL`, a
stable coordinator rule id/version, safe reason code, and the exact executed action hash when accepted.
Acceptance means only that normal coordinator validation selected the proposal. A rejection is a valid
transition and is never silently replaced with an apparent accepted action.

## 6. Reward vector and exact arithmetic

### 6.1 Fixed components

The Phase 12 reward is the ordered vector below. It is never persisted or reported as one aggregate
"session quality" number.

| Ordinal | Metric | Phase 12 reward implementation | Direction | Exact step value |
| --- | --- | --- | --- | --- |
| 0 | `EP-02@1` provenance completeness | `agora.reward.provenance-delta@1` | `HIGHER_BETTER` | `post - pre` |
| 1 | `DH-03@1` attack coverage | `agora.reward.attack-coverage-delta@1` | `HIGHER_BETTER` | `post - pre` |
| 2 | `DH-02@1` disagreement retention | `agora.reward.disagreement-retention-delta@1` | `NO_DIRECTION` | `post - pre` (descriptive) |
| 3 | `CQ-03@1` flip distance | `agora.reward.flip-distance-delta@1` | `HIGHER_BETTER` | `post - pre` |
| 4 | `CE-03@1` cost | `agora.reward.cost-delta@1` | `LOWER_BETTER` | `pre - post` |

Each `RewardComponentV1` carries metric id/version, reward implementation id/version, direction, exact
pre/post values, exact rational reward, status, optional neutral reason, ordered source hashes, and its
component hash. Status is exactly `OBSERVED`, `NOT_APPLICABLE`, or `MISSING_INPUT`. The last two have
`0/1` reward and a stable neutral reason; missing metric data is never guessed.

All authoritative arithmetic uses reduced `(numerator, denominator)` pairs with a positive denominator.
Canonical decimals use plain finite base-10 text: no exponent, leading plus, negative zero, or trailing
fractional zeroes. Binary floats, NaN, infinity, zero/negative denominators, and unreduced fractions fail.

This is **environment reward computation**, owned by Phase 12. The metric names reference the catalogue in
[METRICS.md](METRICS.md), but Phase 12 adds no general metric registry, analytics engine, dashboard, or
full-session metric pipeline; those remain Phase 13.

## 7. Credit accounting

`CreditAssignmentV1` is deterministic provenance accounting, not causal inference. A record is `DIRECT`,
`SHARED`, `ENVIRONMENT`, or `NEUTRAL`; references one exact component id/hash; names captured source hashes;
and orders agent-definition UUIDs by UUID bytes. Shared shares and credited values are reduced rationals.
Credits for every observed component sum exactly to that component reward. A neutral component has exactly
one explicit zero-valued `NEUTRAL` credit and no agent. The implementation makes no Shapley,
counterfactual, learned-causal, or causal-contribution claim.

## 8. Canonical identities and preimages

Canonical bytes are UTF-8 RFC 8785/JCS; hashes are lowercase `sha256:` plus 64 hexadecimal characters.
UUIDs are lowercase hyphenated strings, enums use values, decimals use §6 canonical strings, and rationals
use reduced numerator/positive-denominator objects. Unknown fields, duplicate identities, unsorted declared
sets, malformed hashes, and floats fail closed. Every object omits **only its own hash field**:

| Object | Complete preimage (apart from own hash) |
| --- | --- |
| source snapshot | schema version, source id/kind/version, immutable payload |
| observation source | schema version, ordinal, complete snapshot |
| observation feature | schema version, feature id/version, value, ordered source hashes |
| observation | identity/scope/version, watermark, terminal fields, ordered sources/features and aggregate hashes |
| proposed action | identity/index, observation identity/hash, policy id/version, seed, kind, ordered agents, payload |
| executed action | identity/index, kind, ordered agents, payload |
| coordinator decision | identity/index, observation/proposal/execution hashes, outcome/reason, implementation, feasibility |
| reward component | identity/index/ordinal, metric and implementation, direction, exact values/status/reason/sources |
| credit | identity/index, exact component reference, status, ordered agents/sources, exact share/value, implementation |
| decision boundary | identity/index plus complete observation/proposal/decision/execution objects |
| transition | identity/index plus complete boundary, post-observation, ordered rewards/credits, terminal flag |
| incomplete marker | marker/episode/open-index/reason and optional pending-boundary hash |
| episode | scope/version/status/code identity and ordered transition, pending-boundary, incomplete identities |

Timestamps, where retained as surrounding persistence metadata, are excluded from these identities and never
order records.

## 9. Episode lifecycle

An `OPEN` episode has gapless closed transitions and at most one pending boundary at the next index. A
`COMPLETE` episode has no pending boundary and ends in a transition whose post-observation is terminal. That
terminal observation carries the authoritative lifecycle reason, has no next proposal/decision, and has a
ledger watermark at or after its pre-observation.

Interrupted work becomes `INCOMPLETE` through one immutable marker naming the first unclosed decision and,
when capture occurred, its boundary hash. No post-observation, reward, credit, or successful transition is
fabricated. Gaps and silent skipping are invalid. A structurally authentic incomplete episode is exportable,
but `INCOMPLETE != replay success`.

## 10. Canonical export

A bundle has exactly `manifest.json` and `trajectory.jsonl`, no directory or sidecar. Both are UTF-8 without
BOM, use LF only, and end in LF. The manifest is one JCS object. The trajectory is one JCS object per line:
closed transitions by `decision_index`, then an optional pending boundary and mandatory incomplete marker.

The manifest pins schema/environment/code identity and the observation, reward, credit, and coordinator
implementation id/version sets. It records the exact trajectory byte length, record count, episode status,
episode hash, and SHA-256 of the exact `trajectory.jsonl` bytes—not a reparsed equivalent.

## 11. Hermetic offline verification

`verify_bundle()` receives only manifest bytes, trajectory bytes, and a caller-provided local implementation
registry (plus entry names/resource limits at the import boundary). It performs no database, network, object
store, clock, environment, LLM, retrieval, Z3, or simulation access and never reruns a learned policy.
Captured proposals/actions are inputs.

Verification checks canonical encoding, schemas, exact manifest/trajectory relationship, ordering, child and
episode hashes, references, feature reconstruction from captured snapshots, coordinator decisions, reward
recomputation, credit conservation, and implementation pinning. Unknown ids/versions fail closed.
`ReplayVerificationV1` returns `VERIFIED`, `INCOMPLETE`, or `FAILED`, integrity/replay booleans, episode id,
checked count, expected/actual hashes, and exactly one safe first failure—never an implementation exception.

The closed precedence is:

1. `BUNDLE_ENTRY_SET`
2. `RESOURCE_LIMIT_EXCEEDED`
3. `INVALID_UTF8`
4. `INVALID_JSON`
5. `UNSUPPORTED_SCHEMA_VERSION`
6. `SCHEMA_VIOLATION`
7. `NONCANONICAL_ENCODING`
8. `MANIFEST_MISMATCH`
9. `ORDER_VIOLATION`
10. `HASH_MISMATCH`
11. `REFERENCE_MISMATCH`
12. `UNKNOWN_IMPLEMENTATION`
13. `REPLAY_MISMATCH`
14. `EPISODE_INCOMPLETE`

Ties use `manifest.json` before `trajectory.jsonl`, then lowest line/decision index, then lexical JSON
pointer. Default limits are 256 KiB manifest, 64 MiB trajectory, 100,000 records, depth 64, one MiB strings,
and 100,000 members per object/array. Limit errors are always `RESOURCE_LIMIT_EXCEEDED`.

## 12. Persistence, isolation, and phase boundary

`marl_episodes` stores typed scope, state, versions, code identity, and an optional validated incomplete
marker. `marl_trajectory_records` stores indexed decision/kind/hash columns plus canonical validated JSONB;
each transition JSONB contains its observations, proposal, execution, coordinator decision, five reward
components, and credits as the finalized model deliberately avoids redundant child tables.
Composite tenant/session foreign keys, uniqueness, forced RLS, append-only triggers, and a transaction-level
advisory lock protect ownership, history, and concurrent gapless allocation. The PostgreSQL adapter only
`flush()`es; callers own commit/rollback. The in-memory adapter implements the same append-or-conflict rule:
same identity/content replays, different content conflicts.

The module is research-only and is not wired into production consensus. It includes no PPO, MAPPO, QMIX,
MADDPG, replay buffer, neural policy, gradient training, RL framework dependency, or policy promotion.
Phase 12 trajectory replay checks captured MARL inputs against named local implementations. It is explicitly
not Phase 13 full-session `REPLAY_STRICT`, does not reproduce arbitrary providers, and does not implement the
Phase 13 metric catalogue/runtime infrastructure.

Related: [AGENT_PROTOCOLS.md](AGENT_PROTOCOLS.md) · [REASONING_GRAPH.md](REASONING_GRAPH.md) ·
[EXPERIMENTATION.md](EXPERIMENTATION.md) · [MVP_BOUNDARY.md](MVP_BOUNDARY.md) ·
[REPRODUCIBILITY.md](REPRODUCIBILITY.md) · [PORTS.md §14](PORTS.md)