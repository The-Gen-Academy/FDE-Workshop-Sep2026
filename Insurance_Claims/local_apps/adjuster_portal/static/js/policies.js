const rowsEl = document.getElementById("rows");
const formErrorEl = document.getElementById("formError");

function renderPolicies(items) {
  if (items.length === 0) {
    rowsEl.innerHTML = `<div class="empty-state"><div>No policies yet.</div></div>`;
    return;
  }
  rowsEl.innerHTML = items
    .map((p) => {
      const cov = p.coverage || {};
      return `
      <div class="claim-row">
        <div class="row-top">
          <div class="left">
            <span class="claim-id">${escapeHtml(p.policy_number)}</span>
            <span class="meta">${escapeHtml(p.policyholder_name)} (${escapeHtml(p.policyholder_id)})</span>
          </div>
        </div>
        <div class="fact-grid">
          <div class="fact"><span class="label">VIN</span><span class="value">${escapeHtml(p.vin)}</span></div>
          <div class="fact"><span class="label">Listed drivers</span><span class="value">${escapeHtml((p.listed_drivers || []).join(", "))}</span></div>
          <div class="fact"><span class="label">Collision / comprehensive</span><span class="value">${cov.collision ? "Yes" : "No"} / ${cov.comprehensive ? "Yes" : "No"}</span></div>
          <div class="fact"><span class="label">Deductible</span><span class="value">${money(cov.deductible)}</span></div>
          <div class="fact"><span class="label">Coverage limit</span><span class="value">${money(cov.limits)}</span></div>
          <div class="fact"><span class="label">Effective — expiration</span><span class="value">${escapeHtml(p.effective_date)} — ${escapeHtml(p.expiration_date)}</span></div>
          <div class="fact"><span class="label">Exclusions</span><span class="value">${escapeHtml((p.exclusions || []).join(", "))}</span></div>
        </div>
      </div>`;
    })
    .join("");
}

async function loadPolicies() {
  const items = await apiGet("/api/policies");
  renderPolicies(items);
}

function showFormError(message) {
  formErrorEl.textContent = message;
  formErrorEl.style.display = "inline-block";
}

function clearFormError() {
  formErrorEl.style.display = "none";
}

document.getElementById("createBtn").addEventListener("click", async () => {
  clearFormError();
  const listedDrivers = document
    .getElementById("listedDrivers")
    .value.split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const exclusions = Array.from(document.querySelectorAll(".exclusion:checked")).map((el) => el.value);

  const body = {
    policyholder_name: document.getElementById("policyholderName").value.trim(),
    vin: document.getElementById("vin").value.trim(),
    listed_drivers: listedDrivers,
    collision: document.getElementById("collision").checked,
    comprehensive: document.getElementById("comprehensive").checked,
    deductible: parseFloat(document.getElementById("deductible").value),
    limits: parseFloat(document.getElementById("limits").value),
    effective_date: document.getElementById("effectiveDate").value,
    expiration_date: document.getElementById("expirationDate").value,
    exclusions,
  };

  if (!body.effective_date || !body.expiration_date) {
    showFormError("Effective and expiration dates are required.");
    return;
  }

  try {
    const created = await apiPost("/api/policies", body);
    alert(`Policy created: ${created.policy_number} (policyholder ID ${created.policyholder_id})`);
    document.getElementById("policyholderName").value = "";
    document.getElementById("vin").value = "";
    document.getElementById("listedDrivers").value = "";
    await loadPolicies();
  } catch (e) {
    showFormError(e.message);
  }
});

loadPolicies();
if (localStorage.getItem("claims_demo_role") !== "adjuster") {
  location.href = "index.html";
}
