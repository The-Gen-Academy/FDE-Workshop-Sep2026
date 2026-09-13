function relativeTime(isoString) {
  if (!isoString) return "—";
  const then = new Date(isoString + (isoString.endsWith("Z") ? "" : "Z"));
  const diffMs = Date.now() - then.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function money(n) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function pct(n) {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 100)}%`;
}

function priorityPill(priority) {
  const label = priority ? priority.toUpperCase() : "UNKNOWN";
  return `<span class="pill priority-${priority}">${label}</span>`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
