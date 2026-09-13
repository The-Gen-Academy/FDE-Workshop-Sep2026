const sessionId = localStorage.getItem("claims_session_id");
if (localStorage.getItem("claims_demo_role") !== "client" || !sessionId) {
  location.href = "index.html";
}

const messagesEl = document.getElementById("messages");
const claimChipEl = document.getElementById("claimChip");
const errorBannerEl = document.getElementById("errorBanner");
const outcomeEl = document.getElementById("outcome");
const composerEl = document.getElementById("composer");
const textInputEl = document.getElementById("textInput");
const sendBtnEl = document.getElementById("sendBtn");
const photoRowEl = document.getElementById("photoRow");
const photoInputEl = document.getElementById("photoInput");
const addPhotoBtnEl = document.getElementById("addPhotoBtn");
const photoHintEl = document.getElementById("photoHint");

let pendingPhotos = []; // [{file, url}]
let awaiting = false;

function renderClaimChip(claimId) {
  claimChipEl.innerHTML = claimId
    ? `<div class="claim-chip">📋 Claim ${escapeHtml(claimId)}</div>`
    : "";
}

function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setLoading(show, text) {
  let row = document.getElementById("loadingRow");
  if (show) {
    if (!row) {
      row = document.createElement("div");
      row.id = "loadingRow";
      row.className = "loading-row";
      messagesEl.appendChild(row);
    }
    row.innerHTML = `<span class="spinner"></span><span>${escapeHtml(text)}</span>`;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  } else if (row) {
    row.remove();
  }
}

function renderPhotoThumbs() {
  photoRowEl.querySelectorAll(".thumb-wrap").forEach((el) => el.remove());
  pendingPhotos.forEach((p, i) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb-wrap";
    wrap.innerHTML = `<img class="thumb" src="${p.url}" /><button type="button" class="thumb-remove" data-i="${i}">×</button>`;
    photoRowEl.insertBefore(wrap, addPhotoBtnEl);
  });
  photoRowEl.querySelectorAll(".thumb-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      pendingPhotos.splice(parseInt(btn.dataset.i, 10), 1);
      renderPhotoThumbs();
    });
  });
}

addPhotoBtnEl.addEventListener("click", () => photoInputEl.click());
photoInputEl.addEventListener("change", () => {
  for (const file of photoInputEl.files) {
    pendingPhotos.push({ file, url: URL.createObjectURL(file) });
  }
  photoInputEl.value = "";
  renderPhotoThumbs();
});

function renderOutcome(outcome) {
  if (!outcome) return;
  if (outcome.auto_approved) {
    outcomeEl.innerHTML = `
      <div class="outcome-card approved">
        <div class="big-icon">✅</div>
        <h2>Your claim is approved</h2>
        <div class="amount">${money(outcome.approved_amount)}</div>
        <p>Deductible applied: ${money(outcome.deductible)}</p>
        <p>Next, you'll pick a repair shop — we'll follow up with payment timing details.</p>
      </div>`;
  } else if (outcome.auto_denied) {
    outcomeEl.innerHTML = `
      <div class="outcome-card denied">
        <div class="big-icon">✕</div>
        <h2>Your claim was denied</h2>
        <p>${escapeHtml(outcome.denial_reason || "")}</p>
        <p>If you believe this isn't right, please contact our support team to have it looked at — reference claim ${escapeHtml(outcome.claim_id || "")}.</p>
      </div>`;
  } else {
    outcomeEl.innerHTML = `
      <div class="outcome-card">
        <div class="big-icon">📨</div>
        <h2>Your claim is under review</h2>
        <p>A claims adjuster will review the details you've provided. We'll let you know what happens next.</p>
      </div>`;
  }
  awaiting = true; // conversation is complete; keep the composer disabled
  updateComposerState();
}

function updateComposerState() {
  textInputEl.disabled = awaiting;
  sendBtnEl.disabled = awaiting;
  addPhotoBtnEl.disabled = awaiting;
}

function showError(message) {
  errorBannerEl.innerHTML = message ? `<div class="error-banner">${escapeHtml(message)}</div>` : "";
}

async function loadHistory() {
  try {
    const state = await apiGet(`/api/session/${sessionId}/history`);
    renderClaimChip(state.claim_id);
    for (const turn of state.transcript || []) {
      if (turn.role === "customer" && turn.text) addBubble("customer", turn.text);
      else if (turn.role === "assistant" && turn.text) addBubble("assistant", turn.text);
    }
    if (state.outcome) renderOutcome(state.outcome);
  } catch (e) {
    // Session unknown to this (possibly restarted) backend process.
    localStorage.removeItem("claims_session_id");
    document.querySelector(".page").innerHTML = `
      <div class="brand">Meridian Auto Insurance</div>
      <h1>Your session expired</h1>
      <p class="subtitle">Sorry about that — please start your claim again.</p>
      <button class="primary" onclick="location.href='index.html'">Start again</button>`;
  }
}

async function sendMessage() {
  const text = textInputEl.value.trim();
  if (!text && pendingPhotos.length === 0) return;

  const hadPhotos = pendingPhotos.length > 0;
  if (text) addBubble("customer", text);
  textInputEl.value = "";
  resizeTextInput();
  showError("");

  awaiting = true;
  updateComposerState();
  setLoading(true, hadPhotos ? "Reviewing your policy and estimating next steps…" : "Thinking…");

  const form = new FormData();
  form.append("text", text);
  for (const p of pendingPhotos) form.append("images", p.file);
  pendingPhotos = [];
  renderPhotoThumbs();

  try {
    const result = await apiPostForm(`/api/session/${sessionId}/message`, form);
    setLoading(false);

    if (result.rate_limited) {
      showError("The claims assistant is busy right now — please try again in a moment.");
      awaiting = false;
      updateComposerState();
      return;
    }

    if (result.claim_id) renderClaimChip(result.claim_id);
    if (result.reply_text) addBubble("assistant", result.reply_text);
    if (result.needs_more_photos) {
      photoHintEl.textContent = result.needs_more_photos;
      photoHintEl.classList.add("warn");
    }
    if (result.outcome) {
      renderOutcome(result.outcome);
      return; // renderOutcome already disabled the composer
    }
    awaiting = false;
    updateComposerState();
    textInputEl.focus();
  } catch (e) {
    setLoading(false);
    showError("Something went wrong reaching the claims assistant. Please try again.");
    awaiting = false;
    updateComposerState();
  }
}

function resizeTextInput() {
  textInputEl.style.height = "auto";
  textInputEl.style.height = `${textInputEl.scrollHeight}px`;
}

sendBtnEl.addEventListener("click", sendMessage);
textInputEl.addEventListener("input", resizeTextInput);
textInputEl.addEventListener("keydown", (e) => {
  // isComposing/keyCode 229 guards against sending mid-IME-composition
  // (e.g. typing Japanese/Chinese and pressing Enter to confirm a candidate).
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    sendMessage();
  }
});

loadHistory();
