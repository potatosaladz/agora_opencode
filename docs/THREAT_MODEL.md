# Threat Model

**Version:** 1.0 · **Status:** design
**Method:** STRIDE over the trust boundaries in [SECURITY.md §1](SECURITY.md), extended with
LLM-system threats (injection, tool abuse, model-mediated laundering) and deliberation-integrity
threats specific to this platform · **Requirements:** FR-1001 … FR-1007, NFR-010

## 1. Assets

| Asset | Why it matters | Loss consequence |
| --- | --- | --- |
| The ledger's integrity | it is the evidence the platform's claims rest on | every past recommendation becomes unverifiable |
| Workspace data and documents | customer-owned | regulatory and contractual failure |
| Provider and integration credentials | direct cost and lateral movement | unbounded spend, data exfiltration |
| Epistemic status of artifacts | the difference between evidence and assertion | the platform's purpose inverts |
| Dissent records | the research contribution | silent, undetectable degradation of quality |
| Model and prompt IP | competitive and behavioural | prompt-injection surface widens |
| Availability of deliberation | users decide on the timeline | decisions get made without the platform |

## 2. Boundaries and actors

| Boundary | Adversary assumed inside it |
| --- | --- |
| Browser → gateway | anonymous internet, scripted abuse, a malicious invited user |
| Gateway → services | a compromised service, a confused-deputy token |
| Agent → provider | the provider itself (data leakage), a malicious model output |
| Agent → MCP gateway | **the model, manipulated by content** — the primary adversary here |
| MCP server → world | a hostile or compromised third-party server |
| Anything → sandbox | arbitrary attacker-controlled code, by construction |
| Document → retrieval | an author who wants their text believed, or wants to steer the agents |

The last row deserves emphasis: in a system that reasons over documents, **the corpus is an attack
surface**, and its authors are adversaries whether or not they intend to be.

## 3. Register

Likelihood and impact are `L/M/H` for the MVP deployment. "Residual" is what remains after the
listed controls; a blank residual would be a claim nobody should make.

### 3.1 Classic

| ID | Threat | Vector | I | L | Controls | Residual |
| --- | --- | --- | --- | --- | --- | --- |
| T-1 | Cross-tenant read | id enumeration, missing RLS, cache key collision | H | M | RLS on every table, `404` indistinguishability, per-connection workspace setting, CI cross-tenant suite | application bugs until the suite covers every new table |
| T-2 | Privilege escalation via token | over-scoped token, missing check on a new endpoint | H | M | narrow scopes per screen, deny-by-default routing, scope matrix test in CI | human error in a new route; caught by the matrix |
| T-3 | Prompt injection → exfiltration | crafted document or tool result instructs the model to leak context | H | H | two-channel framing, quarantine, no secrets in prompts, egress allowlist, data-class gate | slow multi-turn extraction across sessions; detection is heuristic |
| T-4 | Poisoned corpus | attacker authors a document that becomes evidence | H | M | trust levels, `SOURCE_VERIFIED` requirement, independence test (EP-04), retraction plus impact traversal | plausible, well-cited disinformation still passes |
| T-5 | SSRF via fetch tool | URL to a metadata endpoint or internal service | H | M | connect-time deny list, redirect re-validation, DNS-rebinding closure | IPv6 or resolver edge cases |
| T-6 | Supply chain | malicious dependency or base-image change | H | L | digests pinned, lockfiles, SBOM, Trivy, signed images verified at deploy | a compromised maintainer of a pinned dependency |
| T-7 | Secret leakage | env var, log line, trace attribute, prompt | H | M | Swarm secrets, redaction filter, gitleaks, no secrets in tool arguments | a log written before the filter is installed |
| T-8 | Ledger tampering | direct DB write by a compromised service account | H | L | `REVOKE UPDATE/DELETE`, hash chain, daily external anchors, nightly verification | a DB superuser who also controls both anchor stores |

### 3.2 LLM-system

