# Google ADK Tutorial

A hands-on introduction to Google Agent Development Kit (ADK), starting from basic agents and tools and gradually moving into workflows, routing, and multi-agent systems.

## What's in the project

| File | Description |
| --- | --- |
| `01_ADK_Fundamentals.ipynb` | Beginner primer on agents, tools, sessions, state, events, specialists, and workflows |
| `02_Insurance_Claims_Agent.ipynb` | Applied tutorial that incrementally builds the insurance-claims architecture |
| `Google_ADK_Complete_Tutorial.ipynb` | Original broad ADK reference notebook |
| `GoogleADK_A2A.ipynb` | Separate introduction to Agent-to-Agent communication |
| `.env.example` | Template for environment variables |
| `pyproject.toml` | Project metadata and Python dependencies |
| `uv.lock` | Pinned, reproducible dependency versions |

## Recommended workshop sequence

1. Start with `01_ADK_Fundamentals.ipynb` to establish the core mental model.
2. Continue to `02_Insurance_Claims_Agent.ipynb` to apply those ideas to the claims workflow.
3. Use the `insurance_claim_agent/` package as the later production-oriented walkthrough.
4. Treat A2A and the original comprehensive notebook as optional follow-on material.

## Topics Covered

- ADK mental model
- Agents and tools
- Single-tool and multi-tool agents
- Sessions, state, and events
- Graph-based workflows
- Dynamic workflows
- Runtime branching, parallel execution, and loops
- Agent routing and delegation
- Collaborative multi-agent workflows
- Callbacks
- Testing and evaluation
- A2A introduction

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for Python and dependency management.

### 1. Install uv

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clone the repository

```bash
git clone <repo-url>
cd <repo-name>
```

### 3. Create the environment

```bash
uv sync
```

This creates a `.venv/` with the exact versions pinned in `uv.lock`, downloading the
Python version in `.python-version` if it isn't already installed.

### 4. Configure the Gemini API key

Copy `.env.example` to `.env`.

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux**

```bash
cp .env.example .env
```

Then open `.env` and replace the placeholder with your Gemini API key.

### 5. Run the notebook

Open `01_ADK_Fundamentals.ipynb` in VS Code and select `.venv` as the Jupyter kernel.

Run its cells in order, then continue to `02_Insurance_Claims_Agent.ipynb`.

## Working with dependencies

```bash
uv add <package>          # add a dependency (updates pyproject.toml and uv.lock)
uv remove <package>       # remove a dependency
uv sync                   # bring .venv back in sync with uv.lock
uv lock --upgrade         # re-resolve to the newest allowed versions
uv run python script.py   # run a command inside the project environment
```

Commit `uv.lock` so everyone installs the same versions.

## Requirements

- uv (which manages the Python 3.11+ toolchain for you)
- A Gemini API key
- VS Code with the Python and Jupyter extensions
