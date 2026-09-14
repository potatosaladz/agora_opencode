type IconName =
  | "activity"
  | "archive"
  | "bell"
  | "book"
  | "check"
  | "chevron"
  | "clock"
  | "coins"
  | "flask"
  | "grid"
  | "history"
  | "message"
  | "network"
  | "pause"
  | "plus"
  | "radio"
  | "send"
  | "settings"
  | "stop"
  | "target"
  | "users";

type IconProps = {
  name: IconName;
  size?: number;
};

export function Icon({ name, size = 16 }: IconProps) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.7,
  };

  const content = {
    activity: <path {...common} d="M3 12h3l2.2-6 3.4 12L14 9l1.8 3H21" />,
    archive: (
      <>
        <path {...common} d="M4 7h16v13H4zM3 4h18v3H3z" />
        <path {...common} d="M9 11h6" />
      </>
    ),
    bell: (
      <>
        <path {...common} d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
        <path {...common} d="M10 21h4" />
      </>
    ),
    book: (
      <>
        <path
          {...common}
          d="M4 5.5A3.5 3.5 0 0 1 7.5 2H11v17H7.5A3.5 3.5 0 0 0 4 22z"
        />
        <path
          {...common}
          d="M20 5.5A3.5 3.5 0 0 0 16.5 2H13v17h3.5A3.5 3.5 0 0 1 20 22z"
        />
      </>
    ),
    check: <path {...common} d="m5 12 4 4L19 6" />,
    chevron: <path {...common} d="m9 18 6-6-6-6" />,
    clock: (
      <>
        <circle {...common} cx="12" cy="12" r="9" />
        <path {...common} d="M12 7v5l3 2" />
      </>
    ),
    coins: (
      <>
        <ellipse {...common} cx="12" cy="6" rx="7" ry="3" />
        <path
          {...common}
          d="M5 6v5c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 11v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5"
        />
      </>
    ),
    flask: (
      <>
        <path
          {...common}
          d="M9 3h6M10 3v6l-5 9.5A1.7 1.7 0 0 0 6.5 21h11a1.7 1.7 0 0 0 1.5-2.5L14 9V3"
        />
        <path {...common} d="M7 16h10" />
      </>
    ),
    grid: (
      <>
        <rect {...common} x="3" y="3" width="7" height="7" />
        <rect {...common} x="14" y="3" width="7" height="7" />
        <rect {...common} x="3" y="14" width="7" height="7" />
        <rect {...common} x="14" y="14" width="7" height="7" />
      </>
    ),
    history: (
      <>
        <path {...common} d="M3 12a9 9 0 1 0 3-6.7L3 8" />
        <path {...common} d="M3 3v5h5M12 7v5l4 2" />
      </>
    ),
    message: <path {...common} d="M4 4h16v13H8l-4 4z" />,
    network: (
      <>
        <circle {...common} cx="12" cy="5" r="2.5" />
        <circle {...common} cx="5" cy="18" r="2.5" />
        <circle {...common} cx="19" cy="18" r="2.5" />
        <path {...common} d="m10.8 7.2-4.5 8.6M13.2 7.2l4.5 8.6M7.5 18h9" />
      </>
    ),
    pause: (
      <>
        <path {...common} d="M8 5v14M16 5v14" />
      </>
    ),
    plus: <path {...common} d="M12 5v14M5 12h14" />,
    radio: (
      <>
        <circle {...common} cx="12" cy="12" r="2" />
        <path
          {...common}
          d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M4.6 4.6a10.5 10.5 0 0 0 0 14.8M19.4 4.6a10.5 10.5 0 0 1 0 14.8"
        />
      </>
    ),
    send: <path {...common} d="m3 11 18-8-8 18-2-8zM11 13l10-10" />,
    settings: (
      <>
        <circle {...common} cx="12" cy="12" r="3" />
        <path
          {...common}
          d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"
        />
      </>
    ),
    stop: <rect {...common} x="6" y="6" width="12" height="12" rx="1" />,
    target: (
      <>
        <circle {...common} cx="12" cy="12" r="9" />
        <circle {...common} cx="12" cy="12" r="5" />
        <circle {...common} cx="12" cy="12" r="1" />
      </>
    ),
    users: (
      <>
        <circle {...common} cx="9" cy="8" r="3" />
        <path {...common} d="M3 20c0-4 2-7 6-7s6 3 6 7" />
        <path {...common} d="M15 5.5a3 3 0 0 1 0 5.5M17 13c2.6.8 4 3.2 4 6" />
      </>
    ),
  }[name];

  return (
    <svg
      aria-hidden="true"
      className="icon"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      {content}
    </svg>
  );
}
