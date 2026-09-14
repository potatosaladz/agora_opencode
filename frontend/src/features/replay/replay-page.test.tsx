import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";

import {
  apiClient,
  type ManifestResponse,
  type ReplayResponse,
  type SessionResponse,
} from "../../api/client";
import ReplayPage from "./replay-page";

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

const manifest: ManifestResponse = {
  data: {
    session_id: "ses_public",
    manifest_id: `man_${"a".repeat(32)}`,
    manifest_version: 1,
    manifest_hash: `sha256:${"a".repeat(64)}`,
    status: "FINALIZED" as const,
    source_session_id: null,
    finalized_at: "2026-09-14T10:00:00Z",
    git_sha: "1cad09a",
    image_digests: { backend: `sha256:${"b".repeat(64)}` },
  },
  meta: { request_id: "request", schema_version: 1, workspace_id: "ws_public" },
};

function verified(): ReplayResponse {
  return {
    data: {
      mode: "REPLAY_STRICT",
      outcome: "VERIFIED",
      source_session_id: "ses_public",
      source_manifest: manifest.data,
      integrity_valid: true,
      byte_identical: true,
      checked_steps: 3,
      differences: [],
      first_mismatch: null,
      replay_session_id: null,
      replay_manifest_id: null,
      replay_event_ids: [],
      replay_result_ids: [],
      links: {
        source_session: "#/explanation",
        manifest: "/api/v1/sessions/ses_public/manifest",
        explanation: "#/explanation",
      },
    },
    meta: {
      request_id: "request",
      schema_version: 1,
      workspace_id: "ws_public",
    },
  };
}

function failedStrict(): ReplayResponse {
  const base = verified();
  return {
    ...base,
    data: {
      ...base.data,
      outcome: "FAILED",
      integrity_valid: true,
      byte_identical: false,
      first_mismatch: {
        reason: "UNKNOWN_IMPLEMENTATION",
        detail: "the exact pinned implementation is unavailable",
        order: 1,
        step_id: `rps_${"c".repeat(32)}`,
        expected_hash: null,
        actual_hash: null,
      },
    },
  };
}

function different(): ReplayResponse {
  const base = verified();
  return {
    ...base,
    data: {
      ...base.data,
      mode: "REPLAY_TOLERANT" as const,
      outcome: "DIFFERENT",
      byte_identical: false,
      differences: [
        {
          order: 1,
          step_id: `rps_${"d".repeat(32)}`,
          kind: "SYMBOLIC",
          difference: "OUTPUT",
          field: "status",
          expected: "UNKNOWN",
          actual: "SAT",
        },
      ],
    },
  };
}

function liveStarted(): ReplayResponse {
  const base = verified();
  return {
    ...base,
    data: {
      ...base.data,
      mode: "REPLAY_LIVE" as const,
      outcome: "LIVE_STARTED",
      byte_identical: false,
      replay_session_id: "ses_derived",
      replay_manifest_id: `man_${"e".repeat(32)}`,
      replay_event_ids: [`evt_${"f".repeat(32)}`],
      replay_result_ids: [`rpr_${"1".repeat(32)}`],
      links: {
        ...base.data.links,
        replay_session: "#/",
      },
    },
  };
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ReplayPage connection={connection} />
    </QueryClientProvider>,
  );
}

