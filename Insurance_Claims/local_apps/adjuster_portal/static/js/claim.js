if (localStorage.getItem("claims_demo_role") !== "adjuster") {
  location.href = "index.html";
}

const claimId = new URLSearchParams(location.search).get("id");
const contentEl = document.getElementById("content");
const CONSISTENCY_THRESHOLD = 0.7;
const EXCLUSION_CONFIDENCE_THRESHOLD = 0.5;

let currentClaim = null;
let selectedAction = null;

async function load() {
  if (!claimId) {
    contentEl.innerHTML = `<div class="card">No claim id given.</div>`;
    return;
  }
  try {
    currentClaim = await apiGet(`/api/claims/${encodeURIComponent(claimId)}`);
  } catch (e) {
    contentEl.innerHTML = `<div class="card">Claim not found.</div>`;
    return;
  }
  render();
}

function render() {
  const c = currentClaim;
  contentEl.innerHTML = `
    ${headerStrip(c)}
    ${incidentSection(c)}
    ${policySection(c)}
    ${evidenceSection(c)}
    ${coverageSection(c)}
    ${riskSection(c)}
    ${costSection(c)}
    ${prioritySection(c)}
    ${recommendationSection(c)}
    ${decisionSection(c)}
  `;
  wireDecisionForm();
}

function headerStrip(c) {
  const status =
    c.status === "auto_approved" ? "Auto-approved" :
    c.status === "auto_denied" ? "Auto-denied" :
    c.status === "resolved" ? "Resolved" : "Pending review";
  return `
  <div class="card section">
    <div class="row-top" style="margin-bottom:0">
      <div class="left">
        <span class="claim-id" style="font-size:18px">${escapeHtml(c.claim_id)}</span>
        ${priorityPill((c.priority_result || {}).priority)}
        <span class="meta">${escapeHtml(status)}</span>
      </div>
      <span class="queued">queued ${relativeTime(c.queued_at)}</span>
    </div>
  </div>`;
}

function fact(label, value) {
  return `<div class="fact"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(value)}</span></div>`;
}

function incidentSection(c) {
  const i = c.incident || {};
  const driverFlagged = (c.coverage_result || {}).status === "needs_review" && (c.coverage_result.reason || "").includes(i.driver_name);
  return `
  <div class="card section">
    <h2>Incident</h2>
    <p>${escapeHtml(i.description)}</p>
    <div class="fact-grid">
      ${fact("Date / time", `${i.incident_date || ""} ${i.incident_time || ""}`)}
      ${fact("Location", i.location)}
      ${fact("Driver", i.driver_name)}${driverFlagged ? '<span class="badge-danger">not a listed driver</span>' : ""}
      ${fact("Drivable?", i.is_drivable ? "Yes" : "No")}
      ${fact("Anyone injured?", i.anyone_injured ? "Yes" : "No")}
      ${fact("Other party involved?", i.other_party_involved ? i.other_party_info || "Yes" : "No")}
      ${fact("Police report filed?", i.police_report_filed ? "Yes" : "No")}
    </div>
  </div>`;
}

function policySection(c) {
  const p = c.policy || {};
  const cov = p.coverage || {};
  return `
  <div class="card section">
    <h2>Policy</h2>
    <div class="fact-grid">
      ${fact("Policyholder", `${p.policyholder_name || ""} (${p.policyholder_id || ""})`)}
      ${fact("Policy number", c.policy_number)}
      ${fact("VIN on file", p.vin)}
      ${fact("Collision / comprehensive", `${cov.collision ? "Yes" : "No"} / ${cov.comprehensive ? "Yes" : "No"}`)}
      ${fact("Deductible", money(cov.deductible))}
      ${fact("Coverage limit", money(cov.limits))}
      ${fact("Effective — expiration", `${p.effective_date || ""} — ${p.expiration_date || ""}`)}
      ${fact("Exclusions", (p.exclusions || []).join(", "))}
      ${fact("Listed drivers", (p.listed_drivers || []).join(", "))}
    </div>
  </div>`;
}

function photoGallery(claimId, photoRefs) {
  if (!photoRefs || !photoRefs.length) return "";
  const thumbs = photoRefs
    .map((_, i) => {
      const src = `/api/claims/${encodeURIComponent(claimId)}/photos/${i}`;
      return `<a href="${src}" target="_blank" rel="noopener"><img class="photo-thumb" src="${src}" alt="Damage photo ${i + 1}"></a>`;
    })
    .join("");
  return `<div class="photo-gallery">${thumbs}</div>`;
}

