# Errors

**Purpose:** every significant error, its root cause, and the change that makes it not recur. This file
is read before starting work, not after. An error that is fixed without a prevention change here will
recur.

## Format

```text
E-nn · date · one-line summary · severity: blocker | major | minor
Symptom     — what was observed
Root cause  — the actual cause, not the proximate one
Fix         — what changed
Prevention  — the rule, check or test that makes recurrence impossible
```

---

## E-01 · 2026-09-04 · Memory bank claimed documents that did not exist · **major**

**Symptom** `memory-bank/tasks.md` marked `T0-05 … T0-10` complete and `CHANGELOG.md` listed files that
were absent from disk. `docs/` cross-links pointed at documents that had never been written, so roughly
a third of the index was fiction.

**Root cause** The task register was updated from *intent* rather than from the filesystem. Nothing
verified the claim, and the documents that did exist were written before the links to the ones that did
not, so the set was internally consistent only in the author's head.

**Fix** Created the 18 missing documents, corrected `docs/README.md` to match the filesystem, and
rewrote `tasks.md`, `activeContext.md`, `progress.md` and `CHANGELOG.md` against what is actually on
disk.

**Prevention** **TS-06**: a link and file-existence check runs on every docs change and fails on a
missing target. A task may be marked `[x]` only by the process that observed the file. "Claimed done"
without a trace in `TRACEABILITY.csv` is caught by TR-1 once CI exists — which is precisely why TR-1 was
written first.

## E-02 · 2026-09-04 · Phase numbers disagreed across documents · **minor**

**Symptom** The same decision carried different phase numbers in different files: Z3 appeared as Phase 8
in an ADR and Phase 11 in the roadmap; the frontend as 7 and 14; research strategies as 12/15 and 16.

**Root cause** Documents were written in different passes against a phase list that lived only in
`README.md`, with no canonical table to cite.

**Fix** Unified every `Phase:` field against the roadmap in [../README.md](../README.md) and
[PLAN.md](PLAN.md); recorded as decision D-08.

**Prevention** [PLAN.md](PLAN.md) is the single definition of phase numbering. A new document's `Phase:`
field must reference a phase that exists there.

## E-03 · 2026-09-04 · Editor writes above ~6 KB failed · **minor**

**Symptom** Several large documents were rejected outright by the editing tool, and one partial write
left a file truncated mid-section.

**Root cause** Treating a document as one write operation instead of a sequence of appends, and not
re-reading the file after a failure to learn how much had landed.

**Fix** Large documents were split into create-then-append operations, each under the limit.

**Prevention** Any document expected to exceed ~5 KB is created in sections and verified by reading the
tail after each append. A failed write is followed by a read, never by a retry of the same payload.

## E-04 · 2026-09-04 · Shell output could not be captured · **minor**

**Symptom** `Get-ChildItem` and `git status` returned exit code 1 with the command echoed but no usable
stdout; a redirect to a file produced UTF-16 content that read as mojibake.

**Root cause** Shell integration on this host does not reliably report completion, and PowerShell
`>` redirection defaults to UTF-16LE.

**Fix** Used a single command per call, and read directory contents through the file tools instead.

**Prevention** For listings, prefer the file-reading tools. When redirection is required, pipe through
`Out-File -Encoding utf8`. Never infer success from an empty result: an empty listing and a failed
command look identical here.

## E-05 · 2026-09-04 · `CURRENT_STATE.md` asserted an untrue repository fact · **minor**

**Symptom** The first draft stated the repository was not under Git. It is initialised — with zero
commits, which is the actual problem.

**Root cause** Writing a state file from memory of the session rather than from observation, which is
E-01 in miniature.

**Fix** Corrected to "initialised, zero commits", then the first commit was made in this session — which
immediately exposed that the recorded identity did not exist (`E-06`).

**Prevention** Facts about the repository in state files must come from a command run in the same
session, and the command is named next to the fact.

---

## E-06 · 2026-09-04 · First commit failed: `Author identity unknown` · **minor**

