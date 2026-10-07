const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

export function formatDate(iso: string): string {
  return dateOnly.format(new Date(iso));
}

export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

/** "Chrome on macOS"-style description of a user agent string. */
export function describeUserAgent(ua: string | null | undefined): string {
  if (!ua) return "Unknown device";
  const browser =
    /Edg\//.test(ua) ? "Edge"
    : /OPR\//.test(ua) ? "Opera"
    : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : /curl|python|httpx|testclient/i.test(ua) ? "Script"
    : "Browser";
  const os =
    /iPhone|iPad/.test(ua) ? "iOS"
    : /Android/.test(ua) ? "Android"
    : /Mac OS X|Macintosh/.test(ua) ? "macOS"
    : /Windows/.test(ua) ? "Windows"
    : /Linux/.test(ua) ? "Linux"
    : null;
  return os ? `${browser} on ${os}` : browser;
}

/** "Mar 2021" for YYYY-MM, the year for YYYY. */
export function formatPartialDate(value: string | null | undefined): string {
  if (!value) return "Present";
  const [year, month] = value.split("-");
  if (!month) return year ?? value;
  const date = new Date(Number(year), Number(month) - 1, 1);
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(date);
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value > 0 && value < 0.01) return "<$0.01";
  return `$${value.toFixed(2)}`;
}

export const MODEL_LABELS: Record<string, string> = {
  "claude-opus-5-5": "Claude Opus 5.5",
  "claude-sonnet-5-5": "Claude Sonnet 5.5",
  "claude-haiku-4-5": "Claude Haiku 4.5",
  "claude-fable-5-1": "Claude Fable 5.1",
  "claude-opus-5": "Claude Opus 5",
  "claude-opus-4-8": "Claude Opus 4.8",
};

export function modelLabel(model: string): string {
  return MODEL_LABELS[model] ?? model;
}
