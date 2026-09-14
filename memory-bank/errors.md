# Error Log (memory bank)

Purpose: never solve the same issue twice. Record every **significant** error —
repeated failures, subtle root causes, architectural surprises, environment traps.
Cosmetic one-off typos do not belong here.

Entry format (mandatory):

```text
ERR-###  YYYY-MM-DD
Component:
Symptom:
Reproduction:
Root cause:
Attempted fixes:
Final fix:
Files changed:
Prevention:
```

---

## Open / active errors

**None.** Current defects found by live tests were fixed in the same task and are recorded under
"Resolved" and in the canonical [project error log](../project/ERRORS.md).

---

## Resolved errors

### ERR-008 · 2026-09-07

**Component:** T7-03 Critic inactivity policy
**Symptom:** the initial wrapper emitted `CRITIC_INACTIVE` after one completed empty Critic turn.
**Reproduction:** dispatch one valid empty Critic bundle through `CriticTurnCoordinator`.
**Root cause:** the new acceptance wording lost `AGENT_MODEL.md` C-6's three-round threshold.
**Attempted fixes:** a first correction used `prior >= 2`, which would repeat the event after round three.
**Final fix:** emit only when the coordinator supplies exactly two prior consecutive empty rounds; timeout,
earlier empties and later empties do not emit.
**Files changed:** `docs/PHASE7_ACCEPTANCE.md`, `project/TASKS.md`,
`backend/app/application/critic_dispatch.py`, `backend/tests/unit/test_critic_dispatch.py`.
**Prevention:** tests cover prior counts zero through three and timeout; phase reconciliation searches the
domain-specific model for each named event's complete trigger semantics.

### ERR-007 · 2026-09-07

**Component:** AES-GCM envelope tamper test / exact-SHA backend CI
**Symptom:** one hosted offline run did not raise for a supposedly tampered credential envelope.
**Reproduction:** encrypt repeatedly until the random ciphertext ends in `0x78`; replacing that byte with
literal `b"x"` leaves the envelope unchanged.
**Root cause:** fixed-value replacement was not guaranteed to mutate random bytes; the collision probability
was 1/256 and occurred 18 times in a 4,096-envelope reproduction.
**Attempted fixes:** none; the hosted failure and ciphertext sample identified the no-op mutation directly.
**Final fix:** XOR the final ciphertext byte with `0x01`, guaranteeing an authenticated-byte change.
**Files changed:** `backend/tests/unit/test_envelope_encryption.py`.
**Prevention:** cryptographic tamper tests mutate bytes relative to their current value and are stress-run.

### ERR-006 · 2026-09-07

**Component:** T6-08 live budget fixture / Phase 2 definition immutability
**Symptom:** the live test attempted to corrupt a referenced definition's budget and PostgreSQL correctly
rejected the update before adapter validation.
**Reproduction:** inject an agent definition into session membership, then update its hash-covered budget.
**Root cause:** one fixture coupled malformed legacy-data validation to a row protected by immutable-on-use.
**Attempted fixes:** none; the first post-aggregate-fix run exposed the invariant conflict.
**Final fix:** seed malformed budget JSON on a separate unreferenced active definition and query that row.
**Files changed:** `backend/tests/integration/test_reasoning_persistence.py`.
**Prevention:** later-phase fixtures preserve earlier-phase database invariants; malformed legacy rows remain
isolated from referenced immutable rows.

### ERR-005 · 2026-09-07

**Component:** T6-08 PostgreSQL durable budget aggregation
**Symptom:** the live membership/usage test failed because strict integer token fields received
`Decimal('30')` and `Decimal('12')`.
**Reproduction:** sum the `BIGINT` token columns in PostgreSQL and pass the asyncpg/SQLAlchemy row directly
to strict `BudgetUsage`.
**Root cause:** PostgreSQL returns `numeric` for `SUM(bigint)`; the offline fake returned Python integers.
**Attempted fixes:** none; the first live Phase 6 exit run exposed the adapter mismatch.
**Final fix:** normalize only finite integral `Decimal` aggregates to Python `int` at the adapter boundary;
reject boolean, fractional, non-finite, and string values.
**Files changed:** `backend/app/db/coordinator_policy.py`,
`backend/tests/unit/test_coordinator_policy.py`.
**Prevention:** a unit regression models PostgreSQL aggregate result types and the real PostgreSQL usage test
remains an exit gate.

### ERR-004 · 2026-09-06

