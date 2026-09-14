# Traceability

**Version:** 1.0 · **Status:** design
**Artefact:** `project/TRACEABILITY.csv` · **Requirements:** [REQUIREMENTS.md](REQUIREMENTS.md) ·
**Enforced by:** CI check `make trace-check`

## 1. What is traced

Traceability here means: for any requirement, name the code and the test that satisfy it; for any
line of code, name the requirement that justifies it. Both directions must resolve, and the check
runs in CI rather than in someone's memory.

```text
origin (goal / risk / research question)
   → requirement (FR-/NFR-/ADR-)
      → design section (docs/*.md §n)
         → module / port / adapter (code path)
            → test id (unit | integration | e2e | property)
               → release note (CHANGELOG entry)
```

## 2. Identifier discipline

| ID form | Owner | Stability rule |
| --- | --- | --- |
| `FR-nnn`, `NFR-nnn` | [REQUIREMENTS.md](REQUIREMENTS.md) | never reused; retirement marks the row `RETIRED` with the reason and the successor id |
| `ADR-nnn` | [adr/](adr/) | never edited after acceptance; supersede with a new number |
| `T<n>-<nn>` | [../memory-bank/tasks.md](../memory-bank/tasks.md) | scoped to a phase, not reused |
| `EP-01 … CA-03` | [METRICS.md §4](METRICS.md) | additive only; deprecation keeps the row |
| `P-1 … P-10`, `C-1 …`, `E-1 …` | the document that defines them | invariants are cited by id in code comments and test names |
| `T-n` (threats) | [THREAT_MODEL.md](THREAT_MODEL.md) | one id per threat, controls cite it |

An id that appears in code must appear in exactly one defining document. Two definitions of the
same invariant is the most common way a document set rots.

## 3. The matrix

`project/TRACEABILITY.csv`, generated and checked, never hand-edited:

| Column | Content |
| --- | --- |
| `req_id` | `FR-`/`NFR-` id |
| `title` | short text, copied from REQUIREMENTS.md |
| `design_refs` | `docs/FILE.md#section` — at least one |
| `code_paths` | repository-relative files, from `# trace:` / `// trace:` annotations |
| `tests` | test node ids, from Python `@req(...)` or frontend `// req:` markers |
| `status` | `implemented` / `partial` / `planned` / `retired` |
| `phase` | the phase that closes it |
| `last_verified` | CI run id where the mapping was last green |

Annotations in code:

```python
# trace: FR-602, FR-603
def feasibility_gate(ctx: ConsensusContext) -> FeasibilityReport: ...

@req("FR-602")
def test_hard_constraint_violation_blocks_recommendation(...): ...
```

Python source annotations must immediately precede a function or class, apart from blank lines.
TypeScript/JavaScript source annotations follow the same rule and may target a named
`function`, `class`, `const`, `let`, `var`, `interface`, or `type`. Put the marker at the smallest
implementation symbol that enforces the cited behaviour; do not mark an import, a whole module,
or an unrelated helper merely because it is nearby.

Backend tests use the side-effect-free decorator from `tests.traceability`:

```python
@req("FR-602", "FR-603")
def test_infeasible_alternative_is_never_ranked() -> None: ...
```

A Python module may instead set `pytestmark = req("FR-...")` (or include that call in the
`pytestmark` list) only when every test in that module verifies the same requirement. A test-level
decorator takes precedence over the module marker.

Frontend Vitest/Jest tests use an immediately preceding line marker. The generated node id includes
the file, source line/column, and title so duplicate titles remain unambiguous:

```typescript
// req: FR-104
it("pauses a running session", async () => { ... });
```

Each test must cite only requirements whose observable behaviour it actually asserts. Broad
module-level mappings and catch-all requirements are not acceptable substitutes for behavioural
evidence. `project/traceability_metadata.json` contains only lifecycle fields (`status`, `phase`, and
`last_verified`) and must contain exactly one entry for every requirement in `REQUIREMENTS.md`.

<!-- trace: NFR-006 -->
## 4. Coverage rules

- **TR-1** Every `FR-`/`NFR-` has ≥ 1 design ref and ≥ 1 test, or its status is `planned` and it
  is not claimed done in `memory-bank/tasks.md`. This rule is the reason this document exists.
- **TR-2** Every backend Python and frontend Vitest/Jest test cites ≥ 1 requirement. A test with no citation is either
  undocumented behaviour or a duplicate; CI rejects it.
- **TR-3** Every `code_paths` glob resolves to at least one existing file. Stale mappings fail
  the build, because a mapping to a deleted file is worse than no mapping.
- **TR-4** Invariants (`C-`, `E-`, `NS-`, `RL-`, `X-`) are cited at their enforcement point.
- **TR-5** ADRs cite the requirements they trade off; a decision that serves no requirement is a
  preference, and belongs in [../project/DECISIONS.md](../project/DECISIONS.md) instead.

## 5. Change protocol

| Event | Required action |
| --- | --- |
| Requirement wording changes | update REQUIREMENTS.md, re-read every design ref, re-run the tests named in the row |
| Requirement retired | mark `RETIRED`, keep the row, delete the tests that existed only for it, note it in CHANGELOG |
| New requirement | add the row with `planned` before implementation starts |
| Code deleted | CI reports the orphaned mapping; either re-point or retire |
| Test flaky | status drops to `partial` automatically; a `partial` row blocks the phase gate that claims it |

## 6. Orphan detection

CI runs three greps and fails on any hit:

| Orphan | Detection |
| --- | --- |
| Requirement with no code and no test, claimed done | matrix `status` vs `memory-bank/tasks.md` |
| Code with a `# trace:` id that does not exist | id resolution against REQUIREMENTS.md |
| Document section that references a missing file | link check across `docs/`, `adr/`, `consensus-formalism/` |

The third is the one that catches documentation drift, which is the failure mode this whole
reconciliation pass exists to fix.

## 7. Human-facing views

- **Per phase:** "what does closing Phase 6 require" — filter by `phase`.
- **Per requirement:** open the row, follow `design_refs` → `code_paths` → `tests`.
- **Per gap:** sort by `status` and read the bottom of the list; that list *is* the backlog.
- **Per claim:** before any "done" is written to `memory-bank/tasks.md`, the row must be
  `implemented` in a green CI run.

## 8. Related

[REQUIREMENTS.md](REQUIREMENTS.md) · [TESTING.md](TESTING.md) ·
[../project/TRACEABILITY.csv](../project/TRACEABILITY.csv) ·
[../memory-bank/tasks.md](../memory-bank/tasks.md) · [AUDITABILITY.md](AUDITABILITY.md)
