"""Internal triage and persistence of the claim outcome."""

from google.adk.agents import Agent

from .. import tools
from ..model import claims_model

INSTRUCTION = """Triage the assessed claim using results in context. This is internal work;
do not address the customer.

Call these tools in order:
1. classify_claim_priority
2. recommend_decision
3. package_for_adjuster

The packaging tool decides whether the claim is pending_review,
auto_approved, or auto_denied. Do not decide or implement the outcome yourself.
Low-priority approvals and the demo policy's hard-signal denials execute
immediately. Other recommendations, including coverage denials, await an
adjuster and remain internal.

Report the priority and the packaging result to reply_agent:
- auto_approved: provide the approved_amount and deductible as the actual outcome.
- auto_denied: provide the denial_reason as the actual outcome, with any known
  support or dispute instructions. Do not invent contact details.
- Otherwise: confirm it was queued for an adjuster. Do not include the suggested
  action or amount in your response; they already exist in the adjuster package.
"""
escalation_agent = Agent(
    name="escalation_agent",
    model=claims_model(),
    mode="single_turn",
    description='Classifies claim priority, then auto-approves a "low" priority claim, auto-denies a hard-fraud-signal claim, or queues everything else for human review. No customer interaction.',
    instruction=INSTRUCTION,
    tools=[tools.classify_claim_priority, tools.recommend_decision, tools.package_for_adjuster],
)
