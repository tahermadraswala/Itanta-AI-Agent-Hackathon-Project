"""
agents/planner.py
──────────────────
Planner Agent — FR-05, FR-06.

Responsibility:
  Decompose the architecture into an ordered, atomic task graph.
  Each task must be independently testable (FR-05).
  The plan is presented for human approval before execution (FR-06).
"""
from __future__ import annotations

import json
import uuid
from typing import List

from agents.base import BaseAgent
from models.workflow import ImplementationTask, TaskStatus, WorkflowState


_SYSTEM = (
    "You are the Planner Agent in a multi-agent software development pipeline. "
    "Break the architecture into the smallest atomic tasks where each task "
    "produces a single, independently testable unit of work. "
    "Order tasks respecting dependencies. Assign a risk level (low/medium/high) "
    "and flag tasks that require a human checkpoint before execution."
)


class PlannerAgent(BaseAgent):

    def run(self, state: WorkflowState) -> WorkflowState:
        self._log_start()

        spec = state.spec
        plan = state.plan
        if spec is None or plan is None:
            raise ValueError("PlannerAgent: spec or plan is missing.")

        modules_text = "\n".join(f"- {m}" for m in plan.module_boundaries)
        contracts_text = "\n".join(f"- {c}" for c in plan.api_contracts)

        prompt = f"""
Break this software project into an ordered list of atomic implementation tasks.

PROJECT SUMMARY:
{spec.project_summary}

MODULES:
{modules_text}

API CONTRACTS:
{contracts_text}

Rules:
- Each task produces exactly one independently testable unit of work.
- Order tasks so that each task's dependencies are completed before it.
- Assign risk_level: "low", "medium", or "high".
- Set requires_checkpoint to true for tasks that modify auth, data schema, or security.

Return a JSON array where each item has:
  "id"                  : unique short string (e.g. "task_001")
  "title"               : short title (max 8 words)
  "description"         : what this task does (1-2 sentences)
  "order"               : integer starting at 1
  "depends_on"          : list of task id strings (empty if no deps)
  "risk_level"          : "low" | "medium" | "high"
  "estimated_files"     : list of file paths this task will touch
  "requires_checkpoint" : boolean

Return ONLY the JSON array.
"""
        raw = self._call_llm_json(prompt, system=_SYSTEM)

        try:
            items: List[dict] = json.loads(raw)
            tasks = []
            for item in items:
                task = ImplementationTask(
                    id=item.get("id", f"task_{uuid.uuid4().hex[:4]}"),
                    title=item.get("title", "Unnamed task"),
                    description=item.get("description", ""),
                    order=int(item.get("order", 999)),
                    depends_on=item.get("depends_on", []),
                    risk_level=item.get("risk_level", "low"),
                    estimated_files=item.get("estimated_files", []),
                    requires_checkpoint=bool(item.get("requires_checkpoint", False)),
                    status=TaskStatus.PENDING,
                )
                tasks.append(task)

            # Sort by order field
            tasks.sort(key=lambda t: t.order)
            plan.tasks = tasks
            self._logger.info(
                f"PlannerAgent produced {len(tasks)} task(s)."
            )

        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            self._logger.error(f"PlannerAgent failed to parse task JSON: {exc}")

        state.plan = plan
        state.record_api_call()
        self._log_end(success=True)
        return state
