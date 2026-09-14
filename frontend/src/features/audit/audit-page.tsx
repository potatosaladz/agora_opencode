import { useState } from "react";
import type { FormEvent, ReactNode } from "react";

import {
  ApiProblem,
  apiClient,
  type AuditQueryRequest,
  type AuditQuestion,
  type AuditResponse,
  type SessionResponse,
} from "../../api/client";

type AuditConnection = { session: SessionResponse; token: string };
type JsonObject = Record<string, unknown>;

const questions: Array<{ id: AuditQuestion; text: string; input: string }> = [
  { id: "Q1", text: "Why is this claim in the record?", input: "Artifact ID" },
  {
    id: "Q2",
    text: "Who changed this epistemic status, and on what warrant?",
    input: "Artifact ID",
  },
  { id: "Q3", text: "What did the agents see at round n?", input: "Round" },
  { id: "Q4", text: "Was a dissent suppressed?", input: "Round" },
  { id: "Q5", text: "Why did the session end?", input: "None" },
  {
    id: "Q6",
    text: "Which strategy and parameters produced this ranking?",
    input: "Round",
  },
  {
    id: "Q7",
    text: "Who accessed this recommendation before it was accepted?",
    input: "Recommendation ID",
  },
  {
    id: "Q8",
    text: "Has anything been altered since it was written?",
    input: "None",
  },
];

function words(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "The authoritative audit query failed.";
}

