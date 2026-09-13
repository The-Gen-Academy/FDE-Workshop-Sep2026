# Meridian Auto Insurance — Claims Handling Policy (Auto Physical Damage)

> **This is a mock document written for this project.** Meridian Auto
> Insurance is fictional. The numbers below are internally consistent —
> the code in `insurance_claim_agent/tools.py` implements exactly what's
> written here — but they are not derived from real claims data, real
> actuarial analysis, or real regulatory guidance. Treat this as "the
> heuristics have a documented, traceable origin" rather than "the
> heuristics are correct." A real insurer adopting this system would need
> to replace every threshold below with values from their own underwriting
> and claims data.

## 1. Purpose and scope

This policy governs automated intake triage for personal auto physical
damage claims. It defines coverage verification rules, risk referral
criteria, damage evidence confidence handling, and severity classification
for the intake system described in `insurance_steps.md`. Section 6 governs
exactly which claims the automated system may resolve on its own (only
"low" priority — see §6) and which it may not (everything else); that
boundary applies regardless of anything else in this document.

## 2. Coverage verification

A claim is coverage-verified when all of the following hold (implemented
in `verify_coverage`):

- The date of loss falls within the policy's effective and expiration
  dates. (Fixed date-range check.)
- The reported incident type (collision or comprehensive) is included on
  the policy's coverage. (Fixed lookup against the policy's coverage
  flags.)
- The driver is on the policy's list of covered drivers, if the policy
  carries an `unlisted_driver` exclusion. (Fixed lookup against
  `listed_drivers` — a real identity check, not a text read.)
- No other listed exclusion applies to the reported cause of the
  accident. Standard other exclusions: racing or competitive driving, and
  commercial use of a personal-use vehicle.
- The vehicle identification number on the submitted evidence matches the
  VIN on file for the policy.

Any failure above routes the claim to `not_covered` or `needs_review`
rather than `covered` — never inferred favorably in the customer's
absence of information.

### 2.1 Exclusion-cause assessment is a model judgment, scored

Whether the reported *cause* of an accident falls under one of the
policy's non-driver exclusions (racing, commercial use) is not a keyword
match against the incident description — an earlier version of this
system did exactly that (substring-matching the exclusion name against the
description) and it was too blunt: it would flag any incidental mention of
a word like "racing" regardless of context, and miss a paraphrased
description of the same excluded conduct.

Instead, the model reads the full incident description against this
policy's own `exclusions` list and reports two things to `verify_coverage`:
a determination (`cause_covered`) and a self-assessed confidence
(`coverage_confidence`, 0.0-1.0) in that determination — plus a brief
`coverage_reasoning`. This is deliberately not a fixed lookup table (the
same reasoning as Section 4's rejection of a fixed impact-zone table
applies here): the space of ways a customer might describe an excluded
cause is not enumerable in advance.

The confidence score is not an arbitrary number: **0.5 is used as the
decisive threshold because it is the standard preponderance-of-the-evidence
bar** ("more likely than not") that insurers commonly apply when weighing
whether a fact — here, whether an exclusion applies — is established. At
or above 0.5, the model's own determination stands and drives the coverage
status (`not_covered` if `cause_covered` is false, otherwise coverage
proceeds to the remaining checks). Below 0.5, the model itself isn't
confident enough for its lean to be decisive, so the claim routes to
`needs_review` regardless of which way it leans — an uncertain "probably
covered" is treated the same as an uncertain "probably excluded": both go
to a human adjuster rather than being resolved by a low-confidence guess.

This assessment, and its score, feed only the `coverage_result` used for
adjuster triage. Per Section 6, it never approves or denies a claim by
itself.

### 2.2 A confirmed coverage denial short-circuits the rest of the assessment

When coverage comes back `not_covered` — for any reason: the policy wasn't
active on the date of loss, the incident type isn't covered, or a
high-confidence exclusion match (§2.1) — the claim skips risk history and
cost estimation (Sections 3-4's tools, `check_claim_history` and
`estimate_repair_cost`) entirely. There is no operational purpose in
fraud-scoring or pricing repairs for a loss already outside the policy's
terms. Priority (Section 5) is set automatically to `high`, and the
system's recommendation (§6.1) is `deny`, both citing the same coverage
reason.

This does **not** skip Section 6 — the claim is still queued for a human
adjuster exactly as any other claim would be. Only the intermediate risk
and cost signals are skipped; human review never is.

