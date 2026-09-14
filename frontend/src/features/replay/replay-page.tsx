import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiProblem,
  apiClient,
  type ReplayMode,
  type ReplayRequest,
  type ReplayResponse,
  type SessionResponse,
} from "../../api/client";

type ReplayConnection = { session: SessionResponse; token: string };
const modes: ReplayMode[] = ["REPLAY_STRICT", "REPLAY_TOLERANT", "REPLAY_LIVE"];

function words(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

function messageFor(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "The replay control request failed.";
}

function modeSummary(mode: ReplayMode): string {
  if (mode === "REPLAY_STRICT")
    return "Verify historical reproducibility with the finalized pins. No live providers are called.";
  if (mode === "REPLAY_TOLERANT")
    return "Comparatively re-execute permitted dependencies and inspect ordered differences. This is not exact reproduction.";
  return "Create a new derived execution with fresh identities and explicit source-session lineage.";
}

function Result({ result }: { result: ReplayResponse }) {
  const data = result.data;
  return (
    <section className="replay-result" aria-labelledby="replay-result-title">
      <header>
        <p>Authoritative replay result</p>
        <h2 id="replay-result-title">{words(data.outcome)}</h2>
        <span
          className={`replay-outcome replay-outcome--${data.outcome.toLowerCase()}`}
        >
          {data.outcome}
        </span>
      </header>
      <dl className="replay-facts">
        <div>
          <dt>Mode</dt>
          <dd>{data.mode}</dd>
        </div>
        <div>
          <dt>Source session</dt>
          <dd>
            <a href={data.links.source_session}>{data.source_session_id}</a>
          </dd>
        </div>
        <div>
          <dt>Manifest</dt>
          <dd>
            <a href={data.links.manifest}>{data.source_manifest.manifest_id}</a>{" "}
            v{data.source_manifest.manifest_version}
          </dd>
        </div>
        <div>
          <dt>Manifest hash</dt>
          <dd>
            <code>{data.source_manifest.manifest_hash}</code>
          </dd>
        </div>
        <div>
          <dt>Ledger integrity</dt>
          <dd>{data.integrity_valid ? "VALID" : "INVALID"}</dd>
        </div>
        <div>
          <dt>Byte identical</dt>
          <dd>{data.byte_identical ? "YES" : "NO"}</dd>
        </div>
      </dl>
      {data.mode === "REPLAY_STRICT" ? (
        <p className="replay-note">
          STRICT is deterministic historical verification and does not call live
          external providers.
        </p>
      ) : null}
      {data.mode === "REPLAY_TOLERANT" ? (
        <p className="replay-note">
          TOLERANT is comparative. DIFFERENT is a valid comparison result, not a
          verification failure.
        </p>
      ) : null}
      {data.first_mismatch ? (
        <section
          className="replay-mismatch"
          aria-labelledby="replay-mismatch-title"
        >
          <h3 id="replay-mismatch-title">
            First mismatch / unavailable dependency
          </h3>
          <dl className="replay-facts">
            <div>
              <dt>Reason</dt>
              <dd>{data.first_mismatch.reason}</dd>
            </div>
            <div>
              <dt>Detail</dt>
              <dd>{data.first_mismatch.detail}</dd>
            </div>
            <div>
              <dt>Step</dt>
              <dd>{data.first_mismatch.step_id ?? "Unavailable"}</dd>
            </div>
            <div>
              <dt>Order</dt>
              <dd>{data.first_mismatch.order ?? "Unavailable"}</dd>
            </div>
          </dl>
        </section>
      ) : null}
      {data.differences.length ? (
        <section
          className="replay-differences"
          aria-labelledby="replay-differences-title"
        >
          <h3 id="replay-differences-title">Ordered tolerant differences</h3>
          <ol>
            {data.differences.map((difference) => (
              <li
                key={`${difference.order}-${difference.step_id}-${difference.field}`}
              >
                <strong>{difference.difference}</strong> / {difference.kind} /{" "}
                {difference.field}: {difference.expected ?? "Unavailable"} →{" "}
                {difference.actual ?? "Unavailable"}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {data.replay_session_id ? (
        <section
          className="replay-live-result"
          aria-labelledby="replay-live-title"
        >
          <h3 id="replay-live-title">Fresh LIVE execution</h3>
          <p>
            Original historical session remains unchanged. Source lineage is
            explicit.
          </p>
          <p>
            New session:{" "}
            <a href={data.links.replay_session}>{data.replay_session_id}</a>
          </p>
          <p>
            Restore the new session to inspect its live explanation and results.
          </p>
          <p>New manifest: {data.replay_manifest_id ?? "Unavailable"}</p>
        </section>
      ) : null}
    </section>
  );
}

export default function ReplayPage({
  connection,
}: {
  connection?: ReplayConnection;
}) {
  const [mode, setMode] = useState<ReplayMode>("REPLAY_STRICT");
  const [confirmLive, setConfirmLive] = useState(false);
  const [result, setResult] = useState<ReplayResponse>();
  const [error, setError] = useState<string>();
  const [running, setRunning] = useState(false);
  const manifestQuery = useQuery({
    enabled: connection !== undefined,
    queryKey: ["session-replay-manifest", connection?.session.data.id],
    queryFn: ({ signal }) =>
      apiClient.getReplayManifest(
        connection!.session.data.id,
        connection!.token,
        signal,
      ),
  });

  async function execute() {
    if (
      !connection ||
      !manifestQuery.data ||
      (mode === "REPLAY_LIVE" && !confirmLive)
    )
      return;
    setRunning(true);
    setError(undefined);
    setResult(undefined);
    const input: ReplayRequest = {
      manifest: manifestQuery.data.data,
      mode,
      confirm_live: confirmLive,
    };
    try {
      setResult(
        await apiClient.replaySession(
          connection.session.data.id,
          input,
          connection.token,
        ),
      );
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="replay-page" id="main-content">
      <header className="replay-header">
        <div>
          <p>Reproducibility / exact pins</p>
          <h1>Replay controls</h1>
        </div>
        <span className="graph-session">
          {connection
            ? `Source ${connection.session.data.id}`
            : "No restored session"}
        </span>
      </header>
      {!connection ? (
        <section className="replay-state">
          <h2>A restored session is required</h2>
          <p>
            Start or restore a session to inspect its finalized manifest and
            replay state.
          </p>
          <a href="#/new-session">Create a session</a>
        </section>
      ) : manifestQuery.isPending ? (
        <div className="replay-state" role="status">
          Reading finalized run manifest...
        </div>
      ) : manifestQuery.error ? (
        <div className="replay-state replay-state--error" role="alert">
          <strong>Replay controls unavailable</strong>
          <span>{messageFor(manifestQuery.error)}</span>
        </div>
      ) : manifestQuery.data ? (
        <div className="replay-workspace">
          <section
            className="replay-manifest"
            aria-labelledby="replay-manifest-title"
          >
            <p>Exact source binding</p>
            <h2 id="replay-manifest-title">Finalized run manifest</h2>
            <dl className="replay-facts">
              <div>
                <dt>Identity</dt>
                <dd>{manifestQuery.data.data.manifest_id}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{manifestQuery.data.data.manifest_version}</dd>
              </div>
              <div>
                <dt>Hash</dt>
                <dd>
                  <code>{manifestQuery.data.data.manifest_hash}</code>
                </dd>
              </div>
              <div>
                <dt>Code pin</dt>
                <dd>{manifestQuery.data.data.git_sha}</dd>
              </div>
            </dl>
          </section>
          <section
            className="replay-controls"
            aria-labelledby="replay-mode-title"
          >
            <p>Select one explicit replay mode</p>
            <h2 id="replay-mode-title">Mode</h2>
            <div
              className="replay-mode-list"
              role="radiogroup"
              aria-label="Replay mode"
            >
              {modes.map((item) => (
                <label
                  className={`replay-mode${mode === item ? " replay-mode--selected" : ""}`}
                  key={item}
                >
                  <input
                    checked={mode === item}
                    name="replay-mode"
                    onChange={() => {
                      setMode(item);
                      setConfirmLive(false);
                    }}
                    type="radio"
                    value={item}
                  />
                  <span>
                    <strong>{item}</strong>
                    <small>{modeSummary(item)}</small>
                  </span>
                </label>
              ))}
            </div>
            {mode === "REPLAY_LIVE" ? (
              <label className="replay-confirm">
                <input
                  checked={confirmLive}
                  onChange={(event) => setConfirmLive(event.target.checked)}
                  type="checkbox"
                />{" "}
                I understand this creates a new execution, preserves the
                historical source, and records source-session lineage.
              </label>
            ) : null}
            <button
              disabled={running || (mode === "REPLAY_LIVE" && !confirmLive)}
              onClick={() => void execute()}
              type="button"
            >
              {running ? "Executing replay..." : `Execute ${mode}`}
            </button>
            {error ? (
              <p className="replay-error" role="alert">
                {error}
              </p>
            ) : null}
          </section>
          {result ? <Result result={result} /> : null}
        </div>
      ) : null}
    </main>
  );
}
