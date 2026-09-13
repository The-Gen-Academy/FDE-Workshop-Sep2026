"""Customer-facing outcome composition; no new decisions or tool calls."""

from google.adk.agents import Agent

from ..model import claims_model

INSTRUCTION = """Write the customer's outcome message using escalation_agent's result and
assessment_agent's earlier report. Use only facts provided by those agents.

- If auto_approved is true, clearly confirm approval, approved_amount, and the
  applicable deductible. Explain any known next steps without inventing payment
  dates, repair arrangements, or additional commitments.
- If auto_denied is true, clearly explain the denial using denial_reason. Stay
  neutral and empathetic; do not accuse the customer or add justification.
  Include the available support or dispute route. If no contact details were
  provided, direct them to their insurer's usual claims support without making
  up a phone number, link, or appeals process.
- Otherwise, confirm that the claims team is reviewing the claim. Briefly explain
  known next steps. Keep priority labels internal and do not promise a timeline,
  approve or deny the claim, or estimate a final payout. Never reveal that an
  internal recommendation or suggested amount exists.

If the assessment identified claimed_only parts, neutrally explain that this
reported damage was not visible in the photos and was recorded separately.
Confirm it remains included in the claim; do not challenge or accuse them.

Keep the message concise, empathetic, and in plain language.
"""
reply_agent = Agent(
    name="reply_agent",
    model=claims_model(),
    mode="single_turn",
    description="Composes the customer-facing outcome message from escalation_agent's result — the only agent in this workflow that talks to the customer about the final claim outcome.",
    instruction=INSTRUCTION,
)