This short-circuit applies only to a confirmed `not_covered` result.
`needs_review` (unlisted driver, a low-confidence exclusion assessment,
VIN mismatch) is deliberately excluded: coverage remains genuinely
undetermined in that case, so the claim still receives the full risk and
cost assessment — every signal helps the adjuster resolve the ambiguity,
rather than short-circuiting an undecided case.

## 3. Risk and fraud referral criteria

A claim is referred for closer review (`check_claim_history`) if any of
the following are true. These are independent triggers — one is
sufficient, and multiple triggers should be read as compounding risk
signals for the adjuster, not averaged into a single score:

- **Claim frequency**: 2 or more claims filed by the same policyholder
  within a rolling 365-day window. This reflects Meridian's standard
  frequency-based referral criteria to claims review.
- **New policy**: the date of loss falls within 30 days of the policy's
  effective date. Early-tenure claims are overrepresented in fraud
  investigations industry-wide (adverse selection risk is highest
  immediately after binding), so Meridian treats the first 30 days of any
  policy as a heightened-scrutiny window.
- **Cross-policyholder VIN history**: the vehicle identified in this claim
  has a prior claim on file under a *different* policyholder. A
  policyholder-scoped history lookup cannot see this by construction — it
  is tracked separately (`vin_claims`) specifically to catch a vehicle
  changing hands with claims following it, a known pattern in staged-loss
  and identity-related fraud.
- **Description-vs-evidence inconsistency**: the agent's own `consistency_score`
  (0.0-1.0, `record_damage_evidence`, Section 4) for how well the submitted
  photos agree with the customer's account falls below
  `CONSISTENCY_SCORE_THRESHOLD` (0.7) — e.g. reported minor damage against
  photographed structural damage, or damage inconsistent with the stated
  mechanism of loss. A photo simply not showing something the customer
  mentioned should not lower this score on its own — see Section 4.

### 3.1 Three of these four signals are "hard" fraud signals

Claim frequency, new policy, and cross-policyholder VIN history are each a
lookup against an **objective recorded fact** — a date, a count, a VIN
match — with essentially no room for the check itself to be wrong (the
underlying data could still be wrong, but the check faithfully reflects
whatever data is on file). Description-vs-evidence consistency is
different in kind: it's the model's own **subjective read** of whether a
photo plausibly matches a description, which is far more likely to be
mistaken — an ambiguous photo, an imprecise turn of phrase, or a genuinely
hard-to-photograph type of damage can all produce a low score on a
perfectly legitimate claim.

This distinction is why only the first three are ever eligible to
auto-deny a claim (§6.2) — Meridian is only willing to let the system deny
a claim outright, with no adjuster, when the reason is a recorded fact the
system can point to directly, never a model's own judgment call about a
photo. Consistency remains referral-only regardless of how low it scores.

## 4. Damage evidence confidence

**Photographic evidence is mandatory.** A minimum of 2 photos is required
before damage evidence can be recorded (`MIN_REQUIRED_PHOTOS`,
`record_damage_evidence`) — a text-only account of damage is not
sufficient to open a damage evidence record, regardless of how detailed
the customer's description is. The VIN is always customer-provided (typed
or spoken) and is never extracted from a photo by the agent; VIN
character recognition from an image is a distinct, error-prone task the
agent is not asked to perform, and treating it as such would introduce an
unvalidated source of truth into the VIN-match check in Section 2.

