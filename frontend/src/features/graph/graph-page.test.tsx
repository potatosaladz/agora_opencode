import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";

import {
  apiClient,
  type GraphSubgraphResponse,
  type SessionResponse,
} from "../../api/client";
import GraphPage from "./graph-page";

const SESSION = {
  data: {
    id: `ses_${"1".repeat(32)}`,
    status: "COMPLETED",
    problem_statement: "Inspect this reasoning graph",
    agent_definition_ids: [],
    objective_ids: [],
    constraint_ids: [],
    budget: { max_rounds: 2, max_tokens: 10, max_usd: "1" },
    round: 2,
    workflow_id: null,
    run_id: null,
    initialized_at: null,
    started_at: null,
    ended_at: null,
  },
  meta: {
    request_id: "request",
    schema_version: 1,
    version: 1,
    workspace_id: `ws_${"2".repeat(32)}`,
    created_at: "2026-09-14T00:00:00Z",
    updated_at: "2026-09-14T00:00:00Z",
    owner: { id: `usr_${"3".repeat(32)}`, class: "HUMAN" },
    permissions: ["read"],
    trace: null,
  },
} as SessionResponse;

const ROOT = `gnd_${"4".repeat(32)}`;
const OTHER = `gnd_${"5".repeat(32)}`;

function response(
  overrides: Partial<GraphSubgraphResponse["data"]> = {},
): GraphSubgraphResponse {
  return {
    data: {
      nodes: [
        {
          id: ROOT,
          workspace_id: SESSION.meta.workspace_id,
          session_id: SESSION.data.id,
          kind: "CLAIM",
          ref_id: `art_${"6".repeat(32)}`,
          label: "Primary claim",
          attrs: {},
        },
        {
          id: OTHER,
          workspace_id: SESSION.meta.workspace_id,
          session_id: SESSION.data.id,
          kind: "EVIDENCE",
          ref_id: `art_${"7".repeat(32)}`,
          label: "Source evidence",
          attrs: {},
        },
      ],
      edges: [
        {
          id: `ged_${"8".repeat(32)}`,
          workspace_id: SESSION.meta.workspace_id,
          session_id: SESSION.data.id,
          from_node: OTHER,
          to_node: ROOT,
          edge_type: "SUPPORTS",
          weight: null,
          qualifier: {},
          actor_class: "HUMAN",
          actor_id: `usr_${"9".repeat(32)}`,
        },
      ],
      truncated: false,
      next_cursor: null,
      ...overrides,
    },
    meta: { request_id: "request", workspace_id: SESSION.meta.workspace_id },
  };
}

function renderGraph() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphPage connection={{ session: SESSION, token: "token" }} />
    </QueryClientProvider>,
  );
}

function submitRoot() {
  fireEvent.change(screen.getByLabelText("Public graph root IDs"), {
    target: { value: ROOT },
  });
  fireEvent.click(screen.getByRole("button", { name: "Query graph" }));
}

describe("GraphPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-805, NFR-004, NFR-019
  it("renders authoritative nodes, labelled edges, truncation, and textual equivalent", async () => {
    vi.spyOn(apiClient, "getGraphSubgraph").mockResolvedValue(
      response({ truncated: true, next_cursor: "next" }),
    );
    renderGraph();
    submitRoot();

    expect((await screen.findAllByText("Primary claim"))[0]).toBeVisible();
    expect(screen.getAllByText("SUPPORTS").length).toBeGreaterThan(0);
    expect(screen.getByText("Depth truncated.")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Nodes and relationships" }),
    ).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: "EVIDENCE: Source evidence" }),
    );
    expect(screen.getByText("Selected node").parentElement).toHaveTextContent(
      "Source evidence",
    );
  });

  // req: FR-805, NFR-010
  it("supports keyboard node navigation and has no detectable WCAG A/AA violations", async () => {
    vi.spyOn(apiClient, "getGraphSubgraph").mockResolvedValue(response());
    const { container } = renderGraph();
    submitRoot();
    const rootNode = await screen.findByRole("button", {
      name: "CLAIM: Primary claim",
    });
    rootNode.focus();
    fireEvent.keyDown(rootNode, { key: "ArrowRight" });
    expect(
      screen.getByRole("button", { name: "EVIDENCE: Source evidence" }),
    ).toHaveFocus();
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  // req: FR-805, NFR-004, NFR-019
  it("renders loading, error, empty, and cursor continuation states", async () => {
    let resolveFirst!: (value: GraphSubgraphResponse) => void;
    const first = new Promise<GraphSubgraphResponse>((resolve) => {
      resolveFirst = resolve;
    });
    const query = vi
      .spyOn(apiClient, "getGraphSubgraph")
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(response({ next_cursor: null }));
    renderGraph();
    submitRoot();
    expect(
      screen.getByText("Reading authoritative nodes and edges…"),
    ).toBeVisible();
    resolveFirst(response({ next_cursor: "next" }));
    const loadMore = await screen.findByRole("button", { name: "Load more" });
    fireEvent.click(loadMore);
    await waitFor(() => expect(query).toHaveBeenCalledTimes(2));

    query.mockRejectedValueOnce(new Error("network unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Query graph" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "network unavailable",
    );

    query.mockResolvedValueOnce(response({ nodes: [], edges: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Query graph" }));
    expect(await screen.findByText("No graph members returned")).toBeVisible();
  });

  // req: FR-805, NFR-010
  it("renders a useful empty session state", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <GraphPage />
      </QueryClientProvider>,
    );
    expect(
      screen.getByRole("heading", { name: "A live session is required" }),
    ).toBeVisible();
  });

  it.each([390, 1280])("keeps graph controls available at %ipx", (width) => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: width,
    });
    renderGraph();
    expect(screen.getByLabelText("Public graph root IDs")).toBeVisible();
    expect(screen.getByRole("button", { name: "Query graph" })).toBeVisible();
  });
});
