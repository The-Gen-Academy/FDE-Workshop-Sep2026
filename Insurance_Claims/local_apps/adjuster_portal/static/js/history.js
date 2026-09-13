const rowsEl = document.getElementById("rows");
const dateFromEl = document.getElementById("dateFrom");
const dateToEl = document.getElementById("dateTo");
const overrideOnlyEl = document.getElementById("overrideOnly");

async function loadHistory() {
  const params = new URLSearchParams();
  if (dateFromEl.value) params.set("date_from", dateFromEl.value);
  if (dateToEl.value) params.set("date_to", dateToEl.value + "T23:59:59");
  if (overrideOnlyEl.checked) params.set("override_only", "true");
  const items = await apiGet(`/api/history?${params.toString()}`);
  render(items);
}

function render(items) {
  if (items.length === 0) {
    rowsEl.innerHTML = `<div class="empty-state"><div>No resolved claims match these filters.</div></div>`;
    return;
  }
  rowsEl.innerHTML = items
    .map((it) => {
      const isOverride = it.matched_system_suggestion === false;
      return `
      <a class="claim-row" href="claim.html?id=${encodeURIComponent(it.claim_id)}">
        <div class="row-top">
          <div class="left">
            <span class="claim-id">${escapeHtml(it.claim_id)}</span>
            ${priorityPill(it.priority)}
            ${it.is_auto_approved ? '<span class="pill status-auto">system-approved</span>' : ""}
            ${it.is_auto_denied ? '<span class="pill status-auto-deny">system-denied</span>' : ""}
            ${isOverride ? '<span class="pill status-override">override</span>' : ""}
          </div>
          <span class="queued">${relativeTime(it.resolved_at)}</span>
        </div>
        <div class="meta">${escapeHtml(it.policyholder_name)} · ${escapeHtml(it.policy_number)}</div>
        <div class="desc"><strong>${escapeHtml(it.final_decision)}</strong>${
          isOverride ? ` — override reason: ${escapeHtml(it.override_reason)}` : ""
        }${it.adjuster_notes ? ` — notes: ${escapeHtml(it.adjuster_notes)}` : ""}</div>
      </a>`;
    })
    .join("");
}

[dateFromEl, dateToEl, overrideOnlyEl].forEach((el) => el.addEventListener("change", loadHistory));
document.getElementById("refreshBtn").addEventListener("click", loadHistory);

loadHistory();
if (localStorage.getItem("claims_demo_role") !== "adjuster") {
  location.href = "index.html";
}
