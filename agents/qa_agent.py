"""
agents/qa_agent.py
───────────────────
QA / TDD Agent — FR-11.

Writes FAILING pytest test files BEFORE production code exists.
Each test file is generated via Gemini with full context:
  - Task details and acceptance test
  - Architecture data models and API endpoints
  - Acceptance criteria from the spec

Outputs:     QAOutput (models/schemas.py)
Prompt src:  agents/prompts/qa_prompts.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from agents.base import BaseAgent
from agents.architect import ArchitectAgent
from agents.prompts import qa_prompts as P
from models.schemas import QAOutput, TestCase, TestType
from models.workflow import ImplementationTask, TaskStatus, WorkflowState


class QAAgent(BaseAgent):

    def __init__(self, *args, project_dir: str = "./generated_project", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._project_dir = Path(project_dir)
        (self._project_dir / "tests").mkdir(parents=True, exist_ok=True)

    # ── Public interface ──────────────────────────────────────

    def run(self, state: WorkflowState) -> WorkflowState:
        """Write TDD tests for all PENDING tasks that have no test file yet."""
        if state.plan is None:
            return state
        for task in state.plan.tasks:
            if task.status == TaskStatus.PENDING and task.test_file is None:
                self.run_for_task(state, task)
        state.record_api_call()
        return state

    def run_for_task(
        self,
        state: WorkflowState,
        task: ImplementationTask,
        previous_content: str = "",
        error_output: str = "",
        production_code: str = "",
    ) -> WorkflowState:
        """
        Generate (or regenerate after failure) the test file for one task.
        Pass previous_content + error_output on retry.
        """
        self._log_start(task_id=task.id)

        arch = ArchitectAgent.get_output(state)
        spec = state.spec

        if previous_content and error_output:
            # Retry mode
            output = self._run_retry(task, previous_content, error_output, production_code)
        else:
            # Initial generation
            output = self._run_initial(task, state, arch, spec)

        errors = output.validate_completeness()
        if errors:
            self._logger.warning(f"QAOutput validation issues for {task.id}: {errors}")

        # Write file to disk
        if output.test_file_content:
            test_path = self._project_dir / output.test_file_path
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_text(output.test_file_content, encoding="utf-8")
            task.test_file = str(test_path)
            self._logger.file_written(str(test_path))
            self._logger.info(
                f"QA: wrote {len(output.test_cases)} test(s) for "
                f"{task.id} → {test_path.name}"
            )

        # Store QAOutput on state for downstream agents
        state.__dict__.setdefault("_qa_outputs", {})[task.id] = output

        state.record_api_call()
        self._log_end(success=bool(output.test_file_content), task_id=task.id)
        return state

    # ── Initial generation ────────────────────────────────────

    def _run_initial(self, task, state, arch, spec) -> QAOutput:
        # Derive module under test from first estimated file
        module_under_test = self._derive_module_path(task)

        data_models_text = self._format_data_models(arch, task)
        api_endpoints_text = self._format_api_endpoints(arch, task)
        acceptance_criteria_text = "\n".join(
            f"  - {c}" for c in (spec.acceptance_criteria if spec else [])
        )
        files_text = "\n".join(
            f"  - {f}" for f in task.estimated_files
        ) or "  (TBD)"

        acceptance_test = task.__dict__.get("acceptance_test", "Verify core functionality works.")

        prompt = P.MAIN_PROMPT_TEMPLATE.format(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            module_name=task.__dict__.get("module", "core"),
            risk_level=task.risk_level,
            estimated_files=files_text,
            acceptance_criteria=acceptance_criteria_text,
            acceptance_test=acceptance_test,
            module_under_test=module_under_test,
            data_models=data_models_text,
            api_endpoints=api_endpoints_text,
        )

        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        return self._parse_output(raw, task.id)

    # ── Retry mode ────────────────────────────────────────────

    def _run_retry(
        self,
        task: ImplementationTask,
        previous_content: str,
        error_output: str,
        production_code: str,
    ) -> QAOutput:
        prompt = P.RETRY_PROMPT_TEMPLATE.format(
            task_id=task.id,
            previous_test_content=previous_content[:3000],
            error_output=error_output[:2000],
            production_code=production_code[:3000],
        )
        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        return self._parse_output(raw, task.id)

    # ── Parsing ───────────────────────────────────────────────

    def _parse_output(self, raw: str, task_id: str) -> QAOutput:
        try:
            data = json.loads(raw)
            # Strip code fences from test_file_content if present
            content = data.get("test_file_content", "")
            content = self._strip_fences(content)

            test_cases = []
            for tc in data.get("test_cases", []):
                try:
                    test_type = TestType(tc.get("test_type", "unit"))
                except ValueError:
                    test_type = TestType.UNIT
                test_cases.append(TestCase(
                    function_name=tc.get("function_name", "test_unnamed"),
                    test_type=test_type,
                    description=tc.get("description", ""),
                    acceptance_criterion=tc.get("acceptance_criterion", ""),
                    should_fail_initially=bool(tc.get("should_fail_initially", True)),
                    fixtures_needed=tc.get("fixtures_needed", []),
                ))

            default_path = f"tests/test_{task_id}.py"
            return QAOutput(
                task_id=task_id,
                test_file_path=data.get("test_file_path", default_path),
                test_file_content=content,
                test_cases=test_cases,
                fixtures=data.get("fixtures", []),
                imports_required=data.get("imports_required", []),
                module_under_test=data.get("module_under_test", "src.core"),
                coverage_summary=data.get("coverage_summary", ""),
            )

        except (json.JSONDecodeError, TypeError, KeyError, Exception) as exc:
            self._logger.error(f"QAAgent parse error for {task_id}: {exc}")
            return QAOutput(
                task_id=task_id,
                test_file_path=f"tests/test_{task_id}.py",
                test_file_content="",
                test_cases=[],
                imports_required=[],
                module_under_test="src.core",
                coverage_summary="Parse error — no tests generated.",
            )

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _derive_module_path(task: ImplementationTask) -> str:
        if task.estimated_files:
            path = task.estimated_files[0]
            # Convert file path to python import path
            return (
                path.replace("/", ".")
                    .replace("\\", ".")
                    .removesuffix(".py")
            )
        return f"src.{task.__dict__.get('module', 'core')}"

    @staticmethod
    def _format_data_models(arch, task: ImplementationTask) -> str:
        if not arch or not arch.data_models:
            return "  (none)"
        return "\n".join(
            f"  {dm.name}: " + ", ".join(
                f"{f.get('name')}({f.get('type', 'any')})"
                for f in dm.fields[:5]
            )
            for dm in arch.data_models
        )

    @staticmethod
    def _format_api_endpoints(arch, task: ImplementationTask) -> str:
        if not arch or not arch.api_endpoints:
            return "  N/A"
        module = task.__dict__.get("module", "")
        relevant = [
            ep for ep in arch.api_endpoints
            if module.lower() in ep.path.lower() or module.lower() in ep.description.lower()
        ] or arch.api_endpoints[:3]
        return "\n".join(
            f"  {ep.method} {ep.path}: {ep.description}" for ep in relevant
        )

    @staticmethod
    def _strip_fences(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)

    @staticmethod
    def get_output(state: WorkflowState, task_id: str) -> Optional[QAOutput]:
        return state.__dict__.get("_qa_outputs", {}).get(task_id)
