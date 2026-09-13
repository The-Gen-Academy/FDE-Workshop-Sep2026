if (localStorage.getItem("claims_demo_role") !== "adjuster") {
  location.href = "index.html";
}

const rowsEl = document.getElementById("rows");
const searchEl = document.getElementById("search");
const priorityEl = document.getElementById("priorityFilter");

async function loadQueue() {
  const params = new URLSearchParams();
  if (searchEl.value.trim()) params.set("q", searchEl.value.trim());
  if (priorityEl.value) params.set("priority", priorityEl.value);
  const items = await apiGet(`/api/queue?${params.toString()}`);
  render(items);
}

function render(items) {
  if (items.length === 0) {
    rowsEl.innerHTML = `
      <div class="empty-state">
        <div class="big">✓</div>
        <div>You're caught up. No claims waiting for review.</div>
      </div>`;
    return;
  }
  rowsEl.innerHTML = items
    .map((it) => {
      const cost = it.cost_low !== null ? `${money(it.cost_low)} – ${money(it.cost_high)}` : it.cost_not_assessed_reason;
      return `
      <a class="claim-row" href="claim.html?id=${encodeURIComponent(it.claim_id)}">
        <div class="row-top">
          <div class="left">
            <span class="claim-id">${escapeHtml(it.claim_id)}</span>
            ${priorityPill(it.priority)}
          </div>
          <span class="queued">${relativeTime(it.queued_at)}</span>
        </div>
        <div class="meta">${escapeHtml(it.policyholder_name)} · ${escapeHtml(it.policy_number)} · ${escapeHtml(it.incident_date)}</div>
        <div class="desc">${escapeHtml(it.incident_description)}</div>
        <div class="cost">${escapeHtml(cost)}</div>
      </a>`;
    })
    .join("");
}

searchEl.addEventListener("input", () => loadQueue());
priorityEl.addEventListener("change", () => loadQueue());
document.getElementById("refreshBtn").addEventListener("click", () => loadQueue());

loadQueue();
setInterval(loadQueue, 8000);