**Component:** Temporal workflow argument conversion / T4-01 live worker acceptance
**Symptom:** the test workflow was polled but remained `RUNNING` while workflow tasks repeatedly failed
with `Unserializable type during conversion: <class 'object'>`.
**Reproduction:** annotate a Temporal workflow argument as `dict[str, object]`, start it with a nested
JSON object, and run a worker using the default converter.
**Root cause:** Temporal interprets runtime type hints as conversion schemas and cannot deserialize an
unconstrained bare `object`.
**Attempted fixes:** none; the first live completion test exposed the boundary mismatch directly.
**Final fix:** replaced the annotation with the exact serializable versioned JSON input shape.
**Files changed:** `backend/tests/integration/test_temporal_workflow.py`.
**Prevention:** workflow/activity arguments and results use concrete serializable types; T4-01 retains a
real worker poll/execute/complete integration rather than treating a successful start RPC as sufficient.

### ERR-001 · 2026-09-04

**Component:** workspace inspection / Phase 0 step 1
**Symptom:** `git status` and `git log` failed with
`fatal: not a git repository (or any of the parent directories): .git` when run against
the shared chat workspace root.
**Reproduction:** run any git command in
`C:\Users\baito\.cline\data\workspaces\chat`.
**Root cause:** the shared chat workspace is a data directory for sessions started
without a project; it is intentionally not a repository. The project brief's recovery
protocol assumes a repository exists.
**Attempted fixes:** none appropriate — creating a repository at the shared workspace
root would pollute other sessions' data.
**Final fix:** created a self-contained project directory
`collective-reasoning-platform/` inside the workspace and ran `git init` there, after
confirming the destination with the user.
**Files changed:** repository structure.
**Prevention:** the recovery protocol now states explicitly that `git status` is run
*inside the project directory*; `project/CURRENT_STATE.md` records the project root path
so a future session does not search for it.

### ERR-002 · 2026-09-04

**Component:** repository-local Git identity
**Symptom:** `git config user.email` / `user.name` returned empty on this host, so an
initial commit would fail with "Please tell me who you are".
**Reproduction:** `git init` then `git commit` on a host with no global Git identity.
**Root cause:** no global Git configuration on the development machine.
**Attempted fixes:** considered writing global config — rejected as a change outside the
project's scope.
**Final fix:** set repository-local `user.name` / `user.email` for this project only.
**Files changed:** `.git/config` (not tracked).
**Prevention:** `project/TASKS.md` T1-00 includes "verify git identity" as a Phase 1
prerequisite check.

### ERR-003 · 2026-09-04

**Component:** documentation authoring tooling
**Symptom:** two `editor` writes were rejected: one for exceeding the ~6000-character
per-edit limit, one for an `insert_line` value outside the permitted range.
**Reproduction:** write a single Markdown file larger than ~6000 characters in one edit,
or insert beyond the reported line range.
**Root cause:** per-call payload limits in the editing tool; long normative documents
naturally exceed them.
**Attempted fixes:** none needed beyond the following.
**Final fix:** split large documents into an initial create plus append-style edits
anchored on a unique trailing paragraph; kept each edit under the limit.
**Files changed:** `README.md`, `memory-bank/architecture.md`.
**Prevention:** authoring convention adopted for this project — keep individual document
sections small enough to write in one edit; prefer several focused documents over one
monolith (which also improves reviewability).

---

## Recurring-risk watchlist (not yet errors)

These are the traps most likely to become ERR entries in Phase 1+. Check them first when
something misbehaves.

| # | Watchlist item | Likely symptom | Where mitigated |
| --- | --- | --- | --- |
| W-1 | Nondeterminism inside Temporal workflow code | workflow task failures, replay errors | ADR-003, docs/ARCHITECTURE.md §3 |
| W-2 | Blocking I/O in async event loop | latency spikes, worker starvation | techContext §3 conventions |
| W-3 | Domain layer importing SQLAlchemy/FastAPI | architecture erosion, untestable domain | ADR-012 + import-lint in T1-03 |
| W-4 | Redis used as if durable | lost state on restart | ADR-009 |
| W-5 | NATS treated as source of truth | unreplayable sessions | ADR-004 |
| W-6 | LLM JSON failing schema validation | crashed activities | T2-04 repair-retry policy |
| W-7 | Secret appearing in logs or API responses | credential exposure | ADR-017, docs/SECURITY.md |
| W-8 | pgvector index type mismatch for dataset size | silently poor recall | docs/RAG_ARCHITECTURE.md |
| W-9 | `replicas: 3` mistaken for HA on stateful services | data corruption / split brain | ADR-020 |
| W-10 | Consensus plugin without formalism doc | unverifiable claims of rigour | TS-04, docs/consensus-formalism/ |
| W-11 | Windows path assumptions leaking into code/config | broken container builds | techContext §6 |
| W-12 | Documentation drifting from implementation | false confidence on resume | TS-01/TS-02, recovery protocol |