**Symptom** `activeContext.md` recorded that a repository-local Git identity had been configured. It had
not: `git commit` failed with `fatal: unable to auto-detect email address (got 'esp@MSI.(none)')`.

**Root cause** An assumption written into a state file as though it were an observation — the same class
of error as E-01, one level down. The configuration step was planned and then never executed, and nobody
re-checked the claim.

**Fix** Set a repo-local placeholder identity and committed `3aa05c1` (82 files, clean tree). Corrected
the assumption in `activeContext.md` §5.3 and flagged the placeholder as an open item.

**Prevention** Environment claims in state files carry the command that verified them. A placeholder
identity is recorded as a placeholder, never as a configuration.

---

## E-07 · 2026-09-04 · Full-stack integration harness produced two false negatives · **minor**

**Symptom** The first all-integration run against Compose failed when the NATS test created a stream
whose subject overlapped the application's existing `agora.>` stream, and when Redis resolved
`localhost` to IPv6 although Compose publishes only on IPv4 loopback.

**Root cause** The integration fixtures assumed a dedicated empty server and an unspecified host
address family. Those assumptions were valid for disposable single-service runs but not for the full
stack.

**Fix** Added `TEST_NATS_STREAM` so the suite can intentionally reuse the Compose stream, and used
`127.0.0.1` for all host-side Compose test endpoints. The unchanged assertions then passed: five live
integration tests in one run.

**Prevention** Full-stack CI sets the stream name and explicit IPv4 endpoints. A test requiring its own
server must use non-overlapping subjects or a separate disposable service, never silently assume an
empty shared JetStream account.

---

## E-08 · 2026-09-04 · PowerShell split a quoted pytest marker expression · **minor**

**Symptom** `Start-Process -ArgumentList '-m','pytest','-m','not integration','-q'` reached pytest as a
path named `integration`, so pytest exited 4 without collecting tests.

**Root cause** PowerShell's native argument serialization did not preserve the marker expression as
one argument.

**Fix** Used the default test run, whose integration modules self-skip without `TEST_*` variables.

**Prevention** Prefer a checked script or argument array that is proven on this host; never interpret
pytest exit 4 as a test failure, and always inspect captured stderr.

---

## E-09 · 2026-09-05 · First remote CI exposed three checkout/tooling mismatches · **major**

**Symptom** GitHub Actions run `33922160948` failed backend formatting before Ruff started, frontend
lint while loading a typed rule for a JavaScript utility, and Compose startup because the backend
container could not import `app.adapters.secrets`.

**Root cause** CI used `uv sync --dev` even though development tools are a project optional extra,
typed TypeScript ESLint presets were applied globally to an `.mjs` file outside either TS project, and
the global `.gitignore` pattern `secrets/` silently omitted the source adapter package. Local Compose
still saw ignored working-tree files, so it did not reproduce a clean checkout.

**Fix** CI and docs now use `uv sync --extra dev --frozen`; typed ESLint presets are scoped to
TypeScript while Node scripts retain regular JS linting; runtime secret directories are root-anchored
in `.gitignore`, and the adapter package is tracked.

**Prevention** CI installs the declared optional extra explicitly, typed rules declare their file scope,
and source package names cannot be swallowed by a global secret-directory ignore. The remote clean
checkout remains the authoritative Phase 1 exit gate.

---

## E-10 · 2026-09-05 · Asyncpg rejected multi-statement trigger DDL · **major**

**Symptom** Both live PostgreSQL migration tests failed while applying revision `20260905_0004`; asyncpg
reported that multiple commands cannot be inserted into a prepared statement.

**Root cause** One `op.execute()` string contained both `CREATE FUNCTION` and `CREATE TRIGGER`. Alembic's
offline SQL renderer accepted it, but the async SQLAlchemy/asyncpg migration path prepares one statement
per execution and rejects combined commands.

**Fix** Split function and trigger creation into separate `op.execute()` calls. Clean upgrade then
succeeded against PostgreSQL.

**Prevention** Every migration containing procedural DDL must run through the live async migration path;
offline SQL generation alone is not acceptance evidence. Keep one SQL command per `op.execute()` when
the production driver is asyncpg.

