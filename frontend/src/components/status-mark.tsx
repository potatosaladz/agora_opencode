import type { components } from "../api/types";

type HealthStatus = components["schemas"]["HealthStatus"];

type StatusMarkProps = {
  status: HealthStatus;
  label?: string;
};

export function StatusMark({ status, label = status }: StatusMarkProps) {
  return (
    <span
      className={`status-mark status-mark--${status}`}
      data-testid="status-mark"
    >
      <span className="status-mark__glyph" aria-hidden="true">
        {status === "ok"
          ? "●"
          : status === "degraded"
            ? "▲"
            : status === "down"
              ? "×"
              : "?"}
      </span>
      <span>{label}</span>
    </span>
  );
}