| ID | Threat | Vector | I | L | Controls | Residual |
| --- | --- | --- | --- | --- | --- | --- |
| T-9 | Unauthorised tool action | model calls a `WRITE` tool | H | M | classification, human approval bound to the rendered call, fail-closed manifest drift | approval fatigue — see T-13 |
| T-10 | Hallucinated citation | model invents a source and asserts it | M | H | provenance required at commit, `HALLUCINATED_SOURCE` critique type, EP-05 with a blocking threshold | a real source cited for a claim it does not support |
| T-11 | Provider retains prompt data | content leaves the perimeter | M | M | data-class gate, per-workspace keys, provider DPA, PII redaction | contractual, not technical |
| T-12 | Model version drift | silent provider update changes behaviour | M | H | `model_version` pinned in the manifest, per-version experiment reporting, tolerant replay diff | drift between pinned versions remains possible |
| T-13 | Approval fatigue | too many `WRITE` approvals, humans rubber-stamp | M | H | batch approvals per round, HO-04 unexamined-acceptance metric, approval-rate alert | a human who reads carefully until they do not |

### 3.3 Deliberation integrity *(platform-specific)*

These are the threats a generic security review misses and that this project cannot afford.

| ID | Threat | Vector | I | L | Controls | Residual |
| --- | --- | --- | --- | --- | --- | --- |
| T-14 | Consensus laundering | pick the strategy or thresholds that produce the preferred answer | H | M | strategy and parameters recorded per result, CQ-06 divergence, flip distance, audit query on strategy changes | an author who picks the task to fit the answer |
| T-15 | Herding collapse | agents converge for social reasons while metrics look healthy | H | M | sealed round 1, DH-05 herding index with a blocking threshold, immutable position history | subtle sycophancy below the threshold |
| T-16 | Metric gaming | optimise a visible metric at the cost of quality | M | H | no composite score (FR-901), guard metrics, [METRICS.md §7](METRICS.md) gaming table | any metric set is gameable by someone outside its rows |
| T-17 | Silent dissent suppression | a UI or export path omits the minority report | H | L | no omit parameter in the contract, contract test asserting dissent presence (FR-506) | a downstream consumer that drops the field |
| T-18 | Rubber-stamped recommendation | a defensible-looking record nobody interrogates | M | H | HO-03/HO-04, explanation-first UI, CQ-05 blocking-critique carry-over | cultural, not technical |
| T-19 | Status inflation | an artifact quietly upgraded from `CLAIM` to `FACT` | H | M | E-2: no LLM path writes `FACT`; `artifacts:validate` scope; `STATUS_CHANGED` events with warrant | a human with the scope who asserts without basis |
| T-20 | Provenance decay | a cited source disappears and the claim stands unqualified | M | H | `STALE_CITATION` flag, EP-02 completeness, retraction keeps rows resolvable | link rot on third-party content we do not mirror |

## 4. Explicitly out of scope for the MVP

| Out of scope | Why, and what would change it |
| --- | --- |
| State-level or organised-crystal adversary | the MVP is a single-region research deployment; the threat model is rewritten if that changes |
| Multi-tenant side channels in shared Postgres | accepted risk with RLS plus per-workspace keys; reconsidered at scale |
| Model-weight exfiltration | we do not own the weights |
| Physical access to hosts | assumed controlled |
| Sybil resistance on agent identity | agents are platform-registered, not user-supplied, until third-party agents are allowed |
| Denial of service beyond rate limiting | Swarm scale-out plus budgets; not a research problem |

## 5. Review cadence and change rules

- Reviewed at each phase gate; a phase cannot close with an unmitigated `H`-impact / `H`-likelihood
  row lacking a control.
- Any PR that adds a table, an endpoint, a tool class or a trust boundary requires a register row
  in the same change ([TRACEABILITY.md §5](TRACEABILITY.md)).
- An incident adds or amends a row; it never edits a row to make past controls look better.
- Controls are cited by id from code (`# trace: T-3`) so that a deleted control is visible as an
  orphan in CI.

## 6. Related

[SECURITY.md](SECURITY.md) · [MCP_SECURITY.md](MCP_SECURITY.md) ·
[REPRODUCIBILITY.md](REPRODUCIBILITY.md) · [METRICS.md](METRICS.md) ·
[ARCHITECTURE.md §9](ARCHITECTURE.md) · [adr/ADR-018](adr/ADR-018-sandbox-execution-boundary.md)

