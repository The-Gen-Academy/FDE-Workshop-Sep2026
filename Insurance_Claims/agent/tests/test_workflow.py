"""Exercise the real ADK graph with scripted, entirely offline model responses."""

import asyncio

import cloudpickle
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from insurance_claim_agent.agent import root_agent


def test_intake_waits_then_resumes_before_downstream_agents(monkeypatch):
    calls = []

    async def scripted_model(self, llm_request, stream=False):
        tools = set(llm_request.tools_dict)
        if "start_claim_intake" in tools:
            stage = "intake"
        elif "verify_coverage" in tools:
            stage = "assessment"
        elif "package_for_adjuster" in tools:
            stage = "escalation"
        else:
            stage = "reply"
        calls.append(stage)
        part = types.Part(text=f"{stage} response")
        if stage == "intake" and calls.count("intake") > 1:
            part = types.Part(
                function_call=types.FunctionCall(
                    name="finish_task",
                    args={"result": "Intake complete"},
                )
            )
        yield LlmResponse(content=types.Content(role="model", parts=[part]))

    monkeypatch.setattr(Gemini, "generate_content_async", scripted_model)

    async def run():
        # Agent Engine serializes this graph before restoring it in the runtime.
        restored = cloudpickle.loads(cloudpickle.dumps(root_agent))
        runner = InMemoryRunner(node=restored, app_name="insurance_claim_agent")
        try:
            session = await runner.session_service.create_session(
                app_name="insurance_claim_agent",
                user_id="offline-test",
            )

            async def turn(text):
                return [
                    event
                    async for event in runner.run_async(
                        user_id="offline-test",
                        session_id=session.id,
                        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
                    )
                ]

            first = await turn("I need to open a claim.")
            assert calls == ["intake"]
            assert [event.author for event in first] == ["intake_agent"]

            second = await turn("Here is the remaining evidence.")
            assert calls == ["intake", "intake", "assessment", "escalation", "reply"]
            assert second[-1].author == "reply_agent"
            assert second[-1].content.parts[0].text == "reply response"
        finally:
            await runner.close()

    asyncio.run(run())
