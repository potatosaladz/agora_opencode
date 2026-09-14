# Experimentation

**Version:** 1.0 · **Status:** design
**Requirements:** FR-903 … FR-908 · **Depends on:**
[REPRODUCIBILITY.md](REPRODUCIBILITY.md), [METRICS.md](METRICS.md) ·
**Storage:** `experiments`, `experiment_runs` ([DATA_MODEL.md §11](DATA_MODEL.md))

## 1. Why this is a first-class subsystem

The platform's deliverable is not only a recommendation engine; it is a claim that some
configurations of collective reasoning are more defensible than others. That claim needs an
experiment harness with the same rigour as the reasoning it studies, otherwise the project is a
dashboard with a hypothesis attached.

**EX-1** An experiment is a recorded object in the database, not a notebook someone ran.
**EX-2** Its inputs are a configuration diff against a named baseline, never a prose description.
**EX-3** Its outputs are metric profiles, not composite scores (FR-901).

## 2. Experiment definition

```jsonc
{ "experiment_id": "exp_01H…", "name": "critic-role-ablation",
  "question": "Does a dedicated Critic agent raise attack coverage without collapsing dissent?",
  "hypothesis": "H1: presence of ag_critic raises DH-03 ≥ 0.2 and does not lower DH-02",
  "primary_metrics": ["DH-03", "DH-02", "EP-01"],
  "guard_metrics":   ["DH-05", "CE-01", "CQ-05"],
  "factors": { "agent_set": ["with_critic","without_critic"],
               "protocol":  ["deliberative"],
               "strategy":  ["constraint_aware"] },
  "tasks": { "suite": "policy-eval-v3", "n": 24, "held_out": 8 },
  "seeds": [20260901, 20260902, 20260903, 20260904, 20260905],
  "baseline": { "session_ids": ["ses_01H…"], "config_hash": "sha256:…" },
  "stopping": { "max_cost_usd": 120, "max_wallclock_h": 12 },
  "preregistration": { "written_at": "…", "analysis_plan": "…", "locked": true } }
```

Cells are the Cartesian product of factors; each cell × task × seed is one `experiment_runs` row
holding a session id and a metric profile. A 2 × 1 × 1 design at 24 tasks and 5 seeds is 240
sessions — the cost is stated before the run, not discovered after it.

## 3. Controls and baselines

| Comparison | Purpose |
| --- | --- |
| rule-based coordinator | the default everyone forgets to compare against |
| round-robin protocol | separates "protocol design" from "extra LLM calls" |
| no-Critic ablation | measures whether adversarial structure does anything |
| single-agent, same budget | the honest floor: is the collective needed at all |
| strategy alternatives | whether the mechanism drives the answer more than the evidence does |

The single-agent control is mandatory for any claim of the form "collective reasoning improves…".

## 4. Protocol

1. **Pre-register** the question, hypothesis, primary and guard metrics, analysis plan and seed
   list. Lock it. Changing the primary metric after seeing results is recorded as such, and the
   report says so in its first line.
2. **Freeze** everything: agent definitions, prompt hashes, index versions, engine versions,
   provider versions. The freeze is part of the manifest.
3. **Run** cells in randomised order to decorrelate from provider load and cache warmth.
4. **Verify** strict replay on a 5 % sample before analysis; a cell that fails replay is excluded
   and the exclusion is reported.
5. **Analyse** per the plan: paired comparisons within task, bootstrap CIs over tasks, effect
   sizes with intervals. No p-values without an effect size.
6. **Report** using §6, and link every number to its `metric_version` and `inputs_hash`.

## 5. Statistical rules

- **ST-1** The unit of analysis is the task, not the session. Five seeds on 24 tasks give 24
  independent observations, not 120.
- **ST-2** Guard metrics can veto a positive primary result. Raising DH-03 by collapsing DH-02 is
  a failure, not a trade-off to be averaged.
- **ST-3** Multiple comparisons across the catalogue are corrected (Holm) and the correction is
  stated.
- **ST-4** Negative and null results are published in
  [RESEARCH_NOTES.md](RESEARCH_NOTES.md). An experiment that found nothing is information.
- **ST-5** A provider version change mid-experiment invalidates the affected cells; the run is
  resumed under a new experiment id, not patched.

## 6. Report template

```markdown
# exp_01H… — <name>
Question / hypothesis (pre-registered <date>, locked)
Design: factors, tasks n, held-out n, seeds, baseline config_hash
Integrity: replay sample pass rate, excluded cells and why
Primary results: per metric, paired effect with 95% CI, n
Guard metrics: table, with any veto triggered
Cost: tokens, USD, wall-clock per cell
Threats to validity: what this design cannot see
Reproduction: crp experiment run exp_01H… --mode strict
Conclusion: supported / not supported / inconclusive, with the reason
```

"Inconclusive" is a permitted and common conclusion. "Promising" is not.

## 7. Pitfalls known in advance

| Pitfall | How it shows up | Counter |
| --- | --- | --- |
| Metric gaming | EP-01 rises, EP-03 falls | guard metrics; [METRICS.md §7](METRICS.md) |
| Provider confound | the "better" arm used a newer model | freeze plus per-version reporting |
| Task leakage | tuned prompts evaluated on tuning tasks | held-out set never used for iteration |
| Survivorship | failed sessions dropped from analysis | report the failure rate as a primary outcome |
| Seed luck | one seed drives the effect | ≥ 5 seeds, paired analysis |
| Cost blindness | the winning arm costs 8× | cost is a guard metric, always reported |
| Narrative drift | the conclusion is written before the table | template order enforced: table first |

## 8. Research-track experiments

MARL studies ([MARL_MODEL.md §8](MARL_MODEL.md)) and consensus strategy bake-offs follow the same
protocol, with two additions: the policy under study must be versioned and disable-able by
configuration, and no research experiment may write to production knowledge namespaces.

## 9. Related

[METRICS.md](METRICS.md) · [REPRODUCIBILITY.md](REPRODUCIBILITY.md) ·
[CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) · [RESEARCH_NOTES.md](RESEARCH_NOTES.md) ·
[MARL_MODEL.md](MARL_MODEL.md) · [MVP_BOUNDARY.md](MVP_BOUNDARY.md)

