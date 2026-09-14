import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  apiClient,
  type DissentResponse,
  type SessionResponse,
} from "../../api/client";
import DissentPage from "./dissent-page";

const connection = {
  session: {
    data: {
      id: "ses_public",
      status: "COMPLETED",
      problem_statement: "Choose a transport policy",
      agent_definition_ids: [],
      objective_ids: [],
      constraint_ids: [],
      budget: { max_rounds: 3, max_tokens: 100, max_usd: "2" },
      round: 3,
      workflow_id: "wf",
      run_id: "run",
      initialized_at: "2026-09-14T10:00:00Z",
      started_at: "2026-09-14T10:00:01Z",
      ended_at: "2026-09-14T10:01:00Z",
    },
    meta: {
      request_id: "request",
      schema_version: 1,
      version: 1,
      workspace_id: "ws_public",
      created_at: "2026-09-14T10:00:00Z",
      updated_at: "2026-09-14T10:01:00Z",
      owner: { id: "usr_public", class: "HUMAN" },
      permissions: ["read"],
      trace: null,
    },
  } as SessionResponse,
  token: "token",
};

const response = {
  data: {
    session_id: "ses_public",
    evaluated: true,
    empty_reason: null,
    majority: {
      consensus_result_id: "cns_public",
      outcome: "CONDITIONAL_CONSENSUS",
      selected_alternative_id: "art_selected",
      selected_alternative_label: "Bus rapid transit",
      selected_alternative_graph_node_id: "gnd_selected",
      selected_alternative_provenance_href:
        "/api/v1/artifacts/art_selected/provenance",
      strategy: "constraint_aware",
      strategy_version: "1.1.0",
      round: 3,
    },
    evidence_context: {
      supports_selected: [
        {
          id: "art_supporting",
          kind: "EVIDENCE",
          label: "Ridership forecast",
          lifecycle: "ACTIVE",
          graph_node_id: "gnd_supporting",
          provenance_href: "/api/v1/artifacts/art_supporting/provenance",
        },
      ],
      opposes_selected: [
        {
          id: "art_opposing_context",
          kind: "EVIDENCE",
          label: "Displacement study",
          lifecycle: "ACTIVE",
          graph_node_id: "gnd_opposing_context",
          provenance_href: "/api/v1/artifacts/art_opposing_context/provenance",
        },
      ],
      qualifies_selected: [],
    },
    minority: [
      {
        agent_id: "agt_critic",
        position: "OPPOSE",
        warrants: [
          {
            id: "art_opposing",
            kind: "EVIDENCE",
            label: "Incidence study",
            lifecycle: "ACTIVE",
            graph_node_id: "gnd_opposing",
            provenance_href: "/api/v1/artifacts/art_opposing/provenance",
          },
          {
            id: "art_withdrawn",
            kind: "EVIDENCE",
            label: "Withdrawn survey",
            lifecycle: "WITHDRAWN",
            graph_node_id: null,
            provenance_href: "/api/v1/artifacts/art_withdrawn/provenance",
          },
        ],
        disputed_proposition_ids: ["art_selected"],
        unresolved_critique_ids: ["crt_open"],
        what_would_change: "Verified distributional evidence",
      },
      {
        agent_id: "agt_abstainer",
        position: "ABSTAIN",
        warrants: [],
        disputed_proposition_ids: [],
        unresolved_critique_ids: [],
        what_would_change: null,
      },
    ],
    critiques: [
      {
        critique_id: "crt_open",
        critique_artifact_id: "art_critique_open",
        logical_id: "crt_logical",
        version: 1,
        target_artifact_id: "art_selected",
        critique_type: "CAUSAL_OVERCLAIM",
        severity: "HIGH",
        resolution: "OPEN",
        response_disposition: null,
        warrant_artifact_ids: ["art_opposing"],
        replacement_target_artifact_id: null,
        graph_node_id: "gnd_critique",
        provenance_href: "/api/v1/artifacts/art_critique_open/provenance",
        argument: "The causal claim exceeds the evidence.",
      },
      {
        critique_id: "crt_unresolved",
        critique_artifact_id: "art_critique_unresolved",
        logical_id: "crt_unresolved",
        version: 2,
        target_artifact_id: "art_selected",
        critique_type: "EVIDENCE_GAP",
        severity: "BLOCKING",
        resolution: "UNRESOLVED",
        response_disposition: "REQUEST_EVIDENCE",
        warrant_artifact_ids: [],
        replacement_target_artifact_id: null,
        graph_node_id: null,
        provenance_href: "/api/v1/artifacts/art_critique_unresolved/provenance",
        argument: null,
      },
      {
        critique_id: "crt_disputed",
        critique_artifact_id: "art_critique_disputed",
        logical_id: "crt_disputed",
        version: 1,
        target_artifact_id: "art_selected",
        critique_type: "CONSTRAINT_IGNORED",
        severity: "MEDIUM",
        resolution: "DISPUTED",
        response_disposition: "REJECT",
        warrant_artifact_ids: [],
        replacement_target_artifact_id: "art_replacement",
        graph_node_id: null,
        provenance_href: "/api/v1/artifacts/art_critique_disputed/provenance",
        argument: "Values remain in conflict.",
      },
    ],
  },
  meta: { request_id: "request", schema_version: 1, workspace_id: "ws_public" },
} as DissentResponse;

