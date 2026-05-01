"""
agents/planner.py
──────────────────
Planner Agent — FR-05, FR-06.

Receives the ArchitectOutput and produces a PlannerOutput: an ordered,
dependency-resolved list of atomic implementation tasks.

Outputs:     PlannerOutput (models/schemas.py)
Prompt src:  agents/prompts/planner_prompts.py
"""
from __future__ import annotations

import json
import uuid
from typing import List, Optional

from agents.base import BaseAgent
from agents.architect import ArchitectAgent
from agents.prompts import planner_prompts as P
from models.schemas import PlannerOutput, PlannerTask, RiskLevel, TaskCheckpoint
from models.workflow import ImplementationPlan, ImplementationTask, TaskStatus, WorkflowState


class PlannerAgent(BaseAgent):

    def run(self, state: WorkflowState) -> WorkflowState:
        self._log_start()

        spec = state.spec
        plan = state.plan
        if spec is None or plan is None:
            raise ValueError("PlannerAgent: spec or plan is missing.")

        arch = ArchitectAgent.get_output(state)

        # Build rich context for prompt
        module_names = ", ".join(
            m.name for m in arch.modules
        ) if arch and arch.modules else "core"

        modules_detail = self._format_modules(arch) if arch else "(no architecture detail)"
        data_models    = self._format_data_models(arch) if arch else "(none)"
        api_endpoints  = self._format_api_endpoints(arch) if arch else "(none)"

        prompt = P.MAIN_PROMPT_TEMPLATE.format(
            project_root=arch.project_root if arch else "generated_project",
            module_names=module_names,
            modules_detail=modules_detail,
            data_models=data_models,
            api_endpoints=api_endpoints,
            acceptance_criteria="\n".join(
                f"  - {c}" for c in (spec.acceptance_criteria or [])
            ),
        )

        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        planner_output = self._parse_output(raw)

        errors = planner_output.validate_completeness()
        if errors:
            self._logger.warning(f"PlannerOutput validation issues: {errors}")

        # Store full PlannerOutput on state for downstream agents
        state.__dict__["_planner_output"] = planner_output

        # Convert PlannerTask list to ImplementationTask list (internal model)
        impl_tasks = self._to_impl_tasks(planner_output.tasks)
        plan.tasks = impl_tasks

        self._logger.info(
            f"PlannerAgent produced {len(impl_tasks)} task(s). "
            f"Critical path: {planner_output.critical_path}."
        )

        state.plan = plan
        state.record_api_call()
        self._log_end(success=True)
        return state

    # ── Parsing ───────────────────────────────────────────────

    def _parse_output(self, raw: str) -> PlannerOutput:
        try:
            data = json.loads(raw)
            tasks = []
            for t in data.get("tasks", []):
                checkpoint: Optional[TaskCheckpoint] = None
                if t.get("checkpoint") and isinstance(t["checkpoint"], dict):
                    cp = t["checkpoint"]
                    checkpoint = TaskCheckpoint(
                        trigger=cp.get("trigger", ""),
                        approver=cp.get("approver", "human"),
                        reason=cp.get("reason", ""),
                    )

                task_id = t.get("id", f"task_{uuid.uuid4().hex[:3]}")
                if not task_id.startswith("task_"):
                    task_id = f"task_{task_id}"

                tasks.append(PlannerTask(
                    id=task_id,
                    title=t.get("title", "Unnamed task"),
                    description=t.get("description", ""),
                    order=int(t.get("order", 999)),
                    module=t.get("module", "core"),
                    depends_on=t.get("depends_on", []),
                    estimated_files=t.get("estimated_files", []),
                    risk_level=RiskLevel(t.get("risk_level", "low")),
                    requires_checkpoint=bool(t.get("requires_checkpoint", False)),
                    checkpoint=checkpoint,
                    acceptance_test=t.get("acceptance_test", ""),
                    estimated_complexity=t.get("estimated_complexity", "medium"),
                ))

            tasks.sort(key=lambda t: t.order)

            return PlannerOutput(
                tasks=tasks,
                total_estimated_complexity=data.get("total_estimated_complexity", "medium"),
                critical_path=data.get("critical_path", []),
                parallel_groups=data.get("parallel_groups", []),
                implementation_notes=data.get("implementation_notes", []),
            )

        except (json.JSONDecodeError, TypeError, KeyError, Exception) as exc:
            self._logger.error(f"PlannerAgent parse error: {exc}")
            return PlannerOutput(tasks=[], total_estimated_complexity="unknown")

    # ── Conversion ────────────────────────────────────────────

    @staticmethod
    def _to_impl_tasks(planner_tasks: List[PlannerTask]) -> List[ImplementationTask]:
        result = []
        for pt in planner_tasks:
            impl = ImplementationTask(
                id=pt.id,
                title=pt.title,
                description=pt.description,
                order=pt.order,
                depends_on=pt.depends_on,
                risk_level=pt.risk_level.value,
                estimated_files=pt.estimated_files,
                requires_checkpoint=pt.requires_checkpoint,
                status=TaskStatus.PENDING,
            )
            # Carry through extra fields
            impl.__dict__["module"]              = pt.module
            impl.__dict__["acceptance_test"]     = pt.acceptance_test
            impl.__dict__["estimated_complexity"] = pt.estimated_complexity
            impl.__dict__["checkpoint_detail"]   = pt.checkpoint
            result.append(impl)
        return result

    # ── Context formatters ────────────────────────────────────

    @staticmethod
    def _format_modules(arch) -> str:
        lines = []
        for m in arch.modules:
            lines.append(
                f"  [{m.name}] {m.responsibility}\n"
                f"    Files: {', '.join(m.files[:5]) or 'TBD'}\n"
                f"    Public: {', '.join(m.public_interface[:4]) or 'TBD'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_data_models(arch) -> str:
        if not arch.data_models:
            return "  (none)"
        lines = []
        for dm in arch.data_models:
            field_str = ", ".join(
                f"{f.get('name')}:{f.get('type','any')}"
                for f in dm.fields[:6]
            )
            lines.append(f"  {dm.name}({field_str})")
        return "\n".join(lines)

    @staticmethod
    def _format_api_endpoints(arch) -> str:
        if not arch.api_endpoints:
            return "  (none)"
        return "\n".join(
            f"  {ep.method} {ep.path} — {ep.description}"
            for ep in arch.api_endpoints
        )

    @staticmethod
    def get_output(state: WorkflowState) -> Optional[PlannerOutput]:
        return state.__dict__.get("_planner_output")
