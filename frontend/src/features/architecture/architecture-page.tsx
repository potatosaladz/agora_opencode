const commitments = [
  [
    "01",
    "PostgreSQL is the only system of record",
    "Caches and transports remain rebuildable.",
  ],
  [
    "02",
    "Deterministic code decides",
    "Models may propose; policy owns transitions.",
  ],
  [
    "03",
    "Every meaningful action is an event",
    "No ledger entry means no auditable claim.",
  ],
] as const;

export function ArchitecturePage() {
  return (
    <main id="main-content" className="page page--architecture">
      <header className="architecture-intro">
        <p className="eyebrow">Architecture / non-negotiable</p>
        <h1>Three rules hold the platform together.</h1>
        <p>
          Foundation skeleton preserves these boundaries before agent or
          consensus behavior lands.
        </p>
      </header>
      <ol className="commitment-list">
        {commitments.map(([index, title, detail]) => (
          <li key={index}>
            <span>{index}</span>
            <h2>{title}</h2>
            <p>{detail}</p>
          </li>
        ))}
      </ol>
    </main>
  );
}
