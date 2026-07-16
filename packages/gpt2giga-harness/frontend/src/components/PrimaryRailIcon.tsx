import type { SurfaceId } from "../navigation";

interface PrimaryRailIconProps {
  surface: SurfaceId;
}

export function PrimaryRailBrand() {
  return <img src="/assets/favicon.ico" alt="" width="30" height="30" />;
}

export function PrimaryRailIcon({ surface }: PrimaryRailIconProps) {
  const common = {
    "aria-hidden": true,
    className: "rail-icon",
    focusable: "false",
    viewBox: "0 0 24 24",
  } as const;

  switch (surface) {
    case "work":
      return (
        <svg {...common} data-icon="workbench">
          <circle cx="12" cy="12" r="3.25" />
          <path d="M12 2.75v3M12 18.25v3M2.75 12h3M18.25 12h3M5.46 5.46l2.12 2.12M16.42 16.42l2.12 2.12M18.54 5.46l-2.12 2.12M7.58 16.42l-2.12 2.12" />
        </svg>
      );
    case "runs":
      return (
        <svg {...common} data-icon="runs">
          <circle cx="12" cy="12" r="8.25" />
          <path className="rail-icon-accent" d="m10.25 8.75 5 3.25-5 3.25V8.75Z" />
          <path d="M3.75 8.25h2.1M2.75 12h2.1M3.75 15.75h2.1" />
        </svg>
      );
    case "automation":
      return (
        <svg {...common} data-icon="automation">
          <circle cx="6" cy="5" r="2" />
          <circle cx="18" cy="8" r="2" />
          <circle cx="18" cy="18" r="2" />
          <path d="M8 5h2a3 3 0 0 1 3 3v7a3 3 0 0 0 3 3M13 10a3 3 0 0 1 3-2" />
        </svg>
      );
    case "evaluation":
      return (
        <svg {...common} data-icon="evaluation">
          <rect x="3.5" y="5" width="6.5" height="14" rx="2" />
          <rect x="14" y="5" width="6.5" height="14" rx="2" />
          <path d="M6 12h1.5M16.5 9.5H18M16.5 12.5H18M6.25 15.25l1 1 1.75-2" />
        </svg>
      );
    case "integrations":
      return (
        <svg {...common} data-icon="integrations">
          <circle cx="12" cy="4.5" r="2.25" />
          <circle cx="5.25" cy="17.25" r="2.25" />
          <circle cx="18.75" cy="17.25" r="2.25" />
          <path d="m10.8 6.5-4.3 8.6M13.2 6.5l4.3 8.6M7.5 17.25h9" />
        </svg>
      );
  }
}
