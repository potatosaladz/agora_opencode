import type { components } from "../../api/types";
import { StatusMark } from "../../components/status-mark";
import { useSystemHealth } from "./use-system-health";

type HealthStatus = components["schemas"]["HealthStatus"];

function ConnectionFailure({ message }: { message: string }) {
  return (
    <div className="connection-failure" role="alert">
      <span className="connection-failure__code">NO SIGNAL</span>
      <p>{message}</p>
      <p className="muted">
        Start backend on port 8000; next probe runs automatically.
      </p>
    </div>
  );
}

export function ObservatoryPage() {
  const { liveness, readiness } = useSystemHealth();
  const overallStatus: HealthStatus =
    readiness.data?.status ?? (readiness.isError ? "down" : "unknown");
  const components = Object.entries(readiness.data?.components ?? {});

  return (
    <main id="main-content" className="page page--observatory">
      <section className="hero" aria-labelledby="observatory-title">
        <div className="hero__copy">
          <p className="eyebrow">System observatory / Phase 1</p>
          <h1 id="observatory-title">
            Reasoning needs
            <em> visible foundations.</em>
          </h1>
          <p className="hero__lede">
            Live operational view of Agora's API and stateful dependencies.
            Green means observed, never assumed.
          </p>
        </div>
        <div
          className="hero__signal"
          aria-label={`System status: ${overallStatus}`}
        >
          <div className={`orb orb--${overallStatus}`} aria-hidden="true">
            <span />
          </div>
          <StatusMark
            status={overallStatus}
            label={`system ${overallStatus}`}
          />
        </div>
      </section>

      <section className="signal-grid" aria-label="Live system signals">
        <article className="signal-card signal-card--primary">
          <div className="signal-card__index">01</div>
          <div>
            <p className="label">API process</p>
            {liveness.data ? (
              <>
                <StatusMark status={liveness.data.status} label="live" />
                <h2>{liveness.data.service}</h2>
                <p className="mono">release / {liveness.data.version}</p>
              </>
            ) : liveness.isError ? (
              <ConnectionFailure message="Liveness endpoint did not answer." />
            ) : (
              <p role="status">Acquiring liveness signal…</p>
            )}
          </div>
        </article>

        <article className="signal-card">
          <div className="signal-card__index">02</div>
          <div>
            <p className="label">Traffic readiness</p>
            {readiness.data ? (
              <>
                <StatusMark status={readiness.data.status} />
                <h2>{components.length} dependencies</h2>
                <p className="muted">
                  Each adapter reports its own bounded health vocabulary.
                </p>
              </>
            ) : readiness.isError ? (
              <ConnectionFailure message="Readiness endpoint did not answer." />
            ) : (
              <p role="status">Acquiring readiness signal…</p>
            )}
          </div>
        </article>

        <article className="signal-card signal-card--principle">
          <div className="signal-card__index">03</div>
          <div>
            <p className="label">Authority model</p>
            <blockquote>Deterministic code decides. Models propose.</blockquote>
            <p className="muted">
              No system health claim is inferred from UI state.
            </p>
          </div>
        </article>
      </section>

      <section className="dependencies" aria-labelledby="dependencies-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Adapter field</p>
            <h2 id="dependencies-title">Dependency ledger</h2>
          </div>
          <p>
            Source / <code>GET /ready</code>
          </p>
        </div>
        {components.length > 0 ? (
          <ol className="dependency-list">
            {components.map(([name, component], index) => (
              <li key={name}>
                <span className="dependency-list__number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <strong>{name}</strong>
                <StatusMark status={component.status} />
                <span className="mono dependency-list__detail">
                  {Object.keys(component.details).length === 0
                    ? "no detail disclosed"
                    : Object.keys(component.details).join(" / ")}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="empty-field">
            <span aria-hidden="true">∅</span>
            <p>No dependency records received.</p>
          </div>
        )}
      </section>
    </main>
  );
}
