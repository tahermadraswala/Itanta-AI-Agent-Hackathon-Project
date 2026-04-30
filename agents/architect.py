"""
agents/architect.py
────────────────────
Architect Agent — FR-04.

Responsibility:
  Take the approved ProjectSpec and produce:
    • directory layout
    • module boundaries
    • API contracts
  This output is stored in the ImplementationPlan (which the Planner
  will populate with tasks).
"""
from __future__ import annotations

import json

from agents.base import BaseAgent
from models.workflow import ImplementationPlan, WorkflowState


_SYSTEM = (
    "You are the Architect Agent in a multi-agent software development pipeline. "
    "Your only job is to design the project's structural blueprint — directory layout, "
    "module boundaries, and API contracts. You do NOT write code or implementation tasks. "
    "Be precise and follow software engineering best practices."
)


class ArchitectAgent(BaseAgent):

    def run(self, state: WorkflowState) -> WorkflowState:
        self._log_start()

        spec = state.spec
        if spec is None or not spec.is_complete():
            raise ValueError("ArchitectAgent: spec is missing or incomplete.")

        prompt = f"""
Design the software architecture for the following project.

PROJECT SUMMARY:
{spec.project_summary}

ACCEPTANCE CRITERIA:
{chr(10).join(f'- {c}' for c in spec.acceptance_criteria)}

CONSTRAINTS:
{chr(10).join(f'- {c}' for c in spec.known_constraints)}

Produce a JSON object with:
  "directory_layout"  : object mapping folder/file paths to their purpose (strings)
  "module_boundaries" : list of strings, each describing one module and its responsibility
  "api_contracts"     : list of strings, each describing one API endpoint or interface

Return ONLY the JSON object.
"""
        raw = self._call_llm_json(prompt, system=_SYSTEM)

        plan = state.plan or ImplementationPlan()
        try:
            data = json.loads(raw)
            plan.directory_layout  = data.get("directory_layout", {})
            plan.module_boundaries = data.get("module_boundaries", [])
            plan.api_contracts     = data.get("api_contracts", [])
        except (json.JSONDecodeError, TypeError) as exc:
            self._logger.error(f"ArchitectAgent failed to parse JSON: {exc}")

        state.plan = plan
        state.record_api_call()
        self._log_end(success=True)
        return state
