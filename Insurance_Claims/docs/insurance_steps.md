Step 1: Collect incident information.
 What's collected: date and time of incident, location, a free-text description of what happened, whether the car is drivable, whether anyone was injured, whether another party was involved (and if so, their info), whether there's a police report.
Step 2: Identify the customer and their policy.
 What's collected/looked up: policyholder ID or login, policy number. System pulls the policy record — coverage types (collision/comprehensive), deductible, limits, effective dates, exclusions.
Step 3: Collect damage evidence.
 What's collected: photos of the damage (2-5 images), VIN (from photo or lookup). No repair shop involved yet at this stage — this is the customer's own submission.
Step 4: Verify coverage applies.
 What's checked: is the policy active on the date of loss? Is this type of incident covered under collision/comprehensive? Any exclusions that apply (racing, commercial use, unlisted driver)? What's the deductible?
 Output: covered / not covered / needs review, with a reason.
Step 5: Check claim history and risk signals.
 What's checked: has this VIN or this policyholder filed claims recently? Any pattern that looks unusual (frequency, timing, inconsistency between description and damage)?
 Output: a risk flag — clean / needs a closer look — with the specific reason if flagged.
Step 6: Estimate the cost.
 What's collected/looked up: which parts are likely damaged (from the photos/description), what those parts + labor typically cost (from a pricing reference).
 Output: an estimated repair cost range.
Step 7: Decide — resolve now or escalate.
 This is the branch point. Inputs to this decision: coverage result (Step 4), risk flags (Step 5), cost estimate (Step 6).

If coverage is clear, no risk flags, and cost is low/moderate → resolve directly.
If a "hard" risk signal fired instead — claim frequency, a too-new policy, or VIN reuse across policyholders, never the softer description-vs-photo consistency signal — resolve directly as denied, regardless of cost.
Anything else ambiguous, flagged, or high-value → escalate to a human adjuster.
Step 8a: If resolved directly as approved — tell the customer the outcome: approved, amount, deductible applied, what happens next (e.g., pick a repair shop, payment timing).
Step 8a-ii: If resolved directly as denied — tell the customer plainly that the claim was denied and why, and how to reach support and dispute it — no adjuster reviewed this one, so the customer needs a real next step, not a closed door.
Step 8b: If escalated — tell the customer it's under review and why, in plain language. Package everything collected in Steps 1–6 for the human adjuster, so they start with full context instead of a blank claim.
Step 9: Human adjuster resolves the escalated case (if escalated) — makes the final call, which may confirm or overturn what the system would have done.
Step 10: Log the outcome.
 What's recorded: the final decision, whether it matched what the system suggested, and — if a human overturned it — why. This becomes the record used to check and improve the system's judgment over time.