function renderPage(page = <DissentPage connection={connection} />) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {page}
    </QueryClientProvider>,
  );
}

describe("DissentPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-504, FR-505, FR-506, FR-609, FR-901, NFR-005, NFR-019
  it("renders selected context, every minority, evidence state, and distinct critiques", async () => {
    vi.spyOn(apiClient, "getSessionDissent").mockResolvedValue(response);
    renderPage();
    expect(
      await screen.findByRole("heading", { name: "Bus rapid transit" }),
    ).toBeVisible();
    expect(screen.getByText("agt_critic")).toBeVisible();
    expect(screen.getByText("agt_abstainer")).toBeVisible();
    expect(screen.getByText("Incidence study")).toBeVisible();
    expect(screen.getByText("Ridership forecast")).toBeVisible();
    expect(screen.getByText("Displacement study")).toBeVisible();
    expect(screen.getByText("Withdrawn survey")).toBeVisible();
    expect(screen.getByText("WITHDRAWN")).toBeVisible();
    expect(
      screen.getByText("No warrant was recorded for this minority position."),
    ).toBeVisible();
    expect(screen.getByText("No change condition was recorded.")).toBeVisible();
    expect(screen.getByText("OPEN critique")).toBeVisible();
    expect(screen.getByText("UNRESOLVED critique")).toBeVisible();
    expect(screen.getByText("DISPUTED critique")).toBeVisible();
    expect(screen.queryByText(/dissent score/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Incidence study/ }),
    ).toHaveAttribute("href", "/api/v1/artifacts/art_opposing/provenance");
    expect(
      screen.getByRole("link", { name: /Open in graph at gnd_opposing/ }),
    ).toHaveAttribute("href", "#/graph?root=gnd_opposing");
    expect(
      screen.getByRole("link", { name: /Open selected alternative in graph/ }),
    ).toHaveAttribute("href", "#/graph?root=gnd_selected");
  });

  // req: FR-505, FR-506
  it("moves minority selection with keyboard controls", async () => {
    vi.spyOn(apiClient, "getSessionDissent").mockResolvedValue(response);
    renderPage();
    await screen.findByText("agt_critic");
    const articles = Array.from(
      document.querySelectorAll<HTMLElement>("[data-kind='minority']"),
    );
    const first = articles[0]!;
    fireEvent.focus(first);
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(articles[1]).toHaveFocus();
    fireEvent.keyDown(articles[1]!, { key: "Home" });
    expect(first).toHaveFocus();
  });

  // req: FR-505, FR-506, NFR-019
  it("has no detectable WCAG A or AA violations", async () => {
    vi.spyOn(apiClient, "getSessionDissent").mockResolvedValue(response);
    const { container } = renderPage();
    await screen.findByText("agt_critic");
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  it.each([
    ["NO_CONSENSUS_RESULT", "No consensus result"],
    ["CONSENSUS_EXPLANATION_UNAVAILABLE", "Dissent unavailable"],
    ["EVALUATED_NO_DISSENT", "No dissent recorded"],
  ] as const)(
    "renders the explicit %s reason",
    async (emptyReason, expected) => {
      vi.spyOn(apiClient, "getSessionDissent").mockResolvedValue({
        ...response,
        data: {
          ...response.data,
          majority: null,
          evidence_context: {
            supports_selected: [],
            opposes_selected: [],
            qualifies_selected: [],
          },
          minority: [],
          critiques: [],
          empty_reason: emptyReason,
          evaluated: emptyReason === "EVALUATED_NO_DISSENT",
        },
      });
      renderPage();
      expect(
        await screen.findByRole("heading", { name: expected }),
      ).toBeVisible();
    },
  );

  // req: FR-505, NFR-005
  it("renders no-session, loading, and error states", async () => {
    const noSession = renderPage(<DissentPage />);
    expect(screen.getByText("A restored session is required")).toBeVisible();
    noSession.unmount();
    vi.spyOn(apiClient, "getSessionDissent").mockImplementation(
      () => new Promise(() => undefined),
    );
    const loading = renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Reading minority positions",
    );
    loading.unmount();
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "getSessionDissent").mockRejectedValue(
      new Error("network offline"),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "network offline",
    );
  });

  it.each([390, 1280])("renders at a %ipx viewport", async (width) => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: width,
    });
    vi.spyOn(apiClient, "getSessionDissent").mockResolvedValue(response);
    const { container } = renderPage();
    await screen.findByText("agt_critic");
    expect(container.querySelector(".dissent-page")).toBeVisible();
  });

  // req: FR-505, FR-506
  it("preserves server order without classifying minority in the browser", async () => {
    vi.spyOn(apiClient, "getSessionDissent").mockResolvedValue({
      ...response,
      data: {
        ...response.data,
        minority: [...response.data.minority].reverse(),
      },
    });
    renderPage();
    const entries = await screen.findAllByText(/agt_(abstainer|critic)/);
    expect(entries.map((entry) => entry.textContent)).toEqual([
      "agt_abstainer",
      "agt_critic",
    ]);
  });
});