---

## E-11 · 2026-09-05 · SQLAlchemy result converted to dict before materialization · **minor**

**Symptom** Live registry schema assertions raised `TypeError: 'CursorResult' object is not subscriptable`
after the migration itself succeeded.

**Root cause** `dict(result.tuples())` let `dict` treat SQLAlchemy's result object as mapping-like instead
of consuming row tuples.

**Fix** Materialized tuple rows with `.tuples().all()` before passing them to `dict`.

**Prevention** Catalog-query assertions materialize SQLAlchemy results explicitly before collection
conversion. Live PostgreSQL tests remain the gate for driver/result API assumptions.

---

## E-12 · 2026-09-06 · Temporal rejected a bare `object` workflow type hint · **minor**

**Symptom** The live T4-01 worker accepted and polled the test workflow, but every workflow task failed
argument decoding and the execution remained `RUNNING`; Temporal reported `Unserializable type during
conversion: <class 'object'>`.

**Root cause** The test-only workflow declared `dict[str, object]`. Temporal's converter uses runtime
annotations as a deserialization schema and deliberately cannot construct an unconstrained `object`.

**Fix** Replaced the vague annotation with the exact versioned JSON input shape used by the contract.
The same live test then completed the workflow and the full 28-test integration suite passed.

**Prevention** Every workflow/activity argument and result must have a concrete serializable type; bare
`object` and `Any` are forbidden at workflow boundaries. A real worker poll/execute/complete test remains
part of T4-01 acceptance so converter compatibility cannot be inferred from start-only tests.

---

## E-13 · 2026-09-07 · Coordinator test patch landed in the wrong runtime fixture · **minor**

**Symptom** The 20-agent attribution test still returned empty proposal bundles while an unrelated
post-accounting budget fixture returned claim proposals. An integration insert also briefly contained a
duplicated escaped SQL fragment.

**Root cause** Similar `ProposalBundle` return blocks and adjacent SQL literals were patched without enough
class/function context, so text matching selected the wrong fixture and duplicated query text.

**Fix** Restored the accounting fixture to an empty bundle, moved the claim proposal into
`TwentyAgentRuntime`, and retained one bound `CAST(:budget AS jsonb)` insert statement. The 20-agent test now
commits and attributes 20 claims through the real coordinator committer.

**Prevention** Patches against repeated fixture shapes include the enclosing class/function name and are
verified by reading both source and target blocks. Focused tests run before broad gates; integration SQL is
collected and rendered through Alembic even when live PostgreSQL settings are unavailable.

---

## E-14 · 2026-09-07 · GitHub rejected a commit with a protected author email · **minor**

**Symptom** The first T6-08 push was rejected with GitHub error `GH007`; the remote branch remained
unchanged.

**Root cause** Repository-local Git identity used the account's protected personal email instead of its
GitHub no-reply address.

**Fix** Updated this repository's Git email to the account no-reply address and amended the unpublished
commit author/committer metadata before retrying the normal push.

**Prevention** Before publishing a new branch commit, compare the configured identity with repository host
privacy policy. Amend only unpublished commits; never rewrite already published history for this check.

---

## E-15 · 2026-09-07 · PostgreSQL token sums crossed the adapter as decimals · **major**

**Symptom** The T6-08 live persistence test failed when strict `BudgetUsage` rejected `Decimal('30')` and
`Decimal('12')` for integer token totals, although the stored call-record columns contain integers.

**Root cause** PostgreSQL promotes `SUM(bigint)` to `numeric`; asyncpg therefore returned token aggregates
as `Decimal`. The offline policy fake returned Python integers and did not exercise the database driver's
aggregate type boundary.

**Fix** The coordinator policy adapter now converts only finite, mathematically integral decimal token
aggregates to Python integers before constructing the strict domain value. Boolean, fractional, non-finite,
and string values still fail closed.

**Prevention** Unit coverage now models PostgreSQL's aggregate result type and its invalid variants. The live
membership/usage acceptance remains a Phase 6 gate, so database expression types cannot be inferred from
the mapped source-column annotation.

