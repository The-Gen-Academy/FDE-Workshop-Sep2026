# Claims agent

This workspace member contains `insurance_claim_agent`, the Google ADK
workflow deployed to Vertex AI Agent Engine. It depends on `claims-core`;
neither portal is part of its deployment.

## Develop

From the repository root, complete the [local setup](../README.md#local-setup),
then run:

```bash
uv run --package insurance-claim-agent adk web agent
```

Select `insurance_claim_agent` at <http://localhost:8000>. The model uses
the Gemini API or Vertex AI according to `.env`; where the workflow runs
and which model API it calls are separate settings.

## Source map

| File | Responsibility |
| --- | --- |
| `insurance_claim_agent/agent.py` | Workflow order and resumable intake |
| `insurance_claim_agent/sub_agents/` | Intake, assessment, escalation, and reply instructions |
| `insurance_claim_agent/tools.py` | ADK tool signatures and session-state adapters |
| `../packages/claims_core/` | Claims decisions and persistence shared with the portals |
| `deploy.py` | Build and validate an agent-only deployment bundle; optionally deploy |

Intake can span multiple customer messages. The workflow waits for intake
to finish before assessment or escalation starts. Model instructions and
tool argument descriptions are part of runtime behavior, so changes to
them deserve the same review as changes to decision code.

## Deploy

Preview the deployment bundle without creating cloud resources:

```bash
uv run --package insurance-claim-agent python agent/deploy.py --dry-run
```

See [deployment](../docs/deployment.md) for required cloud configuration
and the explicit deployment command.