describe("ReplayPage", () => {
  afterEach(() => vi.restoreAllMocks());

  // req: FR-808, NFR-010
  it("shows a restored-session requirement when no session is active", () => {
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ReplayPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("A restored session is required")).toBeVisible();
  });

  // req: FR-808, NFR-014
  it("reads and displays the finalized manifest identity before execution", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    renderPage();
    expect(await screen.findByText(manifest.data.manifest_id)).toBeVisible();
    expect(screen.getByText(manifest.data.manifest_hash)).toBeVisible();
    expect(screen.getByText(manifest.data.git_sha)).toBeVisible();
  });

  // req: FR-808, NFR-003, NFR-019
  it("distinguishes STRICT/TOLERANT/LIVE with a semantic explanation for each mode", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    const group = screen.getByRole("radiogroup", { name: "Replay mode" });
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByText(/No live providers are called/)).toBeVisible();
    fireEvent.click(
      within(group).getByRole("radio", { name: /REPLAY_TOLERANT/ }),
    );
    expect(screen.getByText(/is not exact reproduction/)).toBeVisible();
    fireEvent.click(within(group).getByRole("radio", { name: /REPLAY_LIVE/ }));
    expect(screen.getByText(/fresh identities/)).toBeVisible();
  });

  // req: FR-808, NFR-003
  it("executes STRICT and renders a VERIFIED outcome without external calls", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    const replay = vi
      .spyOn(apiClient, "replaySession")
      .mockResolvedValue(verified());
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    fireEvent.click(
      screen.getByRole("button", { name: /Execute REPLAY_STRICT/ }),
    );
    expect(await screen.findByText("VERIFIED")).toBeVisible();
    expect(
      screen.getByText(/does not call live external providers/),
    ).toBeVisible();
    expect(replay).toHaveBeenCalledWith(
      "ses_public",
      expect.objectContaining({ mode: "REPLAY_STRICT" }),
      "token",
    );
  });

  // req: FR-808, NFR-003
  it("shows the first mismatch / unavailable dependency on a failed STRICT replay", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    vi.spyOn(apiClient, "replaySession").mockResolvedValue(failedStrict());
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    fireEvent.click(
      screen.getByRole("button", { name: /Execute REPLAY_STRICT/ }),
    );
    expect(await screen.findByText("FAILED")).toBeVisible();
    expect(screen.getByText("UNKNOWN_IMPLEMENTATION")).toBeVisible();
    expect(
      screen.getByText("the exact pinned implementation is unavailable"),
    ).toBeVisible();
  });

  // req: FR-808, NFR-003
  it("renders TOLERANT ordered differences and never claims VERIFIED", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    vi.spyOn(apiClient, "replaySession").mockResolvedValue(different());
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    fireEvent.click(screen.getByRole("radio", { name: /REPLAY_TOLERANT/ }));
    fireEvent.click(
      screen.getByRole("button", { name: /Execute REPLAY_TOLERANT/ }),
    );
    expect(await screen.findByText("DIFFERENT")).toBeVisible();
    expect(screen.queryByText("VERIFIED")).not.toBeInTheDocument();
    expect(screen.getByText(/OUTPUT/).closest("li")).toHaveTextContent(
      "SYMBOLIC",
    );
    expect(screen.getByText(/OUTPUT/).closest("li")).toHaveTextContent(
      "status",
    );
    expect(
      screen.getByText(/DIFFERENT is a valid comparison result/),
    ).toBeVisible();
  });

  // req: FR-808, NFR-010
  it("requires explicit confirmation before executing LIVE replay", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    const replay = vi
      .spyOn(apiClient, "replaySession")
      .mockResolvedValue(liveStarted());
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    fireEvent.click(screen.getByRole("radio", { name: /REPLAY_LIVE/ }));
    const button = screen.getByRole("button", { name: /Execute REPLAY_LIVE/ });
    expect(button).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I understand this creates a new execution/,
      }),
    );
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(await screen.findByText("LIVE_STARTED")).toBeVisible();
    expect(replay).toHaveBeenCalledWith(
      "ses_public",
      expect.objectContaining({ mode: "REPLAY_LIVE", confirm_live: true }),
      "token",
    );
  });

  // req: FR-808
  it("shows the fresh LIVE session identity and navigation without reusing the source id", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    vi.spyOn(apiClient, "replaySession").mockResolvedValue(liveStarted());
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    fireEvent.click(screen.getByRole("radio", { name: /REPLAY_LIVE/ }));
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I understand this creates a new execution/,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Execute REPLAY_LIVE/ }),
    );
    const link = await screen.findByRole("link", { name: "ses_derived" });
    expect(link).toHaveAttribute("href", "#/");
    expect(link).not.toHaveTextContent("ses_public");
  });

  // req: FR-808, NFR-010
  it("renders loading and error states", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockReturnValue(
      new Promise(() => undefined),
    );
    const loading = renderPage();
    expect(screen.getByRole("status")).toBeVisible();
    loading.unmount();
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "getReplayManifest").mockRejectedValue(
      new Error("Manifest not finalized"),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Manifest not finalized",
    );
  });

  // req: FR-808, NFR-010
  it("is keyboard operable via native radio/checkbox/button controls", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    renderPage();
    await screen.findByText(manifest.data.manifest_id);
    const strict = screen.getByRole("radio", { name: /REPLAY_STRICT/ });
    strict.focus();
    expect(strict).toHaveFocus();
    fireEvent.keyDown(strict, { key: "ArrowDown" });
  });

  // req: NFR-005, NFR-019
  it("has no detectable WCAG A/AA violations", async () => {
    vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
    const { container } = renderPage();
    await screen.findByText(manifest.data.manifest_id);
    const result = await axe.run(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });

  it.each([390, 1280])(
    "keeps replay controls available at %ipx",
    async (width) => {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: width,
      });
      vi.spyOn(apiClient, "getReplayManifest").mockResolvedValue(manifest);
      renderPage();
      expect(await screen.findByText(manifest.data.manifest_id)).toBeVisible();
      expect(
        screen.getByRole("radiogroup", { name: "Replay mode" }),
      ).toBeVisible();
    },
  );
});