---

## E-16 · 2026-09-07 · Live budget fixture tried to mutate an immutable definition · **minor**

**Symptom** After the aggregate-type fix, the T6-08 live test failed while changing the injected agent's
budget to malformed JSON; PostgreSQL correctly raised `referenced agent definitions are immutable` before
the adapter validation assertion ran.

**Root cause** The acceptance fixture combined two independent checks by corrupting a definition after a
membership intervention had marked it referenced. This contradicted the Phase 2 immutable-on-use invariant.

**Fix** The fixture now inserts a separate unreferenced active definition with malformed legacy budget JSON
and verifies fail-closed adapter loading against that row. The referenced definition remains immutable.

**Prevention** Persistence fixtures must not bypass or fight an earlier-phase invariant to exercise a later
adapter branch. Seed malformed legacy values on isolated rows before reference, and retain separate database
assertions for immutable-on-use behavior.

---

## E-17 · 2026-09-07 · Random ciphertext made the tamper test flaky · **major**

**Symptom** Exact-SHA GitHub Actions run `34147291409` failed one of 479 offline tests because
`test_envelope_rejects_tampering_and_cross_workspace_replay` did not raise; all other substantive jobs,
including the 42-test live suite, passed.

**Root cause** The test replaced the random ciphertext's final byte with literal `b"x"`. When that byte was
already `0x78`—a 1/256 event—the purported tampering was a no-op and valid AES-GCM decryption correctly
succeeded. A 4,096-envelope reproduction observed 18 such collisions.

**Fix** Flip the final ciphertext byte's low bit with XOR, guaranteeing a one-byte authenticated-content
change while preserving the envelope shape.

**Prevention** Random cryptographic test values are mutated relative to their observed value, never replaced
with a fixed value that may already be present. The focused security test is stress-run before the complete
offline gate and exact-SHA CI.

---

## E-18 · 2026-09-07 · Critic inactivity implementation drifted from the three-round contract · **major**

**Symptom** The first T7-03 implementation emitted `CRITIC_INACTIVE` after one completed empty Critic turn,
although `AGENT_MODEL.md` C-6 requires three rounds without a Critique.

**Root cause** The Phase 7 acceptance draft paraphrased inactivity as a single zero-output event and the code
followed that draft without rechecking the older Critic-specific invariant.

**Fix** Reconciled the acceptance/task wording and require an exact coordinator-supplied prior count of two;
the third consecutive completed empty round emits once, while earlier and later rounds and timeouts do not.

**Prevention** Focused tests cover counts zero, one, two and three plus timeout. Phase planning must search the
domain-specific model document for every named event before freezing its trigger semantics.

---

## E-19 · 2026-09-07 · Migration acceptance retained the previous schema head · **major**

**Symptom** The complete Phase 7 Compose integration suite upgraded through migration `20260907_0019`
successfully, but `test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` still expected head
`20260907_0018` and omitted the two Phase 7 response tables from its explicit head-schema census.

**Root cause** Focused `0019` upgrade/downgrade and response-persistence tests were added without updating
the older cumulative linear-migration acceptance fixture that hard-codes the current head and table set.

**Fix** Updated the cumulative test to require head `20260907_0019` and the
`critique_response_requests` and `critique_response_results` tables after re-upgrade.

**Prevention** Every migration must update and run the cumulative head-version and table-census acceptance
test in the same commit, in addition to its focused migration-cycle proof. Phase exit always runs the full
integration marker, not only the new migration's focused tests.

---

## E-20 · 2026-09-11 · Phase 8 migration was not represented in cumulative metadata/head acceptance · **major**

**Symptom** T10-01 live traversal migrations reached `20260909_0020`, but the cumulative reasoning test still
expected `20260907_0019`; `alembic check` wanted to remove both simulation tables. A clean head upgrade also
exposed `requested_by REFERENCES session_agents(id)`, although `session_agents` has a composite primary key
and no `id` column.

