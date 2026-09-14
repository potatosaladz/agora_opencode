# Research Notes

**Version:** 1.0 · **Status:** living document
**Purpose:** the open questions this platform exists to investigate, and the record of what was
found. Written so that a reader in a year can tell what was asked, what was tried, and what was
merely assumed.

## 1. Central question

**Can a heterogeneous group of language-model agents, constrained by structured evidence,
explicit disagreement and formal feasibility checks, produce a recommendation that a human expert
finds more defensible than one produced by a single agent — and can we measure the difference?**

Sub-questions, each mapped to the mechanism that probes it:

| # | Question | Mechanism | Metric that decides |
| --- | --- | --- | --- |
| Q-1 | Does adversarial structure change outcomes, or only their presentation? | Critic ablation | DH-03, DH-02, CQ-03 |
| Q-2 | Does formalizing constraints prevent worse decisions? | feasibility gate | `RR-05`, `INFEASIBLE` frequency, flip distance |
| Q-3 | Is measured disagreement informative or noise? | proposition-level vectors | DH-01 vs DH-05 correlation |
| Q-4 | Does evidence weighting beat equal weighting? | `evidence_weighted` vs `weighted` | CQ-03, EP-03 |
| Q-5 | When does consensus mislead? | strategy comparison, minority reports | CQ-06, override rate HO-02 |
| Q-6 | Can retrieval quality be measured without ground truth? | paraphrase robustness | RB-04 |
| Q-7 | Do agents calibrate, and does it matter? | outcome-bearing sessions | CA-01, CA-03 |
| Q-8 | Is a learned orchestration policy better than rules? | MARL track | reward vector components vs baseline |
| Q-9 | Does provenance visibility change human decisions? | explanation-first UI | HO-03, HO-04 |
| Q-10 | How much of the value is just "more compute"? | single-agent same-budget control | every primary metric, cost-matched |

**Q-10 is the one that must be answered honestly.** If a single agent with the same token budget
performs as well, the collective is decoration. The control is mandatory in
[EXPERIMENTATION.md §3](EXPERIMENTATION.md) for that reason.

## 2. Working hypotheses

Recorded before the evidence, so that later results read as tests rather than justifications.

| # | Hypothesis | Falsifier | Status |
| --- | --- | --- | --- |
| H-1 | Explicit critique raises provenance completeness more than it raises agreement | EP-02 flat under Critic ablation | untested |
| H-2 | A feasibility gate changes at least one recommendation in ≥ 20 % of constrained sessions | gate never fires, or fires only on nonsense constraints | untested |
| H-3 | Sealed first assessment reduces herding | DH-05 indistinguishable between sealed and open round 1 | untested |
| H-4 | `constraint_aware` and `weighted` disagree materially on real tasks | CQ-06 ≈ 1.0 across the suite | untested |
| H-5 | Dissent visible at decision time increases human examination of provenance | HO-03 unchanged when the panel is prominent | untested |
| H-6 | Model uncertainty dominates epistemic uncertainty in most sessions | RB-03 spread small relative to assumption sensitivity | untested |

## 3. Findings log

Append-only, newest first. A finding without a linked experiment id is a speculation and belongs in
§2 instead.

| Date | Experiment | Finding | Effect on the design |
| --- | --- | --- | --- |
| — | — | *(no experiments run yet; Phase 16 builds the comparative harness)* | — |

## 4. Literature to engage with

Not a bibliography; a reading list with the specific question each source bears on. Entries stay
unannotated until read — a citation not yet engaged with is not evidence
([EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md) §1).

| Area | Engage with | For which question |
| --- | --- | --- |
| Judgment aggregation | Condorcet; List & Pettit on the discursive dilemma; impossibility results | Q-4, Q-5, `bayesian` |
| Deliberative democracy | Dryzek; Elster on deliberation and its constraints | `deliberative`, minority report design |
| Prediction markets | Sunstein on deliberative polls and markets; Harrison & Krieger on microstructure | `prediction_market` |
| Argumentation | Toulmin; Dung abstract argumentation; ASPIC+ | graph edge semantics, defeat rules |
| Multi-agent LLM systems | 2023-2026 literature on LLM debate, self-consistency, agent scaffolds | Q-1, Q-10 |
| Neuro-symbolic | Garcez on neural-symbolic systems; Z3 docs and SMT-COMP results | [NEURO_SYMBOLIC.md](NEURO_SYMBOLIC.md) |
| Calibration | Brier; Dawid; Guo et al. on temperature scaling and its limits for LLMs | CA-01, CA-02 |
| Measurement in social systems | Campbell's law; Strathern's refinement | [METRICS.md §7](METRICS.md), AP-24 |
| System dynamics | Forrester; Sterman on bounded rationality in dynamic systems | [SIMULATION_ARCHITECTURE.md](SIMULATION_ARCHITECTURE.md) |
| MARL | Lowe et al. on non-stationarity; Sunehag et al. on VDN/QMIX; Yu et al. on MAPPO | [MARL_MODEL.md](MARL_MODEL.md) |

## 5. Method notes and limitations

- **No ground truth for policy questions.** Defensibility is the measurable proxy, and it is a
  proxy. A session can be perfectly defensible and practically wrong; the platform must say so.
- **Provider confound** is the largest single threat to any claim here. Every comparison is
  per-version; results spanning a version change are reported as two results.
- **Task selection bias** is unavoidable in a small suite: publish it, never iterate on the held-out
  subset, and record negative results.
- **Researcher degrees of freedom** are constrained by pre-registration
  ([EXPERIMENTATION.md §4](EXPERIMENTATION.md)) — inconvenient, therefore effective.
- **The observer effect.** Making dissent visible changes whether people dissent. That is the
  intervention, not a confound, but it means DH-05 is not a natural quantity.

## 6. Related

[MVP_BOUNDARY.md](MVP_BOUNDARY.md) · [EXPERIMENTATION.md](EXPERIMENTATION.md) ·
[CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) · [METRICS.md](METRICS.md) ·
[../project/PLAN.md](../project/PLAN.md)