function evidenceSection(c) {
  const e = c.evidence;
  if (!e) return "";
  const lowConsistency = e.consistency_score !== undefined && e.consistency_score < CONSISTENCY_THRESHOLD;
  return `
  <div class="card section">
    <h2>Evidence</h2>
    ${e.customer_damage_description ? `<p><strong>Customer's own description:</strong> ${escapeHtml(e.customer_damage_description)}</p>` : ""}
    ${photoGallery(c.claim_id, e.photo_refs)}
    <div class="fact-grid">
      ${fact("Photo notes (model's independent read)", (e.photo_descriptions || []).join("; "))}
      ${fact(
        "VIN as reported",
        e.vin
      )}${e.vin_match === false ? '<span class="badge-danger">VIN mismatch</span>' : ""}
      ${fact("Consistency score", pct(e.consistency_score))}${lowConsistency ? `<span class="badge-warn">${escapeHtml(e.consistency_note || "inconsistent")}</span>` : ""}
    </div>
  </div>`;
}

function coverageSection(c) {
  const cov = c.coverage_result || {};
  const lowConfidence = cov.coverage_confidence !== undefined && cov.coverage_confidence < EXCLUSION_CONFIDENCE_THRESHOLD;
  return `
  <div class="card section">
    <h2>Coverage result</h2>
    <p><strong>${escapeHtml((cov.status || "").toUpperCase())}</strong> — ${escapeHtml(cov.reason)}</p>
    <div class="fact-grid">
      ${fact("Deductible", money(cov.deductible))}
      ${cov.coverage_confidence !== undefined ? fact("Exclusion-assessment confidence", pct(cov.coverage_confidence)) : ""}
    </div>
    ${lowConfidence ? `<p class="badge-warn">Assessment inconclusive — confidence below the 50% preponderance threshold</p>` : ""}
  </div>`;
}

function riskSection(c) {
  if (!c.risk_result) {
    return `
    <div class="card section">
      <h2>Risk &amp; cost</h2>
      <p>Not assessed: this claim's coverage was denied at intake (${escapeHtml((c.coverage_result || {}).reason)}). Risk history and cost estimation are skipped for a loss already outside the policy's terms.</p>
    </div>`;
  }
  const r = c.risk_result;
  const flagged = r.risk_flag !== "clean";
  return `
  <div class="card section">
    <h2>Risk result</h2>
    <p>${flagged ? '<span class="badge-danger">Needs closer look</span>' : '<span class="badge-warn" style="background:var(--low-bg);color:var(--low)">Clean</span>'} ${escapeHtml(r.reason)}</p>
  </div>`;
}

function costSection(c) {
  const cost = c.cost_estimate;
  if (!cost) return "";
  const rows = Object.entries(cost.part_provenance || {})
    .map(([part, info]) => {
      const price =
        info.estimated_cost_low !== undefined
          ? `${money(info.estimated_cost_low)} – ${money(info.estimated_cost_high)}`
          : "not priced";
      return `<tr><td>${escapeHtml(part)}</td><td>${escapeHtml(info.provenance)}</td><td>${pct(info.score)}</td><td>${price}</td></tr>`;
    })
    .join("");
  return `
  <div class="card section">
    <h2>Cost estimate</h2>
    <div class="fact-grid">
      ${fact("Estimated range", `${money(cost.estimated_cost_low)} – ${money(cost.estimated_cost_high)}`)}
      ${fact("Insurable amount", money(cost.insurable_amount))}${cost.exceeds_limit ? `<span class="badge-danger">exceeds policy limit (${money(cost.policy_limit)})</span>` : ""}
      ${fact("Unknown parts", (cost.unknown_parts || []).join(", ") || "none")}
    </div>
    <table class="parts-table">
      <thead><tr><th>Part</th><th>Provenance</th><th>Confidence</th><th>Est. cost</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function prioritySection(c) {
  const p = c.priority_result || {};
  return `
  <div class="card section">
    <h2>Priority</h2>
    <p>${priorityPill(p.priority)} ${escapeHtml(p.reason)}</p>
  </div>`;
}

function recommendationSection(c) {
  const rec = c.recommendation;
  if (!rec) return "";
  return `
  <div class="section">
    <div class="suggestion-card">
      <span class="suggestion-label">System suggestion (not a decision)</span>
      <strong>${escapeHtml((rec.recommended_action || "").replace("_", " "))}</strong>
      ${rec.recommended_amount !== null && rec.recommended_amount !== undefined ? ` — ${money(rec.recommended_amount)}` : ""}
      <div>${escapeHtml(rec.reason)}</div>
    </div>
  </div>`;
}

function decisionSection(c) {
  if (c.is_auto_approved) {
    return `<div class="card section"><h2>Decision</h2><p>Auto-approved by the system — no adjuster action needed (see the priority/recommendation above).</p></div>`;
  }
  if (c.is_auto_denied) {
    return `<div class="card section"><h2>Decision</h2><p>Auto-denied by the system — a hard fraud signal fired (see the risk result above). No adjuster action needed; this was never queued for review.</p></div>`;
  }
  if (c.is_resolved) {
    return `<div class="card section"><h2>Decision</h2><p>This claim has already been resolved. See <a href="history.html">Resolved</a> for the recorded outcome.</p></div>`;
  }
  const cost = c.cost_estimate;
  const rec = c.recommendation || {};
  const prefill =
    rec.recommended_action === "approve" && rec.recommended_amount !== null
      ? rec.recommended_amount
      : cost
      ? (cost.estimated_cost_low + cost.estimated_cost_high) / 2
      : "";
  return `
  <div class="card section">
    <h2>Decision</h2>
    <div class="decision-form">
      <div class="action-toggle">
        <button type="button" id="btnApprove" class="approve">Approve</button>
        <button type="button" id="btnDeny" class="deny">Deny</button>
      </div>
      <div id="amountField" style="display:none">
        <label for="amount">Approved amount</label>
        <input type="number" id="amount" step="0.01" value="${prefill}" />
      </div>
      <div>
        <label for="reason" id="reasonLabel">Notes</label>
        <textarea id="reason" placeholder="Optional notes"></textarea>
      </div>
      <div>
        <button type="button" id="submitBtn" class="primary" disabled>Submit decision</button>
      </div>
    </div>
  </div>`;
}

function wireDecisionForm() {
  const approveBtn = document.getElementById("btnApprove");
  const denyBtn = document.getElementById("btnDeny");
  if (!approveBtn) return;
  const amountField = document.getElementById("amountField");
  const reasonLabel = document.getElementById("reasonLabel");
  const reasonEl = document.getElementById("reason");
  const submitBtn = document.getElementById("submitBtn");

  function selectAction(action) {
    selectedAction = action;
    approveBtn.classList.toggle("selected", action === "approve");
    denyBtn.classList.toggle("selected", action === "deny");
    amountField.style.display = action === "approve" ? "block" : "none";
    reasonLabel.textContent = action === "deny" ? "Reason (required)" : "Notes";
    submitBtn.disabled = false;
  }

  approveBtn.addEventListener("click", () => selectAction("approve"));
  denyBtn.addEventListener("click", () => selectAction("deny"));

  submitBtn.addEventListener("click", () => {
    if (selectedAction === "deny" && !reasonEl.value.trim()) {
      alert("A reason is required to deny a claim.");
      return;
    }
    const amount = selectedAction === "approve" ? parseFloat(document.getElementById("amount").value) : null;
    confirmAndSubmit(selectedAction, amount, reasonEl.value.trim());
  });
}

function confirmAndSubmit(action, amount, reason) {
  const summary =
    action === "approve"
      ? `approve this claim for ${money(amount)}`
      : "deny this claim";
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <p>You're about to <strong>${summary}</strong> — confirm?</p>
      <div class="actions">
        <button id="cancelModal">Cancel</button>
        <button id="confirmModal" class="${action === "approve" ? "primary" : "danger"}">Confirm</button>
      </div>
    </div>`;
  document.body.appendChild(backdrop);
  backdrop.querySelector("#cancelModal").addEventListener("click", () => backdrop.remove());
  backdrop.querySelector("#confirmModal").addEventListener("click", async () => {
    backdrop.remove();
    try {
      await apiPost(`/api/claims/${encodeURIComponent(claimId)}/decision`, { action, amount, reason });
      location.href = "history.html";
    } catch (e) {
      alert(`Could not submit decision: ${e.message}`);
      load();
    }
  });
}

load();
