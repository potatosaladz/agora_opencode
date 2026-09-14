import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  apiClient,
  type AssumptionRegisterItem,
  type AssumptionRegisterResponse,
  type SessionResponse,
} from "../../api/client";
import AssumptionRegisterPage from "./assumption-register-page";

const connection = {
  session: {
    data: {
      id: "ses_public",
      status: "COMPLETED",
      problem_statement: "Choose a resilient transit plan",
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

const common = {
  logical_id: "logical",
  category: "Demand",
  constraint_type: null,
  formal_status: null,
  uncertainty_type: null,
  drivers: null,
  representation: null,
  context_artifact_id: "art_context",
  owner: { actor_id: "agt_planner", actor_class: "AGENT" as const },
  round: 2,
  lifecycle: "ACTIVE" as const,
  supersedes_id: null,
  basis: "Observed weekday counts",
  materiality: "HIGH",
  challengeable: true,
  evidence: [],
  critiques: [],
  dependents: [],
  symbolic: null,
  graph_node_id: "gnd_default",
  provenance_href: "/provenance/default",
};

const items: AssumptionRegisterItem[] = [
  {
    ...common,
    id: "art_assumption",
    version: 1,
    kind: "ASSUMPTION",
    statement: "Ridership remains above the planning floor.",
    evidence: [
      {
        id: "ev_support",
        kind: "EVIDENCE",
        relationship: "SUPPORTS",
        label: "Count study",
        graph_node_id: "gnd_support",
        provenance_href: "/provenance/support",
      },
      {
        id: "ev_oppose",
        kind: "EVIDENCE",
        relationship: "OPPOSES",
        label: "Remote work survey",
        graph_node_id: null,
        provenance_href: "/provenance/oppose",
      },
      {
        id: "ev_qualify",
        kind: "EVIDENCE",
        relationship: "QUALIFIES",
        label: "Seasonality note",
        graph_node_id: null,
        provenance_href: "/provenance/qualify",
      },
    ],
    dependents: [
      {
        id: "claim_public",
        kind: "CLAIM",
        relationship: "BASED_ON_ASSUMPTION",
        label: "Revenue claim",
        graph_node_id: "gnd_claim",
        provenance_href: "/provenance/claim",
      },
      {
        id: "rec_public",
        kind: "RECOMMENDATION",
        relationship: "RECOMMENDS",
        label: "Approve corridor",
        graph_node_id: null,
        provenance_href: null,
      },
      {
        id: "art_public",
        kind: "ALTERNATIVE",
        relationship: "BASED_ON_ASSUMPTION",
        label: "Cost model",
        graph_node_id: null,
        provenance_href: "/provenance/artifact",
      },
    ],
  },
  {
    ...common,
    id: "art_disputed",
    logical_id: "logical_disputed",
    version: 3,
    kind: "ASSUMPTION",
    statement: "Construction inflation remains bounded.",
    critiques: [
      {
        id: "crt_public",
        artifact_id: "art_critique",
        logical_id: "crt_logical",
        version: 1,
        critique_type: "EVIDENCE_GAP",
        severity: "HIGH",
        resolution: "DISPUTED",
        response_disposition: null,
        graph_node_id: null,
        provenance_href: "/provenance/critique",
      },
    ],
    graph_node_id: "gnd_disputed",
  },
  {
    ...common,
    id: "art_constraint",
    version: 1,
    kind: "CONSTRAINT",
    statement: "Capital spending must not exceed the statutory ceiling.",
    category: "Budget",
    constraint_type: "NON_NEGOTIABLE",
    challengeable: null,
    basis: null,
    materiality: null,
    lifecycle: "SUPERSEDED",
    symbolic: {
      analysis_status: "AVAILABLE",
      formalization: null,
      evaluation_id: "sev_public",
      status: "UNKNOWN",
      reason: "Solver timed out.",
      policy_action: "DEFER",
    },
  },
  {
    ...common,
    id: "art_uncertainty",
    version: 2,
    kind: "UNCERTAINTY",
    statement: "Supplier lead time is not yet measured.",
    lifecycle: "WITHDRAWN",
    basis: null,
    materiality: null,
    challengeable: null,
    uncertainty_type: "EPISTEMIC",
    context_artifact_id: null,
    graph_node_id: null,
  },
];

const response = {
  data: { session_id: "ses_public", items },
  meta: { request_id: "request", schema_version: 1, workspace_id: "ws_public" },
} satisfies AssumptionRegisterResponse;

function renderPage(page = <AssumptionRegisterPage connection={connection} />) {
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

describe("AssumptionRegisterPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-311, FR-504, FR-705, FR-708, FR-805, NFR-005, NFR-010, NFR-019
  it("renders server order, distinctions, evidence, dependents, and exact unknown policy", async () => {
    vi.spyOn(apiClient, "getSessionAssumptions").mockResolvedValue(response);
    renderPage();

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "Declared reasoning conditions",
      items[0]!.statement,
      items[1]!.statement,
      items[2]!.statement,
      items[3]!.statement,
    ]);
    expect(document.querySelectorAll(".assumption-type")).toHaveLength(4);
    expect(screen.getAllByText("ASSUMPTION")[0]).toBeVisible();
    expect(screen.getAllByText("CONSTRAINT")[0]).toBeVisible();
    expect(screen.getByText("NON_NEGOTIABLE")).toBeVisible();
    expect(screen.getByText("UNCERTAINTY")).toBeVisible();
    expect(screen.getByText("Count study")).toHaveAttribute(
      "href",
      "/provenance/support",
    );
    expect(screen.getByText("Remote work survey")).toBeVisible();
    expect(screen.getByText("Seasonality note")).toBeVisible();
    expect(screen.getByText("Revenue claim")).toBeVisible();
    expect(screen.getByText("Approve corridor")).toBeVisible();
    expect(screen.getByText("Cost model")).toBeVisible();
    expect(screen.getByText("crt_public")).toHaveAttribute(
      "href",
      "#/dissent#dissent-crt_public",
    );
    expect(screen.getAllByText("Open in graph")[0]).toHaveAttribute(
      "href",
      "#/graph?root=gnd_default",
    );
    expect(screen.getAllByText("not determined")[0]).toBeVisible();
    expect(
      screen.getAllByText("symbolic assurance unavailable")[0],
    ).toBeVisible();
    expect(screen.getAllByText("DEFER")).toHaveLength(1);
    expect(screen.getAllByText("NOT APPLICABLE")).toHaveLength(3);
    expect(screen.getAllByText("Analysis unavailable")[0]).toBeVisible();
    expect(screen.getAllByText("Basis unavailable")[0]).toBeVisible();
    expect(screen.queryByText(/generic factor/i)).not.toBeInTheDocument();
  });

  // req: FR-311, FR-805, NFR-010
  it("supports arrow, Home, and End register navigation", async () => {
    vi.spyOn(apiClient, "getSessionAssumptions").mockResolvedValue(response);
    renderPage();
    const first = (await screen.findByText(items[0]!.statement!)).closest(
      "article",
    )!;
    const second = screen.getByText(items[1]!.statement!).closest("article")!;
    const last = screen.getByText(items[3]!.statement!).closest("article")!;
    fireEvent.focus(first);
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(second).toHaveFocus();
    fireEvent.keyDown(second, { key: "End" });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: "Home" });
    expect(first).toHaveFocus();
  });

  // req: FR-311, FR-504, FR-708, NFR-005, NFR-019
  it("has no detectable WCAG A/AA violations", async () => {
    vi.spyOn(apiClient, "getSessionAssumptions").mockResolvedValue(response);
    const { container } = renderPage();
    await screen.findByText(items[0]!.statement!);
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  // req: FR-311, FR-705, FR-708, NFR-005
  it("renders no-session, loading, empty, unavailable, and error states", async () => {
    const noSession = renderPage(<AssumptionRegisterPage />);
    expect(screen.getByText("A restored session is required")).toBeVisible();
    noSession.unmount();

    vi.spyOn(apiClient, "getSessionAssumptions").mockReturnValue(
      new Promise(() => undefined),
    );
    const loading = renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Reading the authoritative",
    );
    loading.unmount();
    vi.restoreAllMocks();

    vi.spyOn(apiClient, "getSessionAssumptions").mockResolvedValue({
      ...response,
      data: { ...response.data, items: [] },
    });
    const empty = renderPage();
    await screen.findByText("No register entries");
    empty.unmount();
    vi.restoreAllMocks();

    vi.spyOn(apiClient, "getSessionAssumptions").mockResolvedValue({
      ...response,
      data: {
        ...response.data,
        items: [
          {
            ...items[2]!,
            symbolic: {
              analysis_status: "MISSING_EVALUATION",
              formalization: null,
              evaluation_id: null,
              status: null,
              reason: "Projection pending",
              policy_action: "DEFER",
            },
          },
        ],
      },
    });
    const unavailable = renderPage();
    expect(
      (await screen.findAllByText("Projection pending")).length,
    ).toBeGreaterThan(0);
    unavailable.unmount();
    vi.restoreAllMocks();

    vi.spyOn(apiClient, "getSessionAssumptions").mockRejectedValue(
      new Error("Network offline"),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Network offline",
    );
  });

  it.each([390, 1280])(
    "keeps the authoritative register available at %ipx",
    async (width) => {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: width,
      });
      vi.spyOn(apiClient, "getSessionAssumptions").mockResolvedValue(response);
      renderPage();
      expect(await screen.findByText(items[0]!.statement!)).toBeVisible();
      expect(
        screen.getByRole("heading", { name: "Declared reasoning conditions" }),
      ).toBeVisible();
    },
  );
});
