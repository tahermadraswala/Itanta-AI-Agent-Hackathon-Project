"""
agents/qa_agent.py
───────────────────
QA / TDD Agent — FR-11.

Responsibility:
  Write failing test cases BEFORE any production code is generated.
  This enforces the TDD-first requirement.

  For each task the Orchestrator hands over, this agent:
    1. Reads the task description and the spec's acceptance criteria.
    2. Generates a pytest test file with failing tests.
    3. Writes the test file to disk (inside the project working dir).
    4. Records the test file path on the task object.
"""
from __future__ import annotations

from pathlib import Path

from agents.base import BaseAgent
from models.workflow import ImplementationTask, TaskStatus, WorkflowState


_SYSTEM = (
    "You are the QA Agent (TDD) in a software development pipeline. "
    "You write pytest tests BEFORE production code exists. "
    "Tests must be failing initially (because no implementation exists yet). "
    "Write clear, focused tests — one test function per acceptance criterion. "
    "Use pytest fixtures, parametrize where appropriate. "
    "Import the module under test using a relative import; assume it will exist "
    "at the path specified in the task description."
)


class QAAgent(BaseAgent):

    def __init__(self, *args, project_dir: str = "./generated_project", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._project_dir = Path(project_dir)
        self._project_dir.mkdir(parents=True, exist_ok=True)
        (self._project_dir / "tests").mkdir(exist_ok=True)

    def run(self, state: WorkflowState) -> WorkflowState:
        """Run TDD for all pending tasks that don't yet have a test file."""
        if state.plan is None:
            return state

        for task in state.plan.tasks:
            if task.status == TaskStatus.PENDING and task.test_file is None:
                self._write_tests_for_task(state, task)

        state.record_api_call()
        return state

    def run_for_task(self, state: WorkflowState, task: ImplementationTask) -> WorkflowState:
        """Run TDD for a single specific task (called by the Orchestrator per-task)."""
        self._log_start(task_id=task.id)
        self._write_tests_for_task(state, task)
        state.record_api_call()
        self._log_end(success=(task.test_file is not None), task_id=task.id)
        return state

    # ── Private ────────────────────────────────────────────────

    def _write_tests_for_task(
        self, state: WorkflowState, task: ImplementationTask
    ) -> None:
        spec = state.spec
        criteria_text = ""
        if spec and spec.acceptance_criteria:
            criteria_text = "\n".join(f"- {c}" for c in spec.acceptance_criteria)

        files_text = ", ".join(task.estimated_files) if task.estimated_files else "TBD"

        prompt = f"""
Write a pytest test file for the following implementation task.

TASK:
  ID:          {task.id}
  Title:       {task.title}
  Description: {task.description}

FILES THIS TASK WILL CREATE:
  {files_text}

ACCEPTANCE CRITERIA:
{criteria_text}

Requirements:
- Each test must FAIL before implementation exists (use assertions that test real behaviour).
- Use `import pytest` and any standard library you need.
- Do NOT mock the entire module — test real logic.
- File should have a module docstring explaining what it tests.
- Function names must start with `test_`.

Return ONLY the Python source code for the test file. No markdown fences.
"""
        code = self._call_llm(prompt, system=_SYSTEM)
        code = self._strip_fences(code)

        test_filename = f"test_{task.id}.py"
        test_path = self._project_dir / "tests" / test_filename

        test_path.write_text(code, encoding="utf-8")
        task.test_file = str(test_path)
        self._logger.file_written(str(test_path))
        self._logger.info(
            f"TDD: wrote failing tests for task {task.id} → {test_path}"
        )

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove ```python … ``` fences if the model added them."""
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)
