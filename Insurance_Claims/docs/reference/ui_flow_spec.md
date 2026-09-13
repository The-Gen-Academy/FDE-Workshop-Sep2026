# UI Flow Specification — Auto Claims Intake

> Historical design reference. The portals now exist, package paths and storage
> have changed, and some implementation notes below are obsolete. Use the
> current [architecture](../architecture.md) and [portal README](../../local_apps/README.md).
> The original screen and field specifications are retained below.

This document is a detailed handoff for the UI team: every screen, state, and
data field involved in the two user-facing surfaces of this system — the
**client portal** (the customer filing a claim) and the **adjuster portal**
(the human reviewing it). It's written against what's actually built today
(the ADK agent in `insurance_claim_agent/` and its local-file backend), not a
generic claims-UI template, so every field name below is real and should be
wired to the real data shape, not reinvented.

Neither portal exists yet — this is the spec to build them from. The agent
itself has been built and verified; these UIs are what would sit in front of
and behind it.

---

## 1. System context (read this before the screens)

The system is one orchestrator agent (`root_agent`) that delegates to three
sub-agents in a fixed order:

1. **`intake_agent`** (chats with the customer) — collects incident details,
   looks up their policy, collects damage evidence.
2. **`assessment_agent`** (no chat, runs once) — checks coverage, then
   checks claim history for risk signals and estimates repair cost *unless*
   coverage came back `not_covered`, in which case it stops right there
   (`claims_handling_policy.md` §2.2) and those two never run.
3. **`escalation_agent`** (no chat, runs once) — classifies a priority
   (`low` / `medium` / `high`) and drafts a recommendation (`approve` /
   `deny` / `needs_manual_review`, plus an amount if approving). For most
   `medium`/`high` claims, that recommendation is purely an advisory
   starting point for a human adjuster, and the claim is written into the
   `escalations` collection with status `pending_review`, where it waits.
   Two specific cases are executed directly instead, no adjuster involved:
   for `low` priority, the agent executes the `approve` recommendation
   itself; for a claim flagged by a "hard" fraud signal from `check_claim_history`
   (claim frequency, a too-new policy, or VIN reuse — never the softer
   description-vs-photo consistency signal, and never a coverage-driven
   `not_covered` denial, which always stays adjuster-only), it executes a
   `deny` recommendation the same way. Both write the same `escalations`
   collection with status `auto_approved`/`auto_denied` instead of
   `pending_review`, plus a permanent `claims_log` record either way, for
   audit purposes (`claims_handling_policy.md` §6, §6.2).

Four rules that must shape every screen described below:

- **Only "low" priority claims are auto-approved, and only hard-fraud-signal
  claims are auto-denied.** Every other claim ends up in the adjuster's
  queue, and for those the client portal must never imply approval or
  denial — only "your claim is being reviewed." For an auto-approved or
  auto-denied claim, by contrast, the client portal states the real outcome
  directly — see §2.4.
- **The recommendation is adjuster-only, except when it was executed.** The
  `recommendation` field (§3.3) is a system-computed starting point for a
  human adjuster on a `pending_review` claim — never a preliminary answer
  for the customer, and it must never appear anywhere in the client portal
  for those claims, in any form (not the action, not the amount). For an
  `auto_approved`/`auto_denied` claim, this same field *is* the real
  outcome, and the client portal shows it as the claim's actual approved
  amount or denial reason (§2.4).
- **An auto-denial always comes with a way to dispute it.** Unlike a
  `pending_review` claim (which a human will eventually look at regardless),
  an auto-denied claim has never been seen by anyone — the client portal
  must always pair the denial with a concrete path to contact support,
  never present it as a closed door.
