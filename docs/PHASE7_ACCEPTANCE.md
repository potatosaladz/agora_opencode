# Phase 7 Acceptance Contract

**Version:** 1.0 · **Status:** frozen for T7-00 · **Phase:** 7
**Baseline:** Phase 6 exact SHA `6d671acffe7abd3e5b587042457f300e0c442adc`
**Requirements:** FR-205, FR-501…FR-504; inherited FR-207, FR-208, FR-210, FR-302 and FR-303

## 1. Boundary

Phase 7 adds coordinator-mediated criticism, response and revision to the existing typed reasoning
model. It does not create another artifact store or grant state authority to a Critic. Critiques,
responses and revisions use the Phase 3 artifact, graph and ledger transaction boundary and the Phase 6
runtime, authorized-context, dispatch, attribution and budget paths.

Phase 7 includes:

- one shipped cross-cutting Critic definition with a digest-pinned prompt;
- strict Critic output limited to typed `CRITIQUE` proposals;
- deterministic target validation and atomic `ATTACKS` projection;
- all seven FR-503 response dispositions and additive critique resolution;
- targeted revision turns with `SUPERSEDES` and `RESPONDS_TO` lineage;
- durable evidence requests and explicitly deferred simulation requests;
- round/phase orchestration for `CRITIQUE` then `REVISE`;
- a deterministic explanation handoff containing every latest unresolved critique head.

Phase 7 excludes simulation execution (Phase 8), consensus and minority reports (Phase 9), graph
traversal and final explanation APIs (Phase 10), metric computation (Phase 13), full UI (Phase 14), and
real-domain experiments (Phase 16). No Phase 8 result may be invented to satisfy a simulation request.

## 2. Executable contract choices

<!-- trace: FR-205, FR-501, FR-502 -->
### 2.1 Taxonomy and targets

The only critique types are the ten FR-501 values already frozen in `CritiqueType`:
`EVIDENCE_GAP`, `LOGICAL_FALLACY`, `HALLUCINATED_SOURCE`, `MEASUREMENT_ERROR`, `MODEL_MISUSE`,
`CONSTRAINT_IGNORED`, `CONFLICT_OF_INTEREST`, `ALTERNATIVE_OMITTED`,
`UNCERTAINTY_UNDERSTATED`, and `CAUSAL_OVERCLAIM`. Earlier roadmap examples
`UNSUPPORTED_CLAIM`, `IGNORED_CONSTRAINT`, and `FALSE_DILEMMA` are aliases with no contract status and
must not enter code, persisted data or wire schemas.

A Critic may attack any of the 14 artifact kinds, including another Critique. The target must be an
`ACTIVE`, same-workspace, same-session artifact visible at or before the coordinator-owned round and
ledger boundary. A fabricated, hidden, future, withdrawn, superseded or cross-session target fails before
any write. Every new Critique starts with `resolution: OPEN`, has a non-blank argument and one severity,
and projects exactly one `ATTACKS` edge. Exact duplicate attacks in one turn fail rather than inflate
attack coverage.

### 2.2 Critic role and visibility

The shipped Critic is a normal immutable agent definition with `role_kind: critic`, distinct declared
objectives, an adversarial stance, the existing provider-neutral activity path, and a literal prompt
digest. During `CRITIQUE`, its proposal bundle may contain only `CRITIQUE` artifacts and no evidence or
simulation request. During other phases it is not dispatched as a Critic.

Critic context contains coordinator-selected public artifact snapshots, authorized knowledge, objectives
and constraints. It has no peer transport, direct persistence, lifecycle, routing or phase-transition
capability. A third consecutive zero-Critique completed round appends `CRITIC_INACTIVE`; earlier empty
rounds remain explicit completed turns and never assert that all artifacts are sound.

<!-- trace: FR-503 -->
### 2.3 Response and resolution

The seven response dispositions are exactly `ACCEPT`, `PARTIALLY_ACCEPT`,
`REJECT_WITH_JUSTIFICATION`, `REVISE`, `REQUEST_EVIDENCE`, `REQUEST_SIMULATION`, and `ABSTAIN`.
A response pins workspace, session, round, responding definition/version, turn, Critique id/version and
target id/version. Only the target artifact's `AGENT` owner may respond automatically; human- and
service-owned targets remain `UNRESOLVED` pending a later human path. A Critique attacking a Critique is
answered by the attacked Critique's owner, not by the original target's owner.

Critique payloads are immutable. Every resolution change creates a new Critique version with the same
logical id, a `SUPERSEDES` edge to the previous head, and one retry-stable response event. The mapping is:

| Response | New Critique resolution | Required effect |
| --- | --- | --- |
| `ACCEPT` | `RESOLVED` | non-blank rationale |
| `PARTIALLY_ACCEPT` | `UNRESOLVED` | rationale plus remaining issue |
| `REJECT_WITH_JUSTIFICATION` | `DISPUTED` | at least one active, visible warrant artifact |
| `REVISE` | `RESOLVED` | one valid target revision linked by `RESPONDS_TO` |
| `REQUEST_EVIDENCE` | `UNRESOLVED` | durable evidence request identity |
| `REQUEST_SIMULATION` | `UNRESOLVED` | durable deferred simulation request identity |
| `ABSTAIN` | `UNRESOLVED` | explicit rationale; never omission |

No response deletes or silently closes a Critique. A conflicting stale head/version returns a conflict;
exact retry returns the previously committed result.

### 2.4 Revision and requests

A `REVISE` turn receives only assigned Critiques, the responding agent's own target lineage,
coordinator-selected public artifacts, and authorized evidence. It does not receive private peer output.
The proposed target revision must preserve workspace, session, kind, logical id and owner, increment the
version by one, supersede the current active head, and satisfy the original kind schema. The coordinator
adds `SUPERSEDES` and `RESPONDS_TO`; model output cannot claim either relationship as authority.

`REQUEST_EVIDENCE` invokes the existing Phase 5 retrieval boundary under the responding agent's effective
membership and namespace grants. Success or failure remains explicit and ledgered. `REQUEST_SIMULATION`
records a typed deferred request for Phase 8; Phase 7 neither runs a simulation nor marks the Critique
resolved from a nonexistent result.

<!-- trace: FR-504 -->
### 2.5 Ordering, atomicity and explanation handoff

`CRITIQUE` commits in pinned Critic/peer order; `REVISE` commits in stable target-artifact order, then
responding-definition order. Both retain the Phase 6 bounded worker pool, durable budget checks and full
attribution. Response processing locks the current Critique head and target head. Artifact versions,
graph edges, request records and ledger events commit in one caller-owned PostgreSQL transaction or not at
all.

Phase 7 exposes an internal deterministic `CritiqueExplanationHandoff`, not the Phase 9 consensus
explanation or Phase 10 public traversal. It lists the latest head of every Critique logical chain in
stable ledger/id order and includes id, version, target, type, severity, resolution, response disposition,
warrants and replacement target id when present. `OPEN`, `UNRESOLVED` and `DISPUTED` heads are always
included. Empty output carries an explicit reason distinguishing no Critic run from a completed run with
no Critiques.

## 3. Requirement disposition

| Requirement | Phase 7 proof |
| --- | --- |
| FR-205 | shipped Critic attacks every artifact kind through proposal-only shared runtime |
| FR-501 | strict models, prompt fixtures and persistence reject values outside the ten frozen types |
| FR-502 | every committed Critique has one active target, severity and `ATTACKS` edge |
| FR-503 | all seven responses pass mapping, authorization, warrant, retry and atomicity tests |
| FR-504 | handoff returns every latest unresolved/disputed/open Critique without an omit parameter |
| FR-207 | coordinator alone validates, allocates identities, commits, resolves and advances phases |
| FR-208 | Critic and revising agents receive mediated immutable context and expose no peer channel |
| FR-210 | Critiques, responses and revisions preserve complete Phase 6 output attribution |
| FR-302/303 | all resolution and target changes append versions; no artifact is deleted or overwritten |

## 4. Execution slices

1. **T7-01:** strict response/assignment values and Critic-only proposal validation.
2. **T7-02:** shipped Critic definition, sealed prompt and deterministic fixtures.
3. **T7-03:** authorized Critic context, dispatch and inactivity event.
4. **T7-04:** atomic Critique commit with target validation and `ATTACKS`.
5. **T7-05:** response policy, immutable resolution versions and request disposition.
6. **T7-06:** targeted revision commit with `SUPERSEDES` and `RESPONDS_TO`.
7. **T7-07:** deterministic phase ordering and complete explanation handoff fixture.
8. **T7-08:** inherited gates, anti-pattern review, live PostgreSQL/Compose proof and exact-SHA CI.

## 5. Exit evidence

Phase 7 exits only when:

1. a planted unsupported Claim produces an `EVIDENCE_GAP` Critique and visible unresolved handoff entry;
2. the Critic can target every artifact kind, while hidden/fabricated/future/inactive targets produce no
   partial write;
3. all seven responses are explicit, authorized, idempotent and preserve unresolved/disputed state;
4. a valid `REVISE` creates immutable Critique and target successors plus exact graph lineage;
5. inactivity, evidence failure and deferred simulation remain labelled rather than silent or fabricated;
6. backend, frontend, contract, migration, traceability, link, whitespace, Compose and exact-SHA remote CI
   gates pass.