import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import {
  ApiProblem,
  apiClient,
  type ExplanationResponse,
  type SessionResponse,
} from "../../api/client";

type ExplanationConnection = { session: SessionResponse; token: string };
type ExplanationData = ExplanationResponse["data"];
type JsonObject = Record<string, unknown>;
type ExplanationMode = "executive" | "expert" | "formal" | "machine";

const sections = [
  ["decision", "Decision / recommendation"],
  ["why-selected", "Why selected"],
  ["alternatives", "Alternatives"],
  ["supporting-evidence", "Supporting evidence"],
  ["opposing-evidence", "Opposing evidence"],
  ["qualifying-evidence", "Qualifying evidence"],
  ["assumptions-constraints", "Assumptions / constraints"],
  ["minority-dissent", "Minority / dissent"],
  ["critiques-objections", "Critiques / unresolved objections"],
  ["risks-uncertainties", "Risks / uncertainties"],
  ["symbolic-feasibility", "Symbolic feasibility"],
  ["conditions", "Conditions"],
  ["counterfactuals", "Counterfactuals"],
  ["provenance-traceability", "Provenance / traceability"],
  ["weakest-evidence", "Weakest evidence"],
] as const;

function object(value: unknown): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function words(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "The authoritative explanation could not be read.";
}

function graphHref(id: string): string {
  return `#/graph?root=${encodeURIComponent(id)}`;
}

function isNumericFact(value: JsonObject): boolean {
  return (
    "value" in value &&
    "kind" in value &&
    "version" in value &&
    "caveat" in value
  );
}

function Value({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === "")
    return (
      <span className="explanation-unavailable">
        {words(label)} unavailable
      </span>
    );
  if (Array.isArray(value)) {
    return value.length ? (
      <ol className="explanation-nested-list">
        {value.map((item, index) => (
          <li key={index}>
            <Value label={`${label} ${index + 1}`} value={item as unknown} />
          </li>
        ))}
      </ol>
    ) : (
      <span className="explanation-unavailable">
        No {words(label)} recorded.
      </span>
    );
  }
  if (typeof value === "object" && value !== null) {
    const record = object(value);
    if (isNumericFact(record)) {
      return (
        <dl
          className="explanation-values"
          aria-label={`Persisted numeric value: ${text(record.kind) ?? words(label)}`}
        >
          <div>
            <dt>Kind</dt>
            <dd>{text(record.kind) ?? "Unavailable"}</dd>
          </div>
          <div>
            <dt>Value</dt>
            <dd>{String(record.value)}</dd>
          </div>
          <div>
            <dt>Unit</dt>
            <dd>{text(record.unit) ?? "Unavailable: no unit recorded"}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd>{text(record.version) ?? "Unavailable"}</dd>
          </div>
          <div>
            <dt>Caveat</dt>
            <dd>{text(record.caveat) ?? "Unavailable"}</dd>
          </div>
        </dl>
      );
    }
    return <RecordView value={record} />;
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return <span>{String(value)}</span>;
  }
  return <span>Unavailable</span>;
}