**Root cause** The Phase 8 migration landed without corresponding SQLAlchemy table metadata or an update to
the cumulative head/table census, and its requester foreign key targeted a nonexistent scalar key.

**Fix** Added matching simulation row metadata, registered it in Alembic metadata, repaired the requester FK
to `agent_definitions.id`, normalized JSONB defaults, and updated the cumulative head/table assertions.

**Prevention** Every migration must ship matching metadata (or an explicit Alembic comparison exclusion),
run from an empty schema, pass `alembic check`, and update the single-head/table-census acceptance in the same
change.

## E-21 · 2026-09-14 · Phase 12 ORM metadata omitted `ck_marl_episodes_status_shape` · **major**

**Symptom** Fourteen integration migration tests failed with
`alembic.util.exc.AutogenerateDiffsDetected` — `alembic check` wanted to `remove_constraint`
`ck_marl_episodes_status_shape` from `marl_episodes` on a freshly migrated schema.

**Root cause** Migration `20260912_0024` creates four CHECK constraints on `marl_episodes`, but
`MarlEpisodeRow` (`backend/app/db/models/marl.py`) declared only three; the status-shape constraint was
missing from the ORM metadata, so autogenerate read it as drift.

**Fix** Declared the missing constraint as `CheckConstraint(..., name="status_shape")` on `MarlEpisodeRow`,
which the shared naming convention (`ck_%(table_name)s_%(constraint_name)s`) renders identically to the
migration's `ck_marl_episodes_status_shape`. No migration file changed; the 14 tests now pass.

**Prevention** ORM metadata must mirror every migration constraint one-to-one (E-20 rule), and the
integration suite runs that `alembic check` from an empty schema on the compost stack as a standard gate.

## E-22 · 2026-09-14 · Head acceptance retained a stale pre-Phase-11 head literal · **major**

**Symptom** `test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` failed at
`test_reasoning_persistence.py` after fixing E-21: `version_num` was `20260912_0024` but the test asserted
`20260911_0021`, and the head table census also excluded the Phase 11/12 tables.

**Root cause** The migration chain grew past `20260911_0021` (`0022`, `0023`, `0024`) without updating the
test's hardcoded head literal or its head-tables census — the same staleness class as E-19/E-20.

**Fix** The head assertion now compares against `ScriptDirectory.from_config(config).get_current_head()`
instead of a literal, and the census gained `_PHASE_11_TABLES` (`formalizations`,
`formalization_validations`, `formalization_decisions`, `symbolic_evaluations`) and `_PHASE_12_TABLES`
(`marl_episodes`, `marl_trajectory_records`).

**Prevention** Head assertions in migration-acceptance tests must derive the head from the Alembic
ScriptDirectory at runtime, never hardcode it, so future chain growth cannot reintroduce stale literals.


## E-23 · 2026-09-14 · Head-tables census did not anticipate the Phase 13 tables · **minor**

**Symptom** The live PostgreSQL suite failed exactly one test —
`test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` — after `20260912_0025` because the
head-tables census set did not yet include `access_log` and `audit_anchors`.

**Root cause** The E-22 fix extended the census through Phase 12, so the pattern was correct; the census
is inherently owned by whichever phase adds the next tables and must be extended in that phase.

**Fix** Added `_PHASE_13_TABLES = ("access_log", "audit_anchors")` and spread it into the census set; the
suite is green and `alembic check` reports no drift at head.

**Prevention** Whenever a migration adds tables, extend the census in the same change — the integration
gate already enforces this by failing, so it cannot silently rot.


---

## Watch list (not errors yet)

| Risk | Why it is here |
| --- | --- |
| Documentation volume outpacing review | ~45 documents is past the point where one reader can hold them consistent; the checks in TS-05/TS-06 are the substitute |
| Estimates in [TASKS.md](TASKS.md) are unfalsifiable so far | no phase has been executed; expect the Phase 1 actuals to invalidate them |
| `TRACEABILITY.csv` is hand-seeded | it is meant to be generated; a hand-maintained matrix will drift exactly like the task register did |
