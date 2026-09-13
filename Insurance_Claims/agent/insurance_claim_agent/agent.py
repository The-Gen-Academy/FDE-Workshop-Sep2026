"""Ordered claims workflow: intake → assessment → escalation → reply.

Task-mode intake is dispatched dynamically because static graph nodes cannot
be task agents. Both nodes must wait for output; the outer node reruns when
resumed, with stable run IDs to continue the same conversation. These settings
prevent assessment from starting while intake is still asking questions.
"""

from google.adk.agents.context import Context
from google.adk.workflow import START, Workflow, node

from .sub_agents import assessment_agent, escalation_agent, intake_agent, reply_agent

_intake_node = node(intake_agent)


async def _intake_dispatch_fn(ctx: Context, node_input):
    """Resume the same intake task, propagating its waiting state."""
    return await ctx.run_node(
        _intake_node,
        node_input=node_input,
        run_id="intake",
        override_isolation_scope="intake",
        raise_on_wait=True,
    )


intake_dispatch = node(_intake_dispatch_fn, name="intake_dispatch", rerun_on_resume=True)
intake_dispatch.wait_for_output = True
root_agent = Workflow(
    name="auto_claims_intake_workflow",
    edges=[(START, intake_dispatch, assessment_agent, escalation_agent, reply_agent)],
)