- **Image analysis is real, but scoped narrowly.** Gemini looks at attached
  photos itself and forms an independent read of the damage — but that read
  only ever feeds two things: the same `damaged_parts` inference the agent
  already had to make from text (now grounded in an actual image instead of
  guessing from the customer's words), and a description-vs-photo
  consistency check that's purely a risk/fraud signal for a human adjuster
  (`check_claim_history`, step 5). It is never used to state a coverage or
  approval outcome to the customer, and it isn't a precise damage-severity
  or cost-estimation instrument — see the model's own reasoning in
  `record_damage_evidence`'s docstring for the exact boundary.

Data currently lives in `local_data/`, as six local JSON files (one file
per collection, each holding a dict of document_id -> fields — see
README.md's "Local data storage" section). **This is a mock/demo stand-in,
not something either portal should be built against as a real backend**:
a local file on the agent's own machine has no remote API for a
separately-hosted portal backend to call, so the field/shape descriptions
below (which will carry over to whatever real datastore replaces this) are
what matters here, not the storage mechanism itself:

| File | Shape | Who writes it |
|---|---|---|
| `policies.json` (keyed by policy_number) | policy record (reference data) | nobody, from the UI's perspective — managed by ops directly in the local file |
| `claim_history.json` (keyed by policyholder_id) | `{"claims": [...]}` | same — reference data |
| `parts_pricing.json` (keyed by part_key) | `{"part_cost": ..., "labor_hours": ...}` | same — reference data |
| `vin_claims.json` (keyed by vin) | `{"claims": [{"claim_id","policyholder_id","date"}, ...]}` | the agent (`record_damage_evidence`) — a fraud signal, lets the system see a VIN reused across *different* policyholders |
| `escalations.json` (keyed by claim_id) | the adjuster queue entry (full shape below) | the agent (`package_for_adjuster`) always; then the adjuster portal's backend on decision — except an `auto_approved`/`auto_denied` entry, which the agent alone ever writes |
| `claims_log.json` (keyed by claim_id) | permanent audit record | the adjuster portal's backend, once a human decision is made — or the agent itself (`package_for_adjuster`), for an `auto_approved`/`auto_denied` claim |

No GCS bucket, no photo storage, and no deployment exist yet either — both
portals below are being spec'd against an agent that currently only runs
locally (`adk web` / `adk run`). Treat the "how does the client portal talk
to the agent" and "where do photos go" questions as open infrastructure
work, called out inline below where relevant.

---

## 2. Client Portal

Audience: the policyholder, on a phone or in a browser, usually not long
after a stressful event (an accident). Every copy decision should assume the
person is anxious and possibly not thinking clearly — short sentences, no
jargon, no dead ends.

### 2.1 Entry / landing screen

Purpose: get the customer into a conversation as fast as possible. This is
not a marketing page — assume the customer arrived here specifically to
file a claim (from an app, a link in a text, or a "File a Claim" button
elsewhere in an existing insurer app/site).

Contents:
- A single, unambiguous primary action: **"Start a claim"** (or **"Continue
  my claim"** if a session/claim ID is detected — see 2.7).
- One reassuring line of copy: something like "This takes about 10 minutes.
  We'll ask about what happened, your policy, and any photos you have."
  Setting a time expectation matters — it reduces anxiety and abandonment.
- A secondary, lower-emphasis link: "Check the status of a claim you already
  filed" → goes to the status-check screen (2.6).
- **Auth model (decided): the policyholder logs in with their own account
  credentials — that's the only identity in the client portal.** There is
  no separate identity for other listed drivers; if someone other than the
  policyholder was driving, the policyholder is still the one who logs in
  and files the claim, giving the driver's name as a piece of information
  within the claim (`driver_name`), not as a second account. This means the
  landing screen sits behind the insurer's normal login — "Start a claim"
  is the first thing an already-authenticated policyholder sees, not a
  public entry point.
- Since the policyholder is already authenticated, their policy number is
  already known from their account — the portal should pass it straight
  into `identify_policy` automatically rather than asking for it again in
  the conversation (see 2.2, sub-phase B, updated accordingly). If a
  policyholder has more than one policy, a lightweight "which policy is
  this claim for" picker belongs here, before the conversation starts.

### 2.2 Conversational intake screen

This is the heart of the client portal and wraps `intake_agent` — steps 1
through 3 of the underlying flow. Structurally, this should be a chat
interface (message bubbles, customer on one side, agent on the other), not a
traditional multi-page form — the agent is asking questions conversationally
and the UI should match that, but the UI can still use structured input
controls *within* the chat for specific data points rather than making the
customer type everything as free text (see below).

**Sub-phase A — Incident details (maps to `start_claim_intake`)**

The agent will ask for, in whatever order feels natural in conversation:
- Date and time of the incident
- Location (free text)
- A free-text description of what happened
- Who was driving at the time (by name) — used later to check against the
  policy's listed drivers; often the policyholder themselves, but the UI
  should not assume that and should ask explicitly
- Whether the car is currently drivable (yes/no)
- Whether anyone was injured (yes/no)
- Whether another party was involved, and if so their info
- Whether a police report was filed (yes/no)

UI recommendation: even though this is conversational, render yes/no
questions as tappable chips/buttons inline in the chat (not just "type yes
or no") — faster for the customer, and removes ambiguity in what gets sent
to the agent. Free-text fields (description, location, other-party info)
get a normal text input. Date/time can use a native date/time picker
component invoked inline rather than asking the customer to type
"2026-07-10" — feed the picker's ISO output to the conversation.

Once all of this is collected, the agent calls `start_claim_intake`, which
generates a `claim_id` (format `CLM-XXXXXXXX`). **Surface this claim ID to
the customer as soon as it exists** — e.g. a small persistent chip at the
top of the screen: "Claim CLM-4F88A21C". This is the ID they'd use on the
status-check screen later, and displaying it early builds confidence that
something durable has happened, not just a chat that could vanish.

**Sub-phase B — Policy identification (maps to `identify_policy`)**

Given the policyholder-only auth model (2.1), this sub-phase is normally
*silent* rather than conversational: the portal already knows which policy
number to use from the logged-in account (or from the picker in 2.1, if
they hold more than one policy), and calls `identify_policy` automatically
as soon as the conversation starts — the customer is never asked to type or
recite a policy number they've already effectively provided by logging in.

- **Loading state**: while `identify_policy` runs, show a brief inline
  "Looking up your policy…" indicator in the chat (today this is a local
  file read — fast in practice, but always show *something* rather than a
  silent pause, since a real backend swapped in later, per README.md's
  "Swapping in real backends," could be slower).
- **Not-found state**: this should be rare, since the account should only
  ever hand over a policy number that exists — treat a not-found result
  here as a real account/data inconsistency (surface a "something's not
  right with your account, please contact support" state), not as a typo
  the customer needs to correct. This differs from the original design,
  where the customer typed the number themselves and a typo was the
  expected failure mode.

**Sub-phase C — Damage evidence (maps to `record_damage_evidence`)**

The agent asks for:
- 2-5 photos of the damage — **required, not optional**. `record_damage_evidence`
  itself rejects fewer than 2 (returns an error the agent is instructed to
  recover from by asking for more), so the UI should mirror that as a hard
  submission block, not just a soft nudge, to avoid a round-trip failure.
- VIN — always typed/spoken by the customer (they can read it off their own
  photo or registration/dashboard if they need to), never something the
  agent extracts from the image itself

This is the one part of the flow needing a real upload widget, not just
chat bubbles:

- **Photo upload control**: a standard multi-file picker, camera-capture
  option on mobile (so the customer can take photos in the moment rather
  than needing pre-existing ones), thumbnail previews with a remove (×)
  option per photo. Disable/block the submit action below 2 photos (hard
  minimum, matching the tool's own enforcement); above 5, just nudge rather
  than hard-block. Accept common image types (JPEG/PNG/HEIC/WebP).
  **Important open infrastructure gap**: there is currently no GCS bucket
  or upload endpoint built for this. The recommended architecture (designed
  earlier, not yet built): the client portal's own backend uploads each
  photo directly to a GCS bucket as soon as it's selected (not waiting for
  the whole form to submit) — that's still the durable copy an adjuster
  views later. What's different now that image analysis is in scope: the
  agent also needs the actual image content, not just a text file
  reference. On Vertex AI, Gemini can take a `gs://...` URI directly as
  multimodal input, so the same uploaded object doubles as both the
  adjuster's durable copy and the agent's visual input — no separate
  "send bytes to the agent" path needed. Show per-photo upload progress and
  success/failure state in the thumbnail itself (a small spinner →
  checkmark, or a retry icon on failure).
- The agent looks at each photo itself and forms its own read of the
  damage — it does not just repeat back whatever the customer types. The
  customer's own incident description (from sub-phase A) is what gets
  compared against that independent read for the consistency check (see
  the system-context note above); the UI doesn't need a separate
  per-photo caption field for this to work, since the comparison happens
  against the incident description already collected, not per-photo text.
- VIN: text input, 17 characters, consider a format hint/validation mask
  (VINs exclude the letters I, O, Q) — but don't hard-block submission on
  client-side VIN validation being imperfect; let the agent/backend be the
  source of truth.

### 2.3 "Assessing your claim" transitional screen

Once intake finishes, `assessment_agent` and `escalation_agent` run in
sequence with no customer interaction — this is real processing time (a
few tool calls plus two LLM turns), likely 2-6 seconds, not instant.

Do not leave the customer looking at a static last chat bubble during this
gap. Show a distinct, honest transitional state:
- A short, calm message: "Reviewing your policy and estimating next
  steps…" — avoid words like "analyzing" or "processing your data" that
  sound more automated/cold than the tone elsewhere.
- A simple indeterminate progress indicator (this is not a long enough
  wait to justify a multi-step progress bar with labeled stages — that
  would overstate how long this takes and invite the customer to wonder
  why "step 2 of 5" is taking so long).
- No cancel button here — this phase is short and mid-flight cancellation
  isn't a meaningfully supported concept in the current design.

### 2.4 Outcome confirmation screen

This is what the customer sees once `package_for_adjuster` has run. It
branches on `status` — this is the one screen in the client portal that is
allowed to state a real outcome, for the `auto_approved` and `auto_denied`
branches.

**Branch A — `status: "auto_approved"` (a "low" priority claim, §6):**
This is a real, final outcome — style it accordingly (a genuine confirmation
state, not a muted "received" state). Contents:
- A clear statement that the claim is approved, with the claim ID.
- The approved amount (`approved_amount`) and the deductible
  (`deductible`) that was applied, stated plainly — this is not a
  recommendation or an estimate at this point, it's the actual amount.
- Calm next-steps copy: picking a repair shop, payment timing (exact
  mechanics are an open gap — see 4.5 — but the copy should not overpromise
  a specific timeline the backend can't guarantee).
- The same `claimed_only` transparency note as Branch B below, if
  applicable.

**Branch B — `status: "pending_review"` (every other non-fraud-flagged claim):**
This screen must never state or imply an approval/denial outcome — that
instruction is baked into the agent itself, and the UI must not undo it
with confident-sounding copy or iconography (no green checkmarks that read
as "approved," no "Success!" framing). Contents:
- Confirmation that the claim was received, with the claim ID prominent
  and easy to copy/screenshot.
- A plain-language summary of what was collected (incident date, policy
  number, a one-line damage summary) — letting the customer visually
  confirm nothing was mis-transcribed.
- Clear, calm next-steps copy: something like "A claims adjuster will
  review the details you've provided. We'll let you know what happens
  next." Do **not** state the priority level, an expected turnaround time
  the system can't actually guarantee, or anything about coverage status —
  the agent's own instruction explicitly avoids stating priority bluntly or
  implying a guaranteed timeline, and the UI shouldn't contradict that by
  inventing a promise the backend can't keep.
- A way to return later: either an account/dashboard link, or explicit
  instructions to use the claim ID on the status-check screen (2.6).

**Branch C — `status: "auto_denied"` (a hard-fraud-signal claim, §6.2):**
Also a real, final outcome — but a harsher one, delivered with no adjuster
ever having looked at it. Contents:
- A clear, calm statement that the claim was denied — factual, never
  punitive or accusatory framing; this is a statement of outcome, not a
  judgment of the customer.
- The reason (`denial_reason`), in the same plain language the agent used —
  don't invent additional justification beyond what the backend gave.
- A prominent, concrete way to contact support and dispute the decision —
  this is not optional on this branch. Unlike Branch B, nobody will
  eventually look at this claim on their own; if the customer doesn't act,
  nothing further happens. Never present this as a closed door.
- The claim ID, for reference when they do contact support.

**All three branches:** if `cost_estimate.part_provenance` has anything
tagged `claimed_only` (damage the customer mentioned that wasn't visible in
their photos — see 3.3), say so here in plain language and neutrally:
something like "you also mentioned [X]; since we couldn't confirm that from
what you sent, we've noted it for the adjuster to take a closer look at"
(Branch B) or "...we've noted it in your claim record" (Branches A and C,
since there's no adjuster to look at it). Always pair this with
confirmation that it's still part of the claim, not dropped — this is a
transparency note, not a challenge to the customer. Branch C's
`cost_estimate` is never `null`, unlike Branch B's `not_covered` case
(§2.2/§3.3) — a hard fraud signal can only ever fire after
`check_claim_history` has actually run, which itself only happens when
coverage wasn't already `not_covered`, so steps 5 and 6 both always
completed before a claim reaches this branch.

### 2.5 Error / edge states (apply throughout 2.2–2.4)

These need real designs, not just "an error occurred":

- **Policy not found** after repeated attempts: offer an escape hatch —
  a link/button to contact support directly, rather than trapping the
  customer in a retry loop indefinitely.
- **Agent/backend unavailable** (the conversation can't get a response):
  a distinct "something went wrong on our end, please try again in a
  moment" state, distinguishable from "we didn't understand your last
  message." Preserve whatever was already collected — don't make the
  customer re-enter incident details because of a transient failure.
- **Photo upload failure**: per-photo retry, not a whole-form failure.
  The customer shouldn't lose photos 1 and 2 because photo 3 failed to
  upload.
- **Session interrupted mid-intake** (customer closes the tab, loses
  connection): on return, resume from wherever they left off rather than
  restarting — this requires the portal to persist a session/claim
  reference client-side (e.g. in the URL or local storage) tied to
  whatever conversation/session ID the backend issued.

### 2.6 Status-check / return-visit screen

**This is an open design gap** — there is currently no mechanism in the
agent for a customer to check on their claim's outcome after the fact, and
no notification system (email/SMS) has been decided either. The
recommended shape, to build the UI against:

- A simple form: claim ID (+ possibly policy number, as a lightweight
  second factor) → looks up the claim's current status.
- Status should be presented as one of a small number of plain-language
  states, not the raw internal ones: "Under review" (maps to
  `escalations.status == "pending_review"`), and a resolved state showing
  the outcome (maps to `escalations.status == "resolved"` /
  `claims_log`'s `final_decision`).
- If/when a notification system is built, this screen becomes less
  load-bearing (customers get told proactively) but should still exist as
  a fallback.

### 2.7 Returning customer / "continue my claim"

If a customer starts the portal again with an in-progress conversation
still active (same browser session, or a saved claim ID), route them back
into the conversation at whatever point they left off, rather than the
landing screen defaulting to "Start a claim" and risking a duplicate.

---

## 3. Adjuster Portal

Audience: an internal claims adjuster, at a desk, working through a queue
as part of their job — this is a professional tool, not a consumer-friendly
surface. Optimize for density, speed, and scanability over the warmth
appropriate to the client portal. This is a dashboard, not a document: it
gets *scanned and operated*, not read top to bottom.

### 3.1 Auth / login

**Open gap**: no adjuster identity model exists anywhere in the system
today — there's no `adjuster_id`, no roles, nothing. This needs to be
designed as part of building this portal (standard authenticated
internal-tool login, likely tied into whatever identity system the
insurer already uses for staff). Not detailed further here since it's pure
infrastructure, not a UI flow question, but flagging it explicitly so it
isn't missed.

### 3.2 Queue view (the main/default screen)

Reads the `escalations.json` file, filtered to
`status == "pending_review"`.

**A "low" priority claim never appears in this queue, and neither does a
hard-fraud-signal claim.** Per `claims_handling_policy.md` §6/§6.2, both are
resolved automatically at intake — their `escalations.json` entries land
with status `auto_approved`/`auto_denied`, not `pending_review`, so they're
filtered out here by construction, not by omission. In practice this means
the priority pill in this queue is effectively always medium, or high
*without* a hard fraud signal (e.g. a coverage exclusion, or just a large
cost) — still worth rendering the low case (below) for
completeness/robustness, but don't design around ever routinely seeing it.

Each row/card in the queue should surface, at a glance, without opening the
claim:
- `claim_id`
- Priority (`priority_result.priority` — "low" / "medium" / "high"),
  rendered as a **severity chip/pill with color**, not just text — this is
  exactly the kind of state that should be encoded in form as well as
  words. Suggest: high = red/urgent, medium = amber, low = a neutral/green
  tone. This is a semantic color use, separate from whatever the portal's
  own brand accent color is.
- Policyholder name (`policy.policyholder_name`) and policy number
  (`policy_number`)
- A one-line incident summary (`incident.description`, truncated) and
  `incident.incident_date`
- Estimated cost range (`cost_estimate.estimated_cost_low` –
  `estimated_cost_high`) — **`cost_estimate` can be `null`.** A confirmed
  `not_covered` coverage result fast-tracks the claim straight past risk and
  cost assessment (`claims_handling_policy.md` §2.2), so `risk_result` and
  `cost_estimate` are both genuinely never computed, not just empty. Render
  this as "Not assessed — coverage not covered," not a blank cell or a
  loading spinner (there's nothing pending; it was deliberately skipped).
- `queued_at` — how long it's been waiting (render as relative time, "3h
  ago," not a raw timestamp — adjusters will want to sort by this)

**Sorting/filtering**: default sort should be priority (high first), then
by `queued_at` (oldest first within a priority tier) — the classic triage
pattern. Provide explicit filter controls for priority tier and a text
search over policy number / claim ID / policyholder name. Given real
adjuster teams, also consider a filter for "assigned to me" once/if
per-adjuster assignment is added (not in the current data model — another
gap worth flagging: `escalations` documents currently have no `assigned_to`
field).

**Empty state**: an empty queue is a *good* outcome here (nothing pending)
— don't design the empty state to look like an error. Something calm
confirming "You're caught up."

### 3.3 Claim detail / review screen

This is the single most important screen in either portal — it needs to
present the exact bundle `package_for_adjuster` produces, laid out for fast
human judgment, not just dumped as raw JSON. Full field inventory, grouped
into sections matching the actual data shape:

**Header strip**: `claim_id`, priority pill (same styling as the queue),
`status`, `queued_at`.

**Incident** (from `incident`):
- Date/time, location, free-text description (this should be prominent —
  it's the adjuster's primary read on what happened)
- Driver name — and if it doesn't match anyone in the policy's
  `listed_drivers`, this is already surfaced as the coverage reason below,
  but it's worth repeating here as its own labeled fact too, since it's a
  quick disqualifying check an adjuster will look for first
- Drivable? / Anyone injured? / Other party involved? (+ their info if so)
  / Police report filed? — render these as a compact set of labeled
  yes/no facts, not buried in paragraph text, since an adjuster scanning
  quickly needs to find "was anyone injured" instantly.

**Policy** (from `policy`, plus `policy_number`):
- Policyholder name/ID, VIN on file, coverage types (collision/
  comprehensive), deductible, coverage limit, effective/expiration dates,
  exclusions list, and `listed_drivers` (needed to cross-check against the
  incident's driver name above). This is reference data the adjuster may
  want to sanity-check against what the coverage result below concluded.

**Evidence** (from `evidence`):
- Photo thumbnails — **open gap**: since no photo upload/storage exists
  yet, there's currently nothing to render here beyond text. Once built,
  this section should show actual images (fetched via a signed GCS URL,
  not a public link), full-size on click, alongside each `photo_descriptions`
  caption.
- `consistency_score` and `consistency_note` — this is the fraud signal
  underlying risk-result trigger #4 above, and needs its own visible
  treatment here, not just a mention buried in the risk `reason` text.
  Render `consistency_score` as a percentage, not just a raw decimal — when
  it falls below `CONSISTENCY_SCORE_THRESHOLD` (0.7, `claims_handling_policy.md`
  §4), show a clear warning badge on the evidence section itself (distinct
  from the VIN-mismatch badge below) with `consistency_note`'s text
  alongside it, so the adjuster sees *why* right next to the photos and
  description they're looking at, not just that something was flagged
  elsewhere on the page. This same score also sets how much confidence
  `claimed_only` damage gets priced at (see Cost estimate below) — it's
  worth showing both effects are the same underlying number, not two
  coincidentally-similar signals.
- VIN as reported, and a clear visual flag if `evidence.vin_match` is
  `false` — this is a real signal the adjuster needs to see immediately,
  not discover by reading the coverage reason text. Consider a small
  warning badge directly on this section.

**Coverage result** (from `coverage_result`):
- Status (`covered` / `not_covered` / `needs_review`) as a colored badge
  (semantic color again — not the same palette as the priority pill, to
  avoid the adjuster confusing "priority" with "coverage status" at a
  glance), the `reason` text in full (this is often the single most
  decision-relevant sentence on the page), and the `deductible`.
- `cause_covered` and `coverage_confidence` (present once the exclusion
  assessment is reached — absent if the claim was already routed to
  `not_covered`/`needs_review` by an earlier fixed check like an inactive
  policy or an unlisted driver). This is the model's own read of whether
  the accident's cause, as described, falls under one of the policy's
  exclusions (racing, commercial use) — not a keyword match — paired with
  its own confidence in that call. Render `coverage_confidence` as a
  percentage next to the status badge, and treat it the same way the
  `part_provenance` confidence is treated below: a clearly-labeled
  model-judgment value, not a deterministic fact. A confidence below 50%
  always means `status` is `needs_review` regardless of which way
  `cause_covered` leans (see `claims_handling_policy.md` §2.1 — 0.5 is a
  preponderance-of-the-evidence threshold, not an arbitrary cutoff); it's
  worth surfacing that explicitly in the UI ("assessment inconclusive") so
  the adjuster understands why a claim landed in review despite the model
  leaning toward "covered."

**Risk result** (from `risk_result` — can be `null`, see below):
- `risk_flag` (`clean` / `needs_closer_look`) as a badge, and the `reason`
  text — this can now combine up to four independent signals in one
  sentence (claim frequency, how recently the policy was opened before the
  loss, the VIN appearing on a *different* policyholder's claim, and a
  description-vs-photo inconsistency from step 3), so render `reason` in
  full rather than truncating it; consider splitting it
  into separate labeled lines client-side if it gets long enough to want
  visual separation. When flagged, the reason will reference specific prior
  `claim_id`s; consider making those clickable/cross-referenceable to claim
  history if a browsing view for that is ever built (not in scope here,
  just noting the extension point).

**Coverage-denial fast track — both sections above can be entirely absent.**
When `coverage_result.status` is `not_covered`, the claim skips risk-history
and cost-estimation entirely (`claims_handling_policy.md` §2.2) — there's no
operational reason to fraud-score or price repairs for a loss already
outside the policy's terms. `risk_result` and `cost_estimate` are `null` in
this case, not an error and not "not yet computed." Render this section as
a single explanatory line — "Risk and cost were not assessed: this claim's
coverage was denied at intake ({coverage_result.reason})" — rather than
an empty card, a loading state, or (worse) silently omitting the section,
which would read as a bug to an adjuster expecting to see it. This does not
apply to `needs_review` — that means coverage is genuinely undetermined, so
the claim still carries a full risk/cost assessment same as any other.

**Cost estimate** (from `cost_estimate` — `null` under the fast track above):
- The low-high range, prominently — this is often the number driving the
  whole decision.
- `insurable_amount` — the high end capped at the policy's `limits`
  (`claims_handling_policy.md` §5.1). This, not `estimated_cost_high`, is
  the figure that represents what the policy can actually pay; render it
  as the headline number when `exceeds_limit` is true (with the raw
  uncapped high end shown alongside, smaller, for context), and identical
  to `estimated_cost_high` otherwise — no separate rendering needed when
  the two already match.
- `priced_parts` and `unknown_parts` as two distinct lists — `unknown_parts`
  in particular is a signal to the adjuster that the estimate is
  incomplete/less reliable (parts the system had no pricing data for), and
  should probably be visually flagged rather than quietly listed.
- `part_provenance` — a per-part breakdown (`{part: {provenance, score}}`)
  the adjuster should see line-by-line against each priced part, not just
  as a total. The agent decides *which tier a part belongs to* (that's a
  real judgment call — did it actually see this in a photo, or only read
  it in text) — see `estimate_repair_cost`'s docstring: `photo_confirmed`
  is always a fixed 1.0 (independently visible in a photo). `claimed_only`
  is not a fixed number at all — it's `evidence.consistency_score` (the
  same 0.0-1.0 model-judged score shown in the Evidence section above)
  directly, *unless* that score clears `CONSISTENCY_SCORE_THRESHOLD` (0.7),
  in which case claimed-only damage earns the same full 1.0 as
  photo-confirmed damage. Still priced either way, at a confidence that
  reflects whether the rest of the claim's story already checks out — a
  claim that's only a little inconsistent scores a little lower, not a
  hard drop to some separate fixed floor. Deliberately not a finer-grained
  plausibility score — an earlier version tried scoring claimed-only parts
  against a fixed "does this fit the incident type" table and it was
  arbitrary and rigid; see `claims_handling_policy.md` §4 for the
  reasoning. Render as a confidence badge per part-line, not just a
  number — this is exactly the kind of state that should be encoded in
  form, not just text. This is also what the customer sees a plain-language
  version of on their own confirmation screen (2.4).
- `exceeds_limit` — a boolean the adjuster needs to see immediately, not
  discover by doing the arithmetic themselves against the policy's `limits`
  field above. Render as a hard warning badge (distinct from the softer
  "unknown parts" flag) when `true`, alongside `policy_limit` for reference
  — and alongside `insurable_amount` above, since that's the number the
  badge is actually explaining.

**Priority result** (from `priority_result`):
- The priority label (matches the queue's pill) and its `reason` — this is
  the system's own explanation of *why* it triaged this the way it did,
  which is valuable context for the adjuster even though the priority
  classification itself never approves or denies anything on its own — see
  §6/§6.2 for what does. Under the fast track above, this is always `"high"`
  with a reason that names the
  coverage denial directly (`"Coverage is not covered: ..."`) rather than
  the usual multi-signal reasoning — this is expected, not a truncated or
  broken result.

**System recommendation** (from `recommendation` — adjuster-only for a
`pending_review` claim, never shown to the customer anywhere in the client
portal for those; for an `auto_approved`/`auto_denied` claim, by contrast,
this same field already *was* executed and told to the customer directly,
per §2.4 — this section of the page is describing the same field, not a
different one, and the claim's `status` is what tells you which situation
you're looking at):
- `recommended_action` (`approve` / `deny` / `needs_manual_review`) and
  `recommended_amount` (present only when the action is `approve`; already
  capped against `insurable_amount` above, §5.1, so it never exceeds what
  the policy could actually pay), plus a `reason` — this is
  `recommend_decision`'s output, derived entirely from the
  coverage/risk/cost/priority results already shown above it on this page,
  not a new independent judgment. Render it as a clearly separate,
  visually muted card (not a pill matching priority/coverage/risk's
  semantic-color treatment, and not placed near the Decision action in
  3.4) — the goal is "here's a starting point the system computed for you,"
  not "here's the answer," and the two must never be visually confusable.
  A label like "System suggestion (not a decision)" directly on the card
  is worth the redundancy on a `pending_review` claim; on an
  `auto_approved`/`auto_denied` claim, label it instead as what it actually
  was — "Executed automatically" — since here it genuinely was the final
  word, not a suggestion an adjuster could have overridden. See
  `claims_handling_policy.md` §6.1/§6.2 — for a `pending_review` claim, the
  adjuster is free to disregard this with no justification required by the
  system itself.

### 3.4 Decision action

This is where the adjuster actually resolves the claim — approve (with an
amount, which may differ from the estimate) or deny (with a reason). Two
buttons/actions, not a single ambiguous "resolve" button, since the two
paths need different required inputs (an amount vs. a reason). **This
action only ever applies to a `pending_review` claim** — an
`auto_approved`/`auto_denied` claim already has its outcome; this UI
shouldn't offer a decision form for one at all (§3.3's claim detail page
should render those two statuses read-only instead).

**Recommended architecture** (a decision reached earlier in this project,
worth restating for whoever builds this): this action should **not** go
through the conversational agent at all. `log_outcome` today is plain data
— `final_decision`, `matched_system_suggestion`, `override_reason` — with
zero judgment involved in the write itself. The adjuster portal's own
backend should write directly to whatever real datastore this local-file
backend gets swapped for (the `claims_log.json`-shaped record, plus
flipping the matching `escalations.json`-shaped entry to
`status: "resolved"`) — not literally the local files themselves, since
those live on the agent's own machine with no remote API a separately
hosted portal backend could call; see README.md's "Swapping in real
backends" — exactly mirroring what `log_outcome` does today, rather than
requiring someone to have a chat conversation with the agent to log a
decision. This
means the "decision" UI here is a normal form submission against your own
backend, not a chat turn.

Fields on this action:
- **Approve**: an amount input, editable, pre-filled from
  `recommendation.recommended_amount` when present (falling back to the
  cost estimate's midpoint if the recommendation itself wasn't an
  `approve`, e.g. the adjuster is overriding a `deny`/`needs_manual_review`
  suggestion). If `cost_estimate` is also `null` — the coverage-denial fast
  track (§3.3) — there's no estimate to fall back to either; leave the
  field blank for manual entry rather than pre-filling a fabricated number.
  Optional adjuster notes either way.
- **Deny**: a required reason (free text, or a reason-code dropdown plus
  free text for specifics — recommend the dropdown-plus-detail pattern for
  consistency/reportability over free text alone).
- Both paths should capture whether this decision matched
  `recommendation.recommended_action` (`approve` == approve, `deny` ==
  deny, `needs_manual_review` counts as a match for either outcome, since
  it wasn't a lean either way) — this maps to `matched_system_suggestion`
  and `override_reason`. This doesn't need to be a question posed directly
  to the adjuster ("did you override the system?"); the backend can derive
  it directly by comparing the submitted decision against
  `recommendation.recommended_action` already sitting in the same
  `escalations` document, prompting for `override_reason` only when they
  disagree.
- A confirmation step before final submit — this is a one-way action
  (there's no "undo" modeled in the data anywhere), so a lightweight "You're
  about to approve this claim for $X — confirm?" step is warranted.

### 3.5 Resolved / history view

After a decision, the claim leaves the active queue (3.2) since its
`escalations.status` is now `resolved`. Adjusters will still want to look
back at what they (or their team) decided:

- A separate "Resolved" tab/view, same card/row layout as the queue but
  showing `claims_log`'s `final_decision`, whether it `matched_system_suggestion`,
  and `override_reason` when present.
- Filterable by date range and by whether a decision was an override — the
  override cases are exactly the ones worth reviewing for pattern-spotting
  (see the fraud-detection discussion below).
- This view is also the natural place a future "why did we deny this"
  audit/compliance need would be served from — it's already the permanent
  record.
- **Include `status == "auto_approved"` and `status == "auto_denied"`
  claims here too**, each distinguished from a human-resolved row (e.g. a
  small "system-approved"/"system-denied" label/icon instead of an
  adjuster's name) — these never passed through the active queue (3.2) at
  all, so this view is the *only* place an adjuster can see them, and it's
  the natural place to spot-check that both carve-outs are behaving as
  intended — an auto-denial in particular is worth an adjuster spot-checking
  periodically, since nobody reviewed it before it took effect.
  `matched_system_suggestion` is always `true` and `override_reason` always
  empty for both, since there was no human decision to compare against.

---

## 4. Cross-cutting concerns

### 4.1 Tone and copy

Client portal: empathetic, plain language, short sentences, no insurance
jargon leaking into customer-facing text (e.g. don't say "loss date" to the
customer, say "the date of the accident"; don't say "coverage status:
needs_review" anywhere the customer can see it). Adjuster portal: precise,
dense, professional — the adjuster already knows the jargon and wants
information density, not reassurance.

### 4.2 Polling (adjuster queue)

The queue (3.2) should reflect new escalations promptly — a claim shouldn't
sit invisible for minutes because of a stale cache. The current local-file
backend (README.md's "Local data storage") has no realtime push/listener
primitive at all — a real deployed adjuster portal couldn't reach a file on
the agent's own machine in the first place, which is exactly why this
backend is a mock/demo stand-in, not something to design the real
architecture around (see README.md's "Swapping in real backends"). Whatever
real datastore replaces it, recommend building for polling rather than
assuming a subscribed listener will be available: the adjuster portal's
backend polling on a short interval (a few seconds) and pushing updates to
connected clients itself (e.g. via its own WebSocket/SSE layer), rather
than each browser tab polling the datastore directly — that way, multiple
adjusters' queues stay in sync with each other via the portal's own
backend fan-out regardless of whether the eventual datastore happens to
offer a native realtime mechanism (some do, some don't).

### 4.3 Responsiveness

Client portal: mobile-first. The realistic scenario is someone standing at
the side of a road, or at home shortly after an incident, on their phone.
Every control (photo capture especially) needs to work well one-handed on a
phone screen.

Adjuster portal: desktop-first. This is a data-dense professional tool used
at a workstation for extended periods; don't compromise information density
to accommodate a phone layout that adjusters are unlikely to need.

### 4.4 Accessibility

Both portals: real focus states on every interactive element, sufficient
color contrast especially on the priority/status pills (color alone should
never be the only signal — pair color with a text label, which the designs
above already do by specifying "pill" as color + text). Client portal in
particular should be tested with a screen reader given the chat-style
interface, which can be less naturally accessible than a traditional form
if built carelessly (ensure new agent messages are announced, form
controls embedded in chat bubbles have proper labels).

### 4.5 Every open gap, in one place

Restating everything flagged inline above, so nothing gets lost:

1. **No GCS bucket or photo upload endpoint exists yet.** The client
   portal's photo widget (2.2, sub-phase C) needs this built — direct
   browser-to-GCS upload, with only the resulting file reference passed
   into the agent conversation as text.
2. **No customer notification mechanism exists.** How the customer learns
   the final outcome (2.6) is unresolved — status-check-on-return,
   email/SMS, or both.
3. **No adjuster identity/auth model exists.** Needed for the adjuster
   portal's login (3.1) and for any future per-adjuster assignment.
4. **No `assigned_to` field on `escalations`.** If adjusters should be able
   to claim/assign items in the queue (3.2) rather than working it
   unassigned, this needs a schema addition.
5. **The adjuster's decision-write path is a recommendation, not yet
   built**: writing directly to a real datastore from the adjuster portal's
   backend (3.4), bypassing the conversational agent for this step — the
   current local-file backend (README.md's "Local data storage") isn't
   reachable from a separately hosted portal backend at all, so this is
   blocked on picking a real datastore, not just on writing the code.
6. **The adjuster queue needs real polling, not a listener** (4.2) — the
   current local-file backend has no realtime subscription primitive, and
   design for polling regardless of what real datastore eventually
   replaces it, since not all of them offer one either.

Note: the fraud/coverage rule gaps flagged in earlier drafts of this
document (policy limit enforcement, a real listed-drivers check instead of
keyword matching, policy-age-at-loss, cross-policyholder VIN reuse) have
since been implemented in `tools.py` — see the field notes on the claim
detail screen (3.3) above for how each one now surfaces. The other-exclusion
check (racing, commercial use) has also since moved off keyword matching,
onto a model-judged `cause_covered`/`coverage_confidence` assessment — see
3.3's Coverage result field and `claims_handling_policy.md` §2.1. The one
remaining coverage-side gap is **location as a territorial coverage
factor**: the
incident's `location` is still free text with no policy-level territory
field to check it against, and needs a design decision (state-level string
match vs. something more precise) before it's buildable.

Three more decisions made since the first draft, no longer open:
- **Client portal auth is policyholder-only** (2.1) — the policyholder logs
  in with their own credentials; there is no separate identity for other
  listed drivers, who only ever appear as a `driver_name` value inside a
  claim the policyholder files.
- **Endorsements are explicitly out of scope** — not being modeled or
  built. Exclusions (which only ever subtract coverage) remain the only
  policy-modification concept in the system.
- **Priority thresholds are percentage-of-limit, not flat dollar amounts**
  (10% / 50% of the policy's own `coverage.limits`, loosely modeled on the
  industry's ~70-75% total-loss-threshold convention) — see
  `classify_claim_priority` in `tools.py`. This replaces the flat
  $3,000/$10,000 figures from earlier drafts, which didn't account for how
  differently a given dollar amount reads against a $5,000 limit versus a
  $50,000 one.
