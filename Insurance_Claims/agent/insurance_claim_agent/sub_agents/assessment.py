"""Internal coverage, risk, and repair-cost assessment."""

from google.adk.agents import Agent

from .. import tools
from ..model import claims_model

INSTRUCTION = """Assess the opened claim using the incident, policy, and evidence in context.
This is internal work: do not ask questions or address the customer.

1. Call verify_coverage. Classify the incident as collision or comprehensive.
   Read this policy's exclusions and judge whether the incident's cause is
   covered. The tool checks dates, coverage types, listed drivers, and VIN;
   assess only the other exclusions, such as racing or commercial use.
   Give honest coverage_confidence from 0 to 1 and specific reasoning. Below
   0.5 requires human review; do not inflate confidence to force a decision.

2. If coverage is not_covered, stop and report only that result. Skip history
   and cost; the claim proceeds to an adjuster. If coverage is needs_review,
   continue with the remaining checks to help the adjuster resolve it.

3. Call check_claim_history, then estimate_repair_cost. Put independently
   visible damage in photo_confirmed_parts and additional damage reported in
   the incident or customer_damage_description in claimed_only_parts. Include
   hidden or mechanical damage even when photos cannot show it. Put each part
   in one list; the tool computes confidence scores itself.
   Map damage to keys such as front_bumper, rear_bumper, headlight, taillight,
   fender, hood, windshield, door_panel, quarter_panel, side_mirror, wheel_rim,
   trunk_lid, frame, airbag_system, and engine.

Return a brief internal summary of the actual tool results: coverage, risk,
and estimate, including any claimed_only parts. If coverage stopped the
assessment, say that risk and cost were skipped. Never invent missing data.
"""
assessment_agent = Agent(
    name="assessment_agent",
    model=claims_model(),
    mode="single_turn",
    description="Verifies coverage, checks claim history/risk signals, and estimates repair cost for an already-opened claim. No customer interaction.",
    instruction=INSTRUCTION,
    tools=[tools.verify_coverage, tools.check_claim_history, tools.estimate_repair_cost],
)
