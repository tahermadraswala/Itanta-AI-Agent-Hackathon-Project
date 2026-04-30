# Itanta AI Agent Hackathon 2026 — Team Intent
## Core Orchestrator Module

> **Phase 2 Implementation — Central Control Layer**

---

## Overview

This module is the **central control layer** of the Itanta AI Agent Framework.
It converts a natural-language project specification into a validated,
test-driven software delivery pipeline by coordinating a graph of specialised AI agents,
each with a single narrow responsibility.

The design is based directly on the Team Intent Phase 1 design document and the
hackathon problem statement functional requirements.

---

## Architecture

```
Natural-Language Input
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR (core.py)                    │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │  State Mgr  │  │   Router    │  │  Checkpoint Manager │   │
│  │  (state.py) │  │ (router.py) │  │  (checkpoints.py)   │   │
│  └─────────────┘  └─────────────┘  └─────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    Agent Pipeline                       │  │
│  │  Clarifier → Architect → Planner → QA → Coder →         │  │
│  │  Reviewer → Validation → Recovery (on failure)          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐                            │
│  │   Logger    │  │  Summary    │                            │
│  │ (logger.py) │  │(summary.py) │                            │
│  └─────────────┘  └─────────────┘                            │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
  Generated Project + Workflow Summary Report
```

---

## File Structure

```
itanta_orchestrator/
├── main.py                      ← CLI entry point
├── config.yaml                  ← All runtime configuration
├── requirements.txt
├── README.md
│
├── orchestrator/
│   ├── core.py                  ← Main Orchestrator (event loop, routing, checkpoints)
│   ├── state.py                 ← WorkflowStateManager (stage transitions, persistence)
│   ├── router.py                ← AgentRouter (stage → agent mapping)
│   ├── checkpoints.py           ← CheckpointManager (save / restore / rollback)
│   ├── recovery.py              ← RecoveryAgent (retry, rollback, escalation)
│   ├── logger.py                ← ActivityLogger (dual text + JSONL logging)
│   └── summary.py               ← SummaryGenerator (Markdown + JSON report)
│
├── agents/
│   ├── base.py                  ← BaseAgent (shared interface)
│   ├── clarifier.py             ← ClarifierAgent  (FR-01, FR-02)
│   ├── architect.py             ← ArchitectAgent  (FR-04)
│   ├── planner.py               ← PlannerAgent    (FR-05, FR-06)
│   ├── qa_agent.py              ← QAAgent / TDD   (FR-11)
│   ├── coder.py                 ← CoderAgent      (FR-08, FR-09)
│   └── reviewer.py              ← ReviewerAgent   (FR-14 extended)
│
├── models/
│   ├── workflow.py              ← All Pydantic models (ProjectSpec, ImplementationPlan, …)
│   └── __init__.py
│
└── utils/
    ├── gemini_client.py         ← Gemini API wrapper (retry, JSON mode)
    └── __init__.py
```

---

## Setup

### 1. Prerequisites

- Python 3.11+
- A valid **Google Gemini API key** (from [Google AI Studio](https://aistudio.google.com/))

### 2. Install dependencies

```bash
cd itanta_orchestrator
pip install -r requirements.txt
```

### 3. Set your API key

```bash
export GEMINI_API_KEY="your_key_here"
```

Or create a `.env` file (never commit this):
```
GEMINI_API_KEY=your_key_here
```

### 4. Prepare your project specification

Create a plain-text file with your project description:

```
# spec.txt
Build a REST API for a task management system.
The API should support creating, reading, updating, and deleting tasks.
Tasks have a title, description, status (pending/done), and a due date.
Use FastAPI and SQLite.
```

---

## Usage

### Interactive mode (recommended for demos)

```bash
python main.py --project "Task Manager API" --spec spec.txt
```

The orchestrator will:
1. Ask you clarifying questions in the terminal
2. Show you the structured spec and ask for approval
3. Generate the architecture and task plan, ask for approval
4. For each task: generate tests, generate code, show the diff, ask for approval
5. Run tests automatically
6. Print a final summary report

### Auto-approve mode (CI / demos)

```bash
python main.py --project "Task Manager API" --spec spec.txt --auto-approve
```

### Non-interactive with pre-loaded answers

```bash
python main.py \
  --project "Task Manager API" \
  --spec spec.txt \
  --answers answers.json
```

Where `answers.json` maps each clarifying question to its answer:
```json
{
  "What database should the API use?": "SQLite",
  "Should the API include authentication?": "No, keep it simple for now."
}
```

---

## Configuration

All runtime behaviour is controlled via `config.yaml`.
No code changes are needed to adjust retry limits, checkpoint behaviour, or model selection.

Key settings:

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `llm` | `model` | `gemini-1.5-pro` | Gemini model to use |
| `llm` | `temperature` | `0.2` | Lower = more deterministic |
| `recovery` | `max_retries_per_task` | `3` | Retries before escalation |
| `recovery` | `retry_backoff_seconds` | `2` | Initial back-off (doubles each retry) |
| `checkpoints` | `require_spec_approval` | `true` | Human must approve spec |
| `checkpoints` | `require_plan_approval` | `true` | Human must approve task plan |
| `checkpoints` | `require_diff_approval` | `true` | Human must approve each code diff |

---

## Human Checkpoints

The framework pauses for human judgment at exactly three points:

| Checkpoint | Trigger | What you see |
|------------|---------|-------------|
| **Spec Approval** | After clarification | Structured spec (JSON) |
| **Plan Approval** | After task planning | Ordered task list with risk levels |
| **Diff Approval** | Before each code write | Unified diff of the proposed change |

Use `--auto-approve` to bypass all checkpoints during demos.

---

## Failure Handling

| Failure | Detection | Response |
|---------|-----------|----------|
| Ambiguous requirements | Clarification stage | Return to clarification |
| Validation failure | Test/lint output | Retry (pass errors to code-gen) |
| API failure | Timeout / HTTP error | Exponential back-off retry |
| State inconsistency | Stage mismatch | Rollback to last checkpoint |
| Unsafe diff | Reviewer flags risk | Block + escalate to human |
| Max retries exceeded | Retry counter | Escalate + mark task failed |

---

## Output Artifacts

After a successful run, find:

```
./logs/
    activity.log          ← Human-readable timestamped activity log
    activity.jsonl        ← Machine-readable JSONL for downstream analysis
    workflow_summary.md   ← Markdown summary report (tasks, tests, failures)
    workflow_summary.json ← JSON summary (for programmatic consumption)

./checkpoints/<run_id>/
    *.json                ← Checkpoint snapshots (one per control point)

./generated_project/
    tests/                ← TDD test files (one per task)
    src/                  ← Generated production code
    …                     ← Layout depends on the project specification
```

---

## Extending the Framework

### Adding a new agent

1. Create `agents/my_agent.py` extending `BaseAgent`
2. Implement the `run(state) → state` method
3. Register it in `orchestrator/core.py`:
   ```python
   self._router.register(WorkflowStage.MY_NEW_STAGE, MyAgent(gemini_client, logger))
   ```
4. Add `MY_NEW_STAGE` to `STAGE_ORDER` in `orchestrator/state.py`

### Switching LLM providers

Replace `utils/gemini_client.py` with a new client that exposes the same
`generate(prompt, system_instruction) → str` and `generate_json(…) → str` interface.
No other files need to change.

---

## Team Intent
**Taher Madraswala · Mustafa Bhagat · Rugved Boargaonkar**

*Itanta AI Agent Hackathon 2026*
