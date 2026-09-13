# Local portals

Two FastAPI apps share this workspace member. The customer portal sends
messages and photos to the agent. The adjuster portal reads the queue,
records decisions, and manages example policies through `claims-core`.

## Run

Complete the repository [setup](../README.md#local-setup), then start each
app from the root in its own terminal:

```bash
uv run --package claims-local-apps --extra local-agent python -m uvicorn client_portal.app:app --port 8002 --reload
```

```bash
uv run --package claims-local-apps python -m uvicorn adjuster_portal.app:app --port 8001 --reload
```

Customer chat: <http://localhost:8002>. Adjuster queue:
<http://localhost:8001>. These apps have no login; keep them bound to
localhost.

## Choose the agent backend

| Setting | Customer portal behavior |
| --- | --- |
| `AGENT_BACKEND=local` | Runs ADK in the portal process; requires the `local-agent` extra |
| `AGENT_BACKEND=vertex` | Calls the deployed agent identified by `AGENT_ENGINE_ID` |

Local ADK sessions disappear when the process restarts. Vertex mode uses
the deployed agent's sessions and stores portal metadata/transcripts in
the shared database, so conversations can resume after a portal restart.
You can omit `--extra local-agent` in Vertex mode. The adjuster portal
does not run an LLM and does not depend on the agent package.

When using Vertex, set `CLAIMS_STORE=firestore` and the same project,
database, and evidence bucket as the deployed agent. Authenticate local
server processes with `gcloud auth application-default login`; browsers
do not receive those credentials. See [deployment](../docs/deployment.md).

`AGENT_BACKEND` selects where the workflow runs. `CLAIMS_STORE` separately
selects where records live. Restart the portals after changing `.env`.

## Source map

Each portal keeps HTTP endpoints in `routers.py`, request/response models
in `schemas.py`, and browser assets in `static/`.
`client_portal/runner_service.py` handles agent sessions and streaming;
shared decision and storage logic lives in `claims-core`.
