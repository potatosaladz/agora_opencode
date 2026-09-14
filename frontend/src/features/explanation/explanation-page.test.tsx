import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";

import { apiClient, type SessionResponse } from "../../api/client";
import { explanationFixture } from "./explanation.fixture";
import ExplanationPage from "./explanation-page";

const connection = {
  session: {
    data: {
      id: "ses_public",
      status: "COMPLETED",
      problem_statement: "Choose a transit plan",
      agent_definition_ids: [],
      objective_ids: [],
      constraint_ids: [],
      budget: { max_rounds: 3, max_tokens: 100, max_usd: "2" },
      round: 3,
      workflow_id: "wf",
      run_id: "run",
      initialized_at: null,
      started_at: null,
      ended_at: null,
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

function renderPage(page = <ExplanationPage connection={connection} />) {
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

describe("ExplanationPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-504, FR-505, FR-605, FR-609, FR-804, FR-805, FR-901, NFR-005, NFR-019
  it("renders all required sections in the server sequence with explicit empty reasons", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderPage();
    expect(
      (await screen.findAllByText("Adopt the staged electric bus rollout"))[0],
    ).toBeVisible();
    const body = document.querySelector<HTMLElement>(".explanation-body")!;
    expect(
      within(body)
        .getAllByRole("heading", { level: 2 })
        .map((heading) => heading.textContent),
    ).toEqual([
      "Decision / recommendation",
      "Why selected",
      "Alternatives",
      "Supporting evidence",
      "Opposing evidence",
      "Qualifying evidence",
      "Assumptions / constraints",
      "Minority / dissent",
      "Critiques / unresolved objections",
      "Risks / uncertainties",
      "Symbolic feasibility",
      "Conditions",
      "Counterfactuals",
      "Provenance / traceability",
      "Weakest evidence",
    ]);
    expect(
      screen.getByText("No qualifying evidence was recorded."),
    ).toBeVisible();
    expect(
      screen.getByText("Withdrawn support:", { exact: false }),
    ).toBeVisible();
    expect(
      screen.getAllByText("Incomplete provenance:", { exact: false }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("UNKNOWN")).toBeVisible();
    expect(
      screen.getByText(/not determined; symbolic assurance unavailable/),
    ).toBeVisible();
    expect(screen.getByText("DEFER")).toBeVisible();
  });

  // req: FR-504, FR-505, FR-605, FR-805, NFR-005
  it("makes why selected and the material counterargument identifiable", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderPage();
    expect(
      await screen.findByText(/reversible deployment sequence was selected/i),
    ).toBeVisible();
    expect(screen.getAllByText("UNRESOLVED_CRITIQUE")[0]).toBeVisible();
    expect(
      screen.getByText("Independent winter fleet validation is missing"),
    ).toBeVisible();
    expect(
      screen.getAllByText("Winter range degradation report")[0],
    ).toBeVisible();
    expect(
      screen.getByText("Cold-weather fleet requirement is understated"),
    ).toBeVisible();
    expect(screen.getAllByText("Prefer the rail alternative")[0]).toBeVisible();
    const weakest = screen
      .getByRole("heading", { level: 2, name: "Weakest evidence" })
      .closest("section")!;
    expect(
      within(weakest).getAllByText(/verification=DISPUTED/)[0],
    ).toBeVisible();
    expect(within(weakest).getByText("Open in graph")).toHaveAttribute(
      "href",
      "#/graph?root=gnd_winter",
    );
    expect(within(weakest).getByText("Open provenance")).toHaveAttribute(
      "href",
      "/api/v1/artifacts/art_winter/provenance",
    );
  });

  // req: FR-609, FR-901, NFR-019
  it("shows persisted numeric kind, unit, version, and caveat without prohibited labels", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderPage();
    await screen.findAllByText("Fleet procurement estimate");
    const values = document.querySelector<HTMLElement>(
      '[aria-label="Persisted numeric value: capital estimate"]',
    )!;
    expect(values).toHaveTextContent("18.4");
    expect(values).toHaveTextContent("USD million");
    expect(values).toHaveTextContent("fixture-v1");
    expect(values).toHaveTextContent("Persisted value");
    expect(document.querySelector(".explanation-body")).not.toHaveTextContent(
      /confidence|trust level|composite score/i,
    );
  });

  // req: FR-804, FR-805, NFR-005
  it("supports Arrow, Home, and End section navigation", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderPage();
    const nav = await screen.findByRole("navigation", {
      name: "Explanation sections",
    });
    const links = within(nav).getAllByRole("link");
    links[0]!.focus();
    fireEvent.keyDown(links[0]!, { key: "ArrowRight" });
    expect(links[1]).toHaveFocus();
    fireEvent.keyDown(links[1]!, { key: "End" });
    expect(links.at(-1)).toHaveFocus();
    fireEvent.keyDown(links.at(-1)!, { key: "Home" });
    expect(links[0]).toHaveFocus();
  });

  // req: FR-804, NFR-005
  it("offers executive, expert, formal, and machine-readable views over one response", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    renderPage();
    const modes = await screen.findByRole("navigation", {
      name: "Explanation view",
    });
    expect(within(modes).getAllByRole("button")).toHaveLength(4);
    fireEvent.click(within(modes).getByRole("button", { name: "Executive" }));
    expect(
      screen.getByRole("heading", { name: "Weakest evidence" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Alternatives" }),
    ).not.toBeInTheDocument();
    fireEvent.click(within(modes).getByRole("button", { name: "Formal" }));
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Symbolic feasibility",
      }),
    ).toBeVisible();
    fireEvent.click(
      within(modes).getByRole("button", { name: "Machine-readable" }),
    );
    expect(
      screen.getByRole("heading", { name: "Machine-readable explanation" }),
    ).toBeVisible();
    expect(screen.getByText(/"status": "AVAILABLE"/)).toBeVisible();
  });

  // req: FR-605, FR-804, NFR-005
  it("renders no-session, loading, error, no-consensus, and unavailable states", async () => {
    const noSession = renderPage(<ExplanationPage />);
    expect(screen.getByText("A restored session is required")).toBeVisible();
    noSession.unmount();
    vi.spyOn(apiClient, "getSessionExplanation").mockReturnValue(
      new Promise(() => undefined),
    );
    const loading = renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Reading the authoritative explanation",
    );
    loading.unmount();
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "getSessionExplanation").mockRejectedValue(
      new Error("Network offline"),
    );
    const failed = renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Network offline",
    );
    failed.unmount();
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue({
      ...explanationFixture,
      data: {
        ...explanationFixture.data,
        status: "NO_CONSENSUS_RESULT",
        empty_reason: "NO_CONSENSUS_RESULT",
      },
    });
    const noConsensus = renderPage();
    expect(await screen.findByText("No consensus result")).toBeVisible();
    noConsensus.unmount();
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue({
      ...explanationFixture,
      data: {
        ...explanationFixture.data,
        status: "EXPLANATION_UNAVAILABLE",
        empty_reason: "EXPLANATION_UNAVAILABLE",
      },
    });
    renderPage();
    expect(
      await screen.findByRole("heading", { name: "Explanation unavailable" }),
    ).toBeVisible();
  });

  // req: FR-504, FR-505, FR-804, NFR-005, NFR-019
  it("has no detectable WCAG A/AA violations", async () => {
    vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
      explanationFixture,
    );
    const { container } = renderPage();
    await screen.findAllByText("Adopt the staged electric bus rollout");
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  it.each([390, 1280])(
    "keeps the explanation available at %ipx",
    async (width) => {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: width,
      });
      vi.spyOn(apiClient, "getSessionExplanation").mockResolvedValue(
        explanationFixture,
      );
      renderPage();
      expect(
        (
          await screen.findAllByText("Adopt the staged electric bus rollout")
        )[0],
      ).toBeVisible();
      expect(
        screen.getByRole("navigation", { name: "Explanation sections" }),
      ).toBeVisible();
    },
  );
});