function record(value: unknown): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function AuditValue({ value }: { value: unknown }): ReactNode {
  if (value === null || value === "") return <span>Unavailable</span>;
  if (Array.isArray(value)) {
    return value.length ? (
      <ol className="audit-nested-list">
        {value.map((item, index) => (
          <li key={index}>
            <AuditValue value={item as unknown} />
          </li>
        ))}
      </ol>
    ) : (
      <span>No evidence recorded.</span>
    );
  }
  if (typeof value === "object") {
    return (
      <dl className="audit-value-grid">
        {Object.entries(record(value)).map(([key, item]) => (
          <div key={key}>
            <dt>{words(key)}</dt>
            <dd>
              <AuditValue value={item} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return <span>{String(value)}</span>;
  return <span>Unavailable</span>;
}

function AuditResult({ result }: { result: AuditResponse }) {
  const data = result.data;
  return (
    <section className="audit-result" aria-labelledby="audit-result-title">
      <header>
        <span>{data.question}</span>
        <h2 id="audit-result-title">{data.question_text}</h2>
      </header>
      <div className="audit-state-grid">
        <section aria-labelledby="audit-completeness-title">
          <h3 id="audit-completeness-title">Completeness</h3>
          <strong>{data.state.completeness}</strong>
          {data.state.completeness_reasons.length ? (
            <ul>
              {data.state.completeness_reasons.map((reason) => (
                <li key={reason}>{words(reason)}</li>
              ))}
            </ul>
          ) : (
            <p>The authoritative service reports a complete answer.</p>
          )}
        </section>
        <section aria-labelledby="audit-integrity-title">
          <h3 id="audit-integrity-title">Integrity verification</h3>
          <strong>{data.state.integrity}</strong>
          {data.state.integrity_reasons.length ? (
            <ul>
              {data.state.integrity_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : (
            <p>
              {data.state.integrity === "NOT_APPLICABLE"
                ? "This question does not assert ledger or anchor integrity."
                : "No integrity failure was reported."}
            </p>
          )}
        </section>
      </div>
      <section
        className="audit-answer"
        aria-labelledby="audit-parameters-title"
      >
        <h3 id="audit-parameters-title">Submitted parameters</h3>
        <AuditValue value={data.parameters} />
      </section>
      <section className="audit-answer" aria-labelledby="audit-answer-title">
        <h3 id="audit-answer-title">Persisted structured answer</h3>
        <AuditValue value={data.answer} />
      </section>
      <section
        className="audit-evidence"
        aria-labelledby="audit-evidence-title"
      >
        <h3 id="audit-evidence-title">Ordered evidence</h3>
        {data.evidence.length ? (
          <ol>
            {data.evidence.map((item, index) => (
              <li key={index} tabIndex={0}>
                <span>Evidence {index + 1}</span>
                <AuditValue value={item} />
              </li>
            ))}
          </ol>
        ) : (
          <p>No evidence was recorded for this answer.</p>
        )}
      </section>
      <nav aria-label="Related authoritative views" className="audit-links">
        {Object.entries(data.links).map(([name, href]) => (
          <a href={href} key={name}>
            {words(name)}
          </a>
        ))}
      </nav>
      {data.pagination.truncated ? (
        <p className="audit-page-note">
          This answer is paginated. Submit the returned cursor to continue in
          evidence order.
        </p>
      ) : null}
    </section>
  );
}

export default function AuditPage({
  connection,
}: {
  connection?: AuditConnection;
}) {
  const [question, setQuestion] = useState<AuditQuestion>("Q1");
  const [artifactId, setArtifactId] = useState("");
  const [recommendationId, setRecommendationId] = useState("");
  const [round, setRound] = useState("1");
  const [cursor, setCursor] = useState<string>();
  const [result, setResult] = useState<AuditResponse>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  function input(nextCursor?: string): AuditQueryRequest {
    if (question === "Q1")
      return {
        question: "Q1",
        artifact_id: artifactId,
        max_depth: 8,
        limit: 50,
        ...(nextCursor ? { cursor: nextCursor } : {}),
      };
    if (question === "Q2") return { question: "Q2", artifact_id: artifactId };
    if (question === "Q3") return { question: "Q3", round: Number(round) };
    if (question === "Q4") return { question: "Q4", round: Number(round) };
    if (question === "Q6") return { question: "Q6", round: Number(round) };
    if (question === "Q7")
      return {
        question,
        recommendation_id: recommendationId,
        limit: 100,
        ...(nextCursor ? { cursor: nextCursor } : {}),
      };
    return { question };
  }

  async function runAudit(nextCursor?: string) {
    if (!connection) return;
    setLoading(true);
    setError(undefined);
    setResult(undefined);
    try {
      setResult(
        await apiClient.querySessionAudit(
          connection.session.data.id,
          input(nextCursor),
          connection.token,
        ),
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setCursor(undefined);
    await runAudit();
  }

  return (
    <main className="audit-page" id="main-content">
      <header className="audit-header">
        <div>
          <p>Append-only authority / eight authored questions</p>
          <h1>Audit search</h1>
        </div>
        <span className="graph-session">
          {connection
            ? `Session ${connection.session.data.id}`
            : "No restored session"}
        </span>
      </header>
      {!connection ? (
        <section className="audit-empty" aria-labelledby="audit-empty-title">
          <h2 id="audit-empty-title">A restored session is required</h2>
          <p>Restore a session to ask its authoritative audit questions.</p>
          <a href="#/new-session">Create a session</a>
        </section>
      ) : (
        <div className="audit-workspace">
          <form
            className="audit-query"
            onSubmit={(event) => void submit(event)}
          >
            <fieldset>
              <legend>Choose one authored audit question</legend>
              <div className="audit-question-list">
                {questions.map((item) => (
                  <label key={item.id}>
                    <input
                      checked={question === item.id}
                      name="audit-question"
                      onChange={() => {
                        setQuestion(item.id);
                        setCursor(undefined);
                        setResult(undefined);
                      }}
                      type="radio"
                      value={item.id}
                    />
                    <span>
                      <strong>{item.id}</strong>
                      {item.text}
                      <small>Input: {item.input}</small>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            {question === "Q1" || question === "Q2" ? (
              <label>
                Artifact public ID
                <input
                  aria-label="Artifact public ID"
                  onChange={(event) => setArtifactId(event.target.value)}
                  placeholder="art_..."
                  required
                  value={artifactId}
                />
              </label>
            ) : null}
            {question === "Q3" || question === "Q4" || question === "Q6" ? (
              <label>
                Round
                <input
                  aria-label="Round"
                  min={question === "Q3" ? 0 : 1}
                  onChange={(event) => setRound(event.target.value)}
                  required
                  type="number"
                  value={round}
                />
              </label>
            ) : null}
            {question === "Q7" ? (
              <label>
                Recommendation public ID
                <input
                  aria-label="Recommendation public ID"
                  onChange={(event) => setRecommendationId(event.target.value)}
                  placeholder="rec_..."
                  required
                  value={recommendationId}
                />
              </label>
            ) : null}
            <button disabled={loading} type="submit">
              {loading
                ? "Reading authoritative audit facts..."
                : `Run ${question}`}
            </button>
            {error ? (
              <p className="audit-error" role="alert">
                {error}
              </p>
            ) : null}
          </form>
          {loading ? (
            <p role="status">Reading authoritative audit facts...</p>
          ) : null}
          {result ? <AuditResult result={result} /> : null}
          {result?.data.pagination.next_cursor ? (
            <button
              className="audit-next"
              disabled={loading}
              onClick={() => {
                const next = result.data.pagination.next_cursor ?? undefined;
                setCursor(next);
                void runAudit(next);
              }}
              type="button"
            >
              Load next evidence page
            </button>
          ) : null}
          {cursor ? (
            <p className="audit-page-note">Continuation cursor applied.</p>
          ) : null}
        </div>
      )}
    </main>
  );
}
