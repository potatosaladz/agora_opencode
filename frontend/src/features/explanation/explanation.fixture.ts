import type { ExplanationResponse } from "../../api/client";

const number = (value: string, kind: string, unit = "count") => ({
  value,
  kind,
  unit,
  version: "fixture-v1",
  caveat: "Persisted value; interpretation is limited to its recorded kind.",
});

export const explanationFixture = {
  data: {
    session_id: "ses_public",
    status: "AVAILABLE",
    empty_reason: null,
    decision: {
      empty_reason: null,
      consensus_result_id: "con_public",
      outcome: "CONDITIONAL_CONSENSUS",
      selected_alternative_id: "art_bus",
      round: number("3", "consensus round"),
    },
    recommendation: {
      empty_reason: null,
      items: [
        {
          id: "rec_bus",
          alternative_id: "art_bus",
          title: "Adopt the staged electric bus rollout",
          statement: "Begin with the north corridor and retain a review gate.",
          rank: number("1", "recommendation rank"),
          conditions: ["Review after first winter"],
        },
      ],
    },
    why: {
      empty_reason: null,
      formula: "Persisted constraint-aware derivation",
      strategy: "constraint_aware",
      strategy_version: "2",
      weights: {},
      thresholds: {},
      derivation: [
        {
          step: number("1", "derivation step"),
          stage: "feasibility",
          description:
            "The staged rollout satisfies the recorded statutory cap.",
        },
        {
          step: number("2", "derivation step"),
          stage: "selection",
          description:
            "The reversible deployment sequence was selected over the remaining alternatives.",
        },
      ],
      contributions: [],
      caveats: ["The winter survey has incomplete provenance."],
      drivers: {
        empty_reason: null,
        items: [{ artifact_id: "art_cost", relationship: "SUPPORTS" }],
      },
      inhibitors: {
        empty_reason: null,
        items: [
          { artifact_id: "art_winter", relationship: "OPPOSES" },
          {
            critique_id: "crt_weather",
            relationship: "UNRESOLVED_CRITIQUE",
            resolution: "UNRESOLVED",
          },
        ],
      },
      absent: {
        empty_reason: null,
        items: ["Independent winter fleet validation is missing"],
      },
    },
    alternatives: [
      {
        id: "art_rail",
        kind: "ALTERNATIVE",
        label: "Accelerated light rail",
        lifecycle: "ACTIVE",
        content: {
          summary:
            "Not selected because the recorded capital constraint was not satisfied.",
        },
        provenance_href: "/api/v1/artifacts/art_rail/provenance",
      },
    ],
    evidence: {
      empty_reason: null,
      supporting: [
        {
          id: "art_cost",
          kind: "EVIDENCE",
          label: "Fleet procurement estimate",
          lifecycle: "ACTIVE",
          relation: "SUPPORTS",
          verification: "SOURCE_VERIFIED",
          weight: number("18.4", "capital estimate", "USD million"),
          citations: [{ source: "procurement ledger" }],
          provenance_href: "/api/v1/artifacts/art_cost/provenance",
        },
        {
          id: "art_old",
          kind: "EVIDENCE",
          label: "Withdrawn supplier quotation",
          lifecycle: "WITHDRAWN",
          relation: "SUPPORTS",
          verification: "REJECTED",
          citations: [],
          provenance_href: "/api/v1/artifacts/art_old/provenance",
        },
      ],
      opposing: [
        {
          id: "art_winter",
          kind: "EVIDENCE",
          label: "Winter range degradation report",
          lifecycle: "ACTIVE",
          relation: "OPPOSES",
          verification: "DISPUTED",
          quote: "Cold-weather range may require additional vehicles.",
          citations: [{ source: "field trial" }],
          provenance_href: "/api/v1/artifacts/art_winter/provenance",
        },
      ],
      qualifying: [],
    },
    assumptions_constraints: {
      empty_reason: null,
      items: [
        {
          id: "art_demand",
          kind: "ASSUMPTION",
          statement: "Demand remains above the service floor",
          lifecycle: "ACTIVE",
          graph_node_id: "gnd_demand",
          provenance_href: "/api/v1/artifacts/art_demand/provenance",
        },
      ],
    },
    minority: [
      {
        agent_id: "agt_equity",
        position: "Prefer the rail alternative",
        what_would_change: "A binding near-term capital limit",
        warrant_artifact_ids: ["art_equity"],
      },
    ],
    critiques: {
      empty_reason: null,
      unresolved: [
        {
          id: "crt_weather",
          artifact_id: "art_critique",
          critique_type: "UNCERTAINTY_UNDERSTATED",
          resolution: "UNRESOLVED",
          argument: "Cold-weather fleet requirement is understated",
          provenance_href: "/api/v1/artifacts/art_critique/provenance",
        },
      ],
      all: [],
    },
    risks_uncertainties: {
      empty_reason: null,
      items: [
        {
          id: "art_supply",
          kind: "RISK",
          label: "Battery supply delay",
          lifecycle: "ACTIVE",
          content: {
            detail: "Delivery timing is unavailable from the supplier.",
          },
          provenance_href: "/api/v1/artifacts/art_supply/provenance",
        },
      ],
    },
    symbolic_feasibility: {
      empty_reason: null,
      constraints: [
        {
          constraint_id: "art_cap",
          status: "UNKNOWN",
          reason: "Solver timed out before a determination.",
          policy_action: "DEFER",
          interpretation: "not determined; symbolic assurance unavailable",
        },
      ],
    },
    conditions_counterfactuals: {
      empty_reason: null,
      conditions: ["Review after first winter"],
      counterfactuals: [
        {
          change: "Depot remediation exceeds the cap",
          effect: "No feasible alternative remains",
        },
      ],
    },
    weakest_evidence: {
      available: true,
      evidence_id: "art_winter",
      rationale:
        "verification=DISPUTED; lifecycle=ACTIVE; citations=present; relation=OPPOSES. This is the recorded weakest-evidence rationale.",
      id: "art_winter",
      label: "Winter range degradation report",
      kind: "EVIDENCE",
      lifecycle: "ACTIVE",
      graph_node_id: "gnd_winter",
      provenance_href: "/api/v1/artifacts/art_winter/provenance",
      version: number("1", "artifact revision"),
      content: {},
    },
    provenance: {
      empty_reason: null,
      complete: false,
      truncated: true,
      next_cursor: "next-page",
      href: "/api/v1/artifacts/art_bus/provenance",
    },
    links: {
      graph: "/api/v1/graph/subgraph",
      dissent: "/api/v1/sessions/ses_public/dissent",
      assumptions: "/api/v1/sessions/ses_public/assumptions",
      provenance: "/api/v1/artifacts/art_bus/provenance",
    },
  },
  meta: { request_id: "request", schema_version: 1, workspace_id: "ws_public" },
} satisfies ExplanationResponse;