function RecordView({ value }: { value: JsonObject }) {
  const hidden = new Set([
    "empty_reason",
    "trust_level",
    "confidence",
    "agent_reported_confidence",
    "position_score",
    "evidence_score",
    "score",
    "composite",
  ]);
  const entries = Object.entries(value).filter(([key]) => !hidden.has(key));
  return (
    <dl className="explanation-record-fields">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{words(key)}</dt>
          <dd>
            <Value label={key} value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ArtifactLinks({ value }: { value: JsonObject }) {
  const provenance = text(value.provenance_href) ?? text(value.href);
  const graphNode = text(value.graph_node_id);
  const artifactId = text(value.id) ?? text(value.evidence_id);
  return (
    <div className="explanation-links">
      {graphNode ? (
        <a href={graphHref(graphNode)}>Open in graph</a>
      ) : artifactId ? (
        <a href={`#/graph?root=${encodeURIComponent(artifactId)}`}>
          Open in graph
        </a>
      ) : (
        <span>Graph relationship unavailable</span>
      )}
      {provenance ? (
        <a href={provenance}>Open provenance</a>
      ) : artifactId?.startsWith("art_") ? (
        <a
          href={`/api/v1/artifacts/${encodeURIComponent(artifactId)}/provenance`}
        >
          Open provenance
        </a>
      ) : (
        <span>Provenance link unavailable</span>
      )}
    </div>
  );
}

function Entry({ value, label }: { value: unknown; label: string }) {
  const record = object(value);
  const lifecycle = text(record.lifecycle);
  const title =
    text(record.title) ??
    text(record.label) ??
    text(record.statement) ??
    text(record.position) ??
    text(record.id) ??
    label;
  return (
    <article className="explanation-entry">
      <header>
        <span>{text(record.kind) ?? label}</span>
        {lifecycle ? (
          <span
            className={`explanation-lifecycle explanation-lifecycle--${lifecycle.toLowerCase()}`}
          >
            {lifecycle}
          </span>
        ) : null}
      </header>
      <h3>{title}</h3>
      {text(record.relation) ? (
        <p className="explanation-relationship">
          Relationship: <strong>{text(record.relation)}</strong>
        </p>
      ) : null}
      {lifecycle === "WITHDRAWN" ? (
        <p className="explanation-warning" role="note">
          Withdrawn support: retained for traceability and not current support.
        </p>
      ) : null}
      {record.citations !== undefined && list(record.citations).length === 0 ? (
        <p className="explanation-warning" role="note">
          Incomplete provenance: no citation was recorded.
        </p>
      ) : null}
      {record.complete === false ? (
        <p className="explanation-warning" role="note">
          Incomplete provenance: the server marked this trace incomplete.
        </p>
      ) : null}
      <RecordView value={record} />
      <ArtifactLinks value={record} />
    </article>
  );
}

function Section({
  id,
  title,
  values,
  emptyReason,
  fallback,
  link,
}: {
  id: string;
  title: string;
  values: unknown[];
  emptyReason?: unknown;
  fallback: string;
  link?: string;
}) {
  const index = sections.findIndex(([key]) => key === id) + 1;
  return (
    <section
      className="explanation-section"
      id={id}
      aria-labelledby={`${id}-title`}
      tabIndex={-1}
    >
      <header>
        <span aria-hidden="true">{String(index).padStart(2, "0")}</span>
        <h2 id={`${id}-title`}>{title}</h2>
        {link ? <a href={link}>Open related view</a> : null}
      </header>
      {values.length ? (
        <div className="explanation-list">
          {values.map((value, itemIndex) => (
            <Entry key={itemIndex} label={title} value={value} />
          ))}
        </div>
      ) : (
        <p className="explanation-empty">{text(emptyReason) ?? fallback}</p>
      )}
    </section>
  );
}

function AvailableExplanation({ data }: { data: ExplanationData }) {
  const navRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [active, setActive] = useState(0);
  const [mode, setMode] = useState<ExplanationMode>("expert");
  const recommendation = object(data.recommendation);
  const why = object(data.why);
  const evidence = object(data.evidence);
  const assumptions = object(data.assumptions_constraints);
  const critiques = object(data.critiques);
  const risks = object(data.risks_uncertainties);
  const symbolic = object(data.symbolic_feasibility);
  const conditional = object(data.conditions_counterfactuals);
  const provenance = object(data.provenance);
  const weakest = object(data.weakest_evidence);

  function move(event: KeyboardEvent<HTMLAnchorElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight" || event.key === "ArrowDown")
      next = (index + 1) % sections.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp")
      next = (index - 1 + sections.length) % sections.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = sections.length - 1;
    else return;
    event.preventDefault();
    setActive(next);
    navRefs.current[next]?.focus();
  }

  const sectionNodes: ReactNode[] = [
    <Section
      id="decision"
      title="Decision / recommendation"
      values={[data.decision, ...list(recommendation.items)]}
      emptyReason={
        object(data.decision).empty_reason ?? recommendation.empty_reason
      }
      fallback="No decision or recommendation was recorded."
    />,
    <Section
      id="why-selected"
      title="Why selected"
      values={[
        {
          formula: why.formula,
          strategy: why.strategy,
          strategy_version: why.strategy_version,
          derivation: why.derivation,
          contributions: why.contributions,
          caveats: why.caveats,
          drivers: why.drivers,
          inhibitors: why.inhibitors,
          absent: why.absent,
        },
      ]}
      emptyReason={why.empty_reason}
      fallback="No selection rationale was recorded."
    />,
    <Section
      id="alternatives"
      title="Alternatives"
      values={data.alternatives}
      fallback="No alternatives were recorded."
    />,
    <Section
      id="supporting-evidence"
      title="Supporting evidence"
      values={list(evidence.supporting)}
      emptyReason={evidence.empty_reason}
      fallback="No supporting evidence was recorded."
    />,
    <Section
      id="opposing-evidence"
      title="Opposing evidence"
      values={list(evidence.opposing)}
      emptyReason={evidence.empty_reason}
      fallback="No opposing evidence was recorded."
    />,
    <Section
      id="qualifying-evidence"
      title="Qualifying evidence"
      values={list(evidence.qualifying)}
      emptyReason={evidence.empty_reason}
      fallback="No qualifying evidence was recorded."
    />,
    <Section
      id="assumptions-constraints"
      title="Assumptions / constraints"
      values={list(assumptions.items)}
      emptyReason={assumptions.empty_reason}
      fallback="No assumptions or constraints were recorded."
      link="#/assumptions"
    />,
    <Section
      id="minority-dissent"
      title="Minority / dissent"
      values={data.minority}
      fallback="No minority or dissent position was recorded."
      link="#/dissent"
    />,
    <Section
      id="critiques-objections"
      title="Critiques / unresolved objections"
      values={list(critiques.unresolved)}
      emptyReason={critiques.empty_reason}
      fallback="No unresolved critique or objection was recorded."
      link="#/dissent"
    />,
    <Section
      id="risks-uncertainties"
      title="Risks / uncertainties"
      values={list(risks.items)}
      emptyReason={risks.empty_reason}
      fallback="No risks or uncertainties were recorded."
    />,
    <Section
      id="symbolic-feasibility"
      title="Symbolic feasibility"
      values={list(symbolic.constraints)}
      emptyReason={symbolic.empty_reason}
      fallback="Symbolic feasibility is unavailable; assurance is unavailable and the conservative action is DEFER."
    />,
    <Section
      id="conditions"
      title="Conditions"
      values={list(conditional.conditions)}
      emptyReason={conditional.empty_reason}
      fallback="No conditions were recorded."
    />,
    <Section
      id="counterfactuals"
      title="Counterfactuals"
      values={list(conditional.counterfactuals)}
      emptyReason={conditional.empty_reason}
      fallback="No counterfactuals were recorded."
    />,
    <Section
      id="provenance-traceability"
      title="Provenance / traceability"
      values={[provenance]}
      emptyReason={provenance.empty_reason}
      fallback="No provenance or traceability record is available."
    />,
    <section
      className="explanation-section explanation-weakest"
      id="weakest-evidence"
      aria-labelledby="weakest-evidence-title"
      tabIndex={-1}
    >
      <header>
        <span aria-hidden="true">15</span>
        <h2 id="weakest-evidence-title">Weakest evidence</h2>
      </header>
      {weakest.available === true ? (
        <>
          <p className="explanation-rationale">
            <strong>Recorded reason this evidence is weakest:</strong>{" "}
            {text(weakest.rationale) ?? "Recorded rationale unavailable."}
          </p>
          <Entry label="Weakest evidence" value={weakest} />
        </>
      ) : (
        <p className="explanation-empty">
          {text(weakest.rationale) ??
            "Weakest evidence was not identified by the server."}
        </p>
      )}
    </section>,
  ];

  const visibleSections =
    mode === "executive"
      ? new Set([
          "decision",
          "why-selected",
          "minority-dissent",
          "weakest-evidence",
        ])
      : mode === "formal"
        ? new Set([
            "why-selected",
            "symbolic-feasibility",
            "conditions",
            "counterfactuals",
            "provenance-traceability",
          ])
        : null;

  if (mode === "machine") {
    return (
      <div className="explanation-record">
        <ExplanationModes mode={mode} onChange={setMode} />
        <section
          className="explanation-machine"
          aria-labelledby="machine-title"
        >
          <h2 id="machine-title">Machine-readable explanation</h2>
          <p>
            The exact authenticated response is shown without generated prose.
          </p>
          <pre>{JSON.stringify(data, null, 2)}</pre>
        </section>
      </div>
    );
  }

  return (
    <div className="explanation-record">
      <ExplanationModes mode={mode} onChange={setMode} />
      <nav className="explanation-jump" aria-label="Explanation sections">
        <p>
          Section navigation <span>Use arrow keys, Home, or End</span>
        </p>
        <div>
          {sections.map(([id, title], index) => (
            <a
              href={`#${id}`}
              key={id}
              onFocus={() => setActive(index)}
              onKeyDown={(event) => move(event, index)}
              ref={(node) => {
                navRefs.current[index] = node;
              }}
              tabIndex={active === index ? 0 : -1}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              {title}
            </a>
          ))}
        </div>
      </nav>
      <div className="explanation-body">
        {sectionNodes.map((node, index) =>
          visibleSections === null ||
          visibleSections.has(sections[index]![0]) ? (
            <div key={sections[index]?.[0]}>{node}</div>
          ) : null,
        )}
      </div>
    </div>
  );
}

function ExplanationModes({
  mode,
  onChange,
}: {
  mode: ExplanationMode;
  onChange: (mode: ExplanationMode) => void;
}) {
  const modes: Array<[ExplanationMode, string]> = [
    ["executive", "Executive"],
    ["expert", "Expert"],
    ["formal", "Formal"],
    ["machine", "Machine-readable"],
  ];
  return (
    <nav className="explanation-modes" aria-label="Explanation view">
      {modes.map(([value, label]) => (
        <button
          aria-pressed={mode === value}
          key={value}
          onClick={() => onChange(value)}
          type="button"
        >
          {label}
        </button>
      ))}
    </nav>
  );
}

export default function ExplanationPage({
  connection,
}: {
  connection?: ExplanationConnection;
}) {
  const query = useQuery({
    enabled: connection !== undefined,
    queryKey: ["session-explanation", connection?.session.data.id],
    queryFn: ({ signal }) =>
      apiClient.getSessionExplanation(
        connection!.session.data.id,
        connection!.token,
        signal,
      ),
  });
  const status = query.data?.data.status;
  return (
    <main className="explanation-page" id="main-content">
      <header className="explanation-header">
        <div>
          <p>Authoritative record / no inference</p>
          <h1>Explanation panel</h1>
        </div>
        <span>
          {connection
            ? `Session ${connection.session.data.id}`
            : "No restored session"}
        </span>
      </header>
      {!connection ? (
        <section
          className="explanation-state"
          aria-labelledby="explanation-no-session"
        >
          <h2 id="explanation-no-session">A restored session is required</h2>
          <p>
            Start or restore a session to inspect its persisted explanation.
          </p>
          <a href="#/new-session">Create a session</a>
        </section>
      ) : query.isPending ? (
        <div className="explanation-state" role="status">
          Reading the authoritative explanation...
        </div>
      ) : query.error ? (
        <div
          className="explanation-state explanation-state--error"
          role="alert"
        >
          <strong>Explanation unavailable</strong>
          <span>{errorMessage(query.error)}</span>
        </div>
      ) : status === "NO_CONSENSUS_RESULT" ? (
        <section
          className="explanation-state"
          aria-labelledby="explanation-no-consensus"
        >
          <h2 id="explanation-no-consensus">No consensus result</h2>
          <p>
            {text(query.data.data.empty_reason) ??
              "This session has not produced a consensus result."}
          </p>
        </section>
      ) : status === "EXPLANATION_UNAVAILABLE" ? (
        <section
          className="explanation-state"
          aria-labelledby="explanation-unavailable"
        >
          <h2 id="explanation-unavailable">Explanation unavailable</h2>
          <p>
            {text(query.data.data.empty_reason) ??
              "A consensus result exists, but no persisted explanation is available."}
          </p>
        </section>
      ) : query.data ? (
        <AvailableExplanation data={query.data.data} />
      ) : null}
    </main>
  );
}