Meridian's AI governance standards do not permit automated plausibility
inference (e.g. "does this claimed damage make sense for this incident
type") without a validated statistical model of real damage patterns —
Meridian does not have one, and neither invents crash-damage taxonomy nor
outsources that judgment to a general-purpose language model's
unsupported guess. Until such a model exists and is validated, damage
confidence is tracked with a provenance signal keyed to `consistency_score`
(`estimate_repair_cost`), not a plausibility score:

| Tier | Score | Meaning |
|---|---|---|
| `photo_confirmed` | 1.0 (fixed) | Independently visible in submitted photo evidence |
| `claimed_only` | 1.0 if `consistency_score` ≥ 0.7, else `consistency_score` itself | Reported in the customer's account, not visible in any photo |

`photo_confirmed` is always 1.0 — you either independently saw it or you
didn't. `claimed_only` is not a fixed number at all: `consistency_score` is
the model's own continuous read (0.0-1.0, `record_damage_evidence`) of how
well this claim's photos and narrative agree overall — the same signal
Section 3 uses for its description-vs-evidence risk referral, rather than
inventing a new judgment here. At or above `CONSISTENCY_SCORE_THRESHOLD`
(0.7), that agreement is strong enough to trust claimed-only damage exactly
like photo-confirmed damage, so it gets the same 1.0. Below that threshold,
`claimed_only` items are priced at `consistency_score` directly — a claim
that's only a little off scores a little lower, not a hard drop to some
separately-invented floor. 0.7 continues the confidence level this system
already granted claimed-only damage on a cleanly-matching claim before this
was a continuous score; formalizing it as the threshold for full trust
(rather than a second fixed output value) is what removes the discontinuity
a fixed two-tier scheme had.

Both tiers are priced — Meridian does not withhold payment for real damage
solely because it falls outside what a photograph can show (mechanical,
structural, and electronic damage routinely are not visible in customer-
submitted photos). `claimed_only` items are surfaced to both the reviewing
adjuster and the customer (see Section 7) as unconfirmed, not denied.

## 5. Claim severity classification

Every claim receives a priority classification (`classify_claim_priority`)
for adjuster queue triage, expressed as a percentage of the *policy's own*
coverage limit rather than a flat dollar figure — a given dollar amount
means something different against a $5,000 limit than a $50,000 one.

| Priority | Trigger |
|---|---|
| `high` | Coverage not clearly `covered`, any Section 3 risk trigger fired, estimated cost exceeds 50% of the policy limit, or estimated cost exceeds the limit outright |
| `medium` | Otherwise clean, but estimated cost exceeds 10% of the policy limit |
| `low` | Coverage clear, no risk triggers, estimated cost at or below 10% of the policy limit |

The 50%-of-limit high-priority trigger is deliberately conservative
relative to typical industry total-loss thresholds (commonly 70-75% of
vehicle value in most jurisdictions) — Meridian's intent is for a claim
approaching total-loss territory to already be in front of a senior
reviewer well before it reaches that boundary, not at it.

Priority is a triage aid for "medium" and "high" claims — it has no
bearing on their outcome, which only a human adjuster decides. For "low"
priority, by contrast, the classification itself is what triggers
auto-approval — see Section 6.

### 5.1 Insurable amount is capped at the policy limit

`estimate_repair_cost` reports an `insurable_amount` alongside the raw cost
range: the estimate's high end, capped at the policy's coverage limit
(`min(estimated_cost_high, policy_limit)`). A policy can never pay out more
than its own limit no matter how high a repair estimate runs, so the
figure an adjuster works from should already reflect that ceiling rather
than requiring them to do the arithmetic themselves against `policy_limit`
and `exceeds_limit`. When the estimate doesn't exceed the limit,
`insurable_amount` simply equals `estimated_cost_high`, unchanged.

`recommend_decision`'s approve-amount calculation (§6.1) is capped against
this same figure, as a backstop — in practice, an estimate that exceeds the
limit already forces `high` priority under this section, so the approve
path and this cap rarely interact directly, but the cap holds regardless
of how the priority logic evolves.

## 6. Human review is mandatory, except for "low" priority claims

No claim above "low" priority (Section 5) is approved, denied, or adjusted
by the automated system under any circumstance, regardless of confidence
scores or coverage result. Every "medium" or "high" priority claim is
queued for a licensed human adjuster (`package_for_adjuster`), who makes
the sole determination. This section supersedes any other provision of
this policy, for every claim neither of this section's two carve-outs
below applies to.

**Exception one — auto-approval**: a "low" priority claim — Section 5's
cleanest tier, meaning coverage is clearly `covered`, no Section 3 risk
trigger fired, and the estimated cost is within `LOW_PRIORITY_LIMIT_PCT` of
the policy limit — is auto-approved by the system itself, at the amount
`recommend_decision` (§6.1) computes, with no adjuster ever looking at it.
There is no ambiguity left in a "low" claim for a human to resolve: every
input to that classification is already a clean, unambiguous result, not a
marginal or uncertain one. A "low" priority claim still produces a full
audit trail — `package_for_adjuster` writes both an `escalations` record
(status `auto_approved`) and a `claims_log` record, the same two writes a
human adjuster's decision eventually produces via `log_outcome` — so the
record is durable and queryable even though nothing reads it before the
approval takes effect.

**Exception two — auto-denial (§6.2)**: a claim flagged by any of the three
*hard* fraud signals from Section 3.1 (claim frequency, new policy, or
cross-policyholder VIN history — never the softer consistency signal) is
auto-denied the same way, with the same audit-trail treatment. See §6.2 for
the full reasoning and boundary.

### 6.1 System-generated recommendations are advisory for "medium"/"high" claims, executed for "low"

The system drafts a recommended action and, where relevant, a recommended
amount (`recommend_decision`) from results already computed under Sections
2-5 (coverage status, risk flag, cost estimate, and priority) — it
introduces no new judgment of its own:

| Priority (Section 5) | Coverage (Section 2) | Risk (Section 3) | Recommendation |
|---|---|---|---|
| `low` | `covered` | clean | `approve`, at the cost estimate's midpoint (capped at `insurable_amount`, §5.1) minus the deductible — **executed automatically, per §6's carve-out** |
| `medium` | `covered` | clean | `approve`, at the cost estimate's midpoint (capped at `insurable_amount`, §5.1) minus the deductible — advisory only |
| `high` | `not_covered` | — | `deny`, citing the coverage failure reason — including the §2.2 fast-tracked case, where this is the only recommendation reached since risk/cost were never computed. Always adjuster-only — see §6.2. |
| `high` | anything else | hard fraud signal(s) fired | `deny`, citing which hard signal(s) fired and the same detail `check_claim_history` produced — **executed automatically, per §6.2's carve-out** |
| `high` | anything else | no hard signal | `needs_manual_review`, citing the priority reason |

For every row except the two marked "executed automatically," this
recommendation is stored only in the adjuster-facing package. It is never
surfaced to the customer in any form — not the action, not the amount, not
its existence — and it carries no authority: an adjuster is free to
disregard it entirely without any override justification being required by
the system itself (though Meridian's own case-handling procedures outside
this document may separately require adjusters to document their
reasoning, as with any claim decision). Section 6's supersession applies to
this recommendation exactly as it applies to priority, confidence scores,
and coverage results, for every claim neither carve-out applies to. For
"low" priority and hard-fraud-signal claims, by contrast, this
recommendation *is* the outcome told to the customer — not adjuster-only
context.

### 6.2 Hard fraud signals may auto-deny a claim, never auto-approve one

A claim flagged by any of Section 3.1's three *hard* fraud signals — claim
frequency, new policy, or cross-policyholder VIN history — is auto-denied
by the system itself, the same way a "low" priority claim is auto-approved:
no adjuster ever looks at it, and `package_for_adjuster` writes the same
two audit records (`escalations` status `auto_denied`, plus a `claims_log`
entry) immediately.

This carve-out is deliberately narrower than auto-approval's in two ways:

- **Only the three hard signals qualify — the softer consistency signal
  never does**, regardless of how low the score is (§3.1). Consistency is
  the model's own subjective read of a photo against a description, not a
  recorded fact; Meridian is only willing to let the system deny a claim
  outright when it can point to a fact on file, never to its own judgment
  call.
- **A coverage-exclusion denial (`not_covered`, §2, §2.2) is never
  auto-executed, even though it also recommends `deny`.** That
  determination already always reaches a human adjuster under this
  section's main rule, and this carve-out does not change that — only a
  hard-fraud-signal denial is auto-executed. The two "deny" rows in
  §6.1's table are handled identically by `recommend_decision`, but
  `package_for_adjuster` tells them apart by checking whether a hard
  fraud signal is actually present before executing either one.

An auto-denied claim still produces the same full audit trail described in
Section 6's second exception above. Because this is a one-sided outcome
with no adjuster ever reviewing it, the customer must always be told a
concrete way to reach support and dispute the decision (§7) — never left
with only a closed door.

## 7. Customer communication

The customer is told, in plain language, that their claim is under review
and what happens next — never that it has been approved or denied, **for
any claim neither of Section 6's two carve-outs applies to.** For an
auto-approved claim, the customer is told the real, final approved amount
and deductible directly. For an auto-denied claim, the customer is told
plainly that the claim was denied and why, in the same terms as the
system's own reason — never punitively or accusatorially, since this is a
statement of outcome, not a judgment of the customer — and always paired
with a concrete way to reach support and dispute the decision, since no
adjuster reviewed it. Where `claimed_only` damage exists (Section 4), the
customer is told plainly that it's noted for adjuster review and confirmed
as still part of the claim — never presented as a challenge or an
implication of dishonesty.
