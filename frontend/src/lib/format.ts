/** "mm:ss", or "h:mm:ss" from one hour. */
export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "--:--";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const x = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(x).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** A rough remaining time: "~23 min", "~45 s", "~1 h 10 min"; "—" when unknown. */
export function approx(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `~${Math.max(5, Math.round(s / 5) * 5)} s`;
  const min = Math.round(s / 60);
  if (min < 60) return `~${min} min`;
  const h = Math.floor(min / 60);
  const rest = min % 60;
  return rest ? `~${h} h ${rest} min` : `~${h} h`;
}

export function percent(fraction: number | null | undefined): string {
  if (fraction == null || !isFinite(fraction)) return "0%";
  return `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%`;
}

/** "Oct 31, 14:52" in the viewer's time zone. */
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** "14:52:17" — log timestamps. */
export function timeOfDay(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** "library_system.models.loan.Loan.renew" → "Loan.renew". */
export function shortComponent(id: string): string {
  const parts = id.split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : id;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
