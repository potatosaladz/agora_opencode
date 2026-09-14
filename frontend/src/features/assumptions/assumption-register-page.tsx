import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import {
  ApiProblem,
  apiClient,
  type AssumptionRegisterCritique,
  type AssumptionRegisterItem,
  type AssumptionRegisterRelation,
  type SessionResponse,
} from "../../api/client";

type AssumptionConnection = { session: SessionResponse; token: string };

function messageFor(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  if (error instanceof Error) return error.message;
  return "The authoritative assumption register could not be read.";
}

function graphHref(id: string): string {
  return `#/graph?root=${encodeURIComponent(id)}`;
}

function EvidenceList({
  title,
  empty,
  values,
}: {
  title: string;
  empty: string;
  values: AssumptionRegisterRelation[];
}) {
  return (
    <section className="assumption-related" aria-label={title}>
      <h3>{title}</h3>
      {values.length ? (
        <ul>
          {values.map((value) => (
            <li key={value.id}>
              {value.provenance_href ? (
                <a href={value.provenance_href}>{value.label ?? value.id}</a>
              ) : (
                <span>{value.label ?? value.id}</span>
              )}
              <span>{value.kind}</span>
              <span>{value.relationship}</span>
              {value.graph_node_id ? (
                <a href={graphHref(value.graph_node_id)}>Graph</a>
              ) : (
                <span>Graph unavailable</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </section>
  );
}

function Critiques({ values }: { values: AssumptionRegisterCritique[] }) {
  return (
    <section className="assumption-related" aria-label="Active critiques">
      <h3>Active critiques</h3>
      {values.length ? (
        <ul>
          {values.map((value) => (
            <li key={value.id}>
              <a href={`#/dissent#dissent-${value.id}`}>{value.id}</a>
              <span>{value.resolution}</span>
              <span>
                {value.critique_type} / {value.severity}
              </span>
              <a href={value.provenance_href}>Provenance</a>
            </li>
          ))}
        </ul>
      ) : (
        <p>No active critiques recorded.</p>
      )}
    </section>
  );
}

function Dependents({
  title,
  empty,
  values,
}: {
  title: string;
  empty: string;
  values: AssumptionRegisterRelation[];
}) {
  return (
    <section className="assumption-related" aria-label={title}>
      <h3>{title}</h3>
      {values.length ? (
        <ul>
          {values.map((value) => (
            <li key={`${value.kind}-${value.id}`}>
              {value.provenance_href ? (
                <a href={value.provenance_href}>{value.label ?? value.id}</a>
              ) : (
                <span>{value.label ?? value.id}</span>
              )}
              <span>{value.kind}</span>
              {value.graph_node_id ? (
                <a href={graphHref(value.graph_node_id)}>Graph</a>
              ) : (
                <span>Graph unavailable</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </section>
  );
}

function SymbolicResult({ item }: { item: AssumptionRegisterItem }) {
  if (item.kind !== "CONSTRAINT") {
    return (
      <section className="symbolic-result" aria-label="Symbolic assessment">
        <span>Symbolic status</span>
        <strong>NOT APPLICABLE</strong>
        <p>
          Symbolic constraint evaluation does not apply to this artifact kind.
        </p>
      </section>
    );
  }
  const missing = item.symbolic?.status == null;
  const unknown = item.symbolic?.status === "UNKNOWN";
  const status = item.symbolic?.status ?? "NOT EVALUATED";
  const action = item.symbolic?.policy_action ?? "DEFER";
  return (
    <section
      className={`symbolic-result symbolic-result--${status.toLowerCase()}`}
      aria-label="Symbolic assessment"
    >
      <span>Symbolic status</span>
      <strong>{status}</strong>
      <p>
        {unknown
          ? "not determined"
          : missing
            ? "No symbolic evaluation is recorded"
            : "Determined by symbolic analysis"}
      </p>
      <p>
        {unknown ? "symbolic assurance unavailable" : item.symbolic?.reason}
      </p>
      <b>{unknown || missing ? "DEFER" : action}</b>
    </section>
  );
}

function RegisterCard({
  item,
  index,
  selected,
  onSelect,
  onMove,
  setRef,
}: {
  item: AssumptionRegisterItem;
  index: number;
  selected: boolean;
  onSelect: () => void;
  onMove: (event: KeyboardEvent<HTMLElement>, index: number) => void;
  setRef: (node: HTMLElement | null) => void;
}) {
  const headingId = `assumption-${item.id}`;
  const contextId = `${headingId}-context`;
  return (
    <article
      aria-labelledby={headingId}
      aria-describedby={contextId}
      className={`assumption-card assumption-card--${item.kind.toLowerCase()}${selected ? " assumption-card--selected" : ""}`}
      onClick={onSelect}
      onFocus={onSelect}
      onKeyDown={(event) => onMove(event, index)}
      ref={setRef}
      tabIndex={selected ? 0 : -1}
    >
      <header>
        <div>
          <span className="assumption-position">
            {String(index + 1).padStart(2, "0")}
          </span>
          <span className="assumption-type">{item.kind}</span>
          <span
            className={`assumption-lifecycle assumption-lifecycle--${item.lifecycle.toLowerCase()}`}
          >
            {item.lifecycle}
          </span>
          {item.critiques.some(
            (critique) => critique.resolution === "DISPUTED",
          ) ? (
            <span className="assumption-disputed">DISPUTED</span>
          ) : null}
        </div>
        <h2 id={headingId}>{item.statement ?? "Statement unavailable"}</h2>
        <p id={contextId}>
          {item.context_artifact_id
            ? `Context artifact ${item.context_artifact_id}`
            : "Context unavailable"}
        </p>
      </header>

      {!item.symbolic || item.symbolic.analysis_status !== "AVAILABLE" ? (
        <div className="assumption-unavailable" role="note">
          <strong>Analysis unavailable</strong>
          <span>
            {item.symbolic?.reason ??
              "No symbolic analysis is available for this register entry."}
          </span>
        </div>
      ) : null}

      <div className="assumption-facts">
        <dl>
          <div>
            <dt>Category</dt>
            <dd>
              {item.category ??
                item.constraint_type ??
                item.uncertainty_type ??
                "Category unavailable"}
            </dd>
          </div>
          <div>
            <dt>Type detail</dt>
            <dd>
              {item.constraint_type ?? item.uncertainty_type ?? item.kind}
            </dd>
          </div>
          <div>
            <dt>Formal status</dt>
            <dd>{item.formal_status ?? "Not applicable"}</dd>
          </div>
          <div>
            <dt>Owner</dt>
            <dd>
              {item.owner.actor_id} / {item.owner.actor_class}
            </dd>
          </div>
          <div>
            <dt>Origin</dt>
            <dd>
              Round {item.round} / version {item.version}
            </dd>
          </div>
          <div>
            <dt>Basis</dt>
            <dd>{item.basis ?? "Basis unavailable"}</dd>
          </div>
          <div>
            <dt>Materiality</dt>
            <dd>{item.materiality ?? "Materiality unavailable"}</dd>
          </div>
          <div>
            <dt>Challengeable</dt>
            <dd>
              {item.challengeable === null
                ? "Challengeability unavailable"
                : item.challengeable
                  ? "Yes"
                  : "No"}
            </dd>
          </div>
          <div>
            <dt>Uncertainty drivers</dt>
            <dd>{item.drivers?.join(", ") || "Not applicable"}</dd>
          </div>
          <div>
            <dt>Uncertainty representation</dt>
            <dd>
              {item.representation
                ? JSON.stringify(item.representation)
                : "Not applicable"}
            </dd>
          </div>
        </dl>
        <SymbolicResult item={item} />
      </div>

      <div className="assumption-columns">
        <div>
          <EvidenceList
            title="Supporting evidence"
            empty="No supporting evidence recorded."
            values={item.evidence.filter(
              (value) => value.relationship === "SUPPORTS",
            )}
          />
          <EvidenceList
            title="Opposing evidence"
            empty="No opposing evidence recorded."
            values={item.evidence.filter(
              (value) => value.relationship === "OPPOSES",
            )}
          />
          <EvidenceList
            title="Qualifying evidence"
            empty="No qualifying evidence recorded."
            values={item.evidence.filter(
              (value) => value.relationship === "QUALIFIES",
            )}
          />
        </div>
        <div>
          <Critiques values={item.critiques} />
          <Dependents
            title="Dependent claims"
            empty="No dependent claims recorded."
            values={item.dependents.filter((value) => value.kind === "CLAIM")}
          />
          <Dependents
            title="Dependent recommendations"
            empty="No dependent recommendations recorded."
            values={item.dependents.filter(
              (value) => value.kind === "RECOMMENDATION",
            )}
          />
          <Dependents
            title="Dependent artifacts"
            empty="No other dependent artifacts recorded."
            values={item.dependents.filter(
              (value) =>
                value.kind !== "CLAIM" && value.kind !== "RECOMMENDATION",
            )}
          />
        </div>
      </div>

      <footer>
        <a href={item.provenance_href}>Open provenance</a>
        {item.graph_node_id ? (
          <a href={graphHref(item.graph_node_id)}>Open in graph</a>
        ) : (
          <span>Graph unavailable</span>
        )}
        <span>Logical ID {item.logical_id}</span>
      </footer>
    </article>
  );
}

export default function AssumptionRegisterPage({
  connection,
}: {
  connection?: AssumptionConnection;
}) {
  const [selected, setSelected] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const query = useQuery({
    enabled: connection !== undefined,
    queryKey: ["session-assumptions", connection?.session.data.id],
    queryFn: ({ signal }) =>
      apiClient.getSessionAssumptions(
        connection!.session.data.id,
        connection!.token,
        signal,
      ),
  });

  function move(event: KeyboardEvent<HTMLElement>, index: number) {
    const count = query.data?.data.items.length ?? 0;
    if (!count) return;
    let next = index;
    if (event.key === "ArrowDown" || event.key === "ArrowRight")
      next = (index + 1) % count;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft")
      next = (index - 1 + count) % count;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    else return;
    event.preventDefault();
    setSelected(next);
    refs.current[next]?.focus();
  }

  return (
    <main className="assumption-page" id="main-content">
      <header className="assumption-header">
        <div>
          <p>Declared premises / authoritative order</p>
          <h1>Assumption register</h1>
        </div>
        <span>
          {connection
            ? `Session ${connection.session.data.id}`
            : "No restored session"}
        </span>
      </header>
      {!connection ? (
        <section
          className="assumption-empty"
          aria-labelledby="assumption-no-session"
        >
          <h2 id="assumption-no-session">A restored session is required</h2>
          <p>
            Start or restore a session to inspect its assumptions, constraints,
            and uncertainties.
          </p>
          <a href="#/new-session">Create a session</a>
        </section>
      ) : query.isPending ? (
        <div className="assumption-state" role="status">
          Reading the authoritative assumption register...
        </div>
      ) : query.error ? (
        <div className="assumption-state assumption-state--error" role="alert">
          <strong>Assumption register unavailable</strong>
          <span>{messageFor(query.error)}</span>
        </div>
      ) : query.data.data.items.length === 0 ? (
        <section
          className="assumption-empty"
          aria-labelledby="assumption-empty"
        >
          <h2 id="assumption-empty">No register entries</h2>
          <p>
            The server returned an empty assumption register for this session.
          </p>
        </section>
      ) : (
        <section
          className="assumption-register"
          aria-labelledby="register-title"
        >
          <header>
            <div>
              <span>Server sequence</span>
              <h2 id="register-title">Declared reasoning conditions</h2>
            </div>
            <p>
              {query.data.data.items.length} entries. Use arrow keys, Home, or
              End to move through the register.
            </p>
          </header>
          <div aria-label="Assumptions, constraints, and uncertainties">
            {query.data.data.items.map((item, index) => (
              <RegisterCard
                item={item}
                index={index}
                key={`${item.id}-${item.version}`}
                selected={selected === index}
                onSelect={() => setSelected(index)}
                onMove={move}
                setRef={(node) => {
                  refs.current[index] = node;
                }}
              />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
