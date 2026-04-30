"""
agents/coder.py
────────────────
Coder Agent — FR-08, FR-09.

Responsibility:
  Generate production code for a task — BUT ONLY after tests exist (FR-08).
  Present the change as a diff/summary before writing to disk (FR-09).
  Never execute shell commands that delete files outside the project dir (NFR-05).
"""
from __future__ import annotations

import difflib
from pathlib import Path

from agents.base import BaseAgent
from models.workflow import DiffPayload, ImplementationTask, TaskStatus, WorkflowState


_SYSTEM = (
    "You are the Coder Agent in a software development pipeline. "
    "You receive a task description, the existing tests, and the current project state. "
    "Your job is to generate production Python code that makes the tests pass. "
    "Follow PEP-8. Use type hints. Write docstrings. "
    "Return ONLY the Python source code — no markdown fences, no explanation."
)


class CoderAgent(BaseAgent):

    def __init__(self, *args, project_dir: str = "./generated_project", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._project_dir = Path(project_dir)
        self._project_dir.mkdir(parents=True, exist_ok=True)

    def run(self, state: WorkflowState) -> WorkflowState:
        """Generate code for the next PENDING task in the plan."""
        if state.plan is None:
            return state
        pending = state.plan.pending_tasks()
        if pending:
            self.run_for_task(state, pending[0])
        return state

    def run_for_task(
        self,
        state: WorkflowState,
        task: ImplementationTask,
        error_output: str = "",
    ) -> WorkflowState:
        """
        Generate (or regenerate after failure) code for a specific task.
        error_output is passed on retry so the model knows what went wrong.
        """
        self._log_start(task_id=task.id)

        if task.test_file is None:
            self._logger.warning(
                f"CoderAgent: task {task.id} has no test file yet — skipping."
            )
            self._log_end(success=False, task_id=task.id)
            return state

        # Read the test file so the model knows what it must satisfy
        test_code = Path(task.test_file).read_text(encoding="utf-8") if Path(task.test_file).exists() else ""

        # Determine the output file path (first estimated file, or derive from task id)
        if task.estimated_files:
            output_path = self._project_dir / task.estimated_files[0]
        else:
            output_path = self._project_dir / "src" / f"{task.id}.py"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing content for diff generation
        existing_code = output_path.read_text(encoding="utf-8") if output_path.exists() else ""

        retry_context = ""
        if error_output:
            retry_context = f"\n\nPREVIOUS ATTEMPT FAILED WITH:\n{error_output}\n\nFix the above errors."

        prompt = f"""
Generate Python code for the following task.

TASK:
  ID:          {task.id}
  Title:       {task.title}
  Description: {task.description}

TARGET FILE: {output_path.relative_to(self._project_dir)}

TESTS THAT MUST PASS:
```python
{test_code}
```
{retry_context}

Return ONLY the Python source code. No markdown fences. No explanation.
"""
        new_code = self._call_llm(prompt, system=_SYSTEM)
        new_code = self._strip_fences(new_code)

        # Generate a unified diff for the reviewer / human approval
        diff = self._make_diff(
            existing_code, new_code,
            from_file=f"a/{output_path.name}",
            to_file=f"b/{output_path.name}",
        )

        diff_payload = DiffPayload(
            task_id=task.id,
            file_path=str(output_path),
            diff_text=diff,
            is_approved=False,
        )
        state.diffs.append(diff_payload)
        task.diff_summary = diff[:500] + ("…" if len(diff) > 500 else "")
        task.code_file    = str(output_path)

        # Store the new code on the task so the Orchestrator can apply it after approval
        task.__dict__["_pending_code"] = new_code

        state.record_api_call()
        self._log_end(success=True, task_id=task.id)
        return state

    def apply_code(self, task: ImplementationTask, state: WorkflowState) -> None:
        """
        Write the generated code to disk.
        Called by the Orchestrator AFTER human diff approval.
        """
        pending_code = task.__dict__.get("_pending_code", "")
        if not pending_code or not task.code_file:
            return

        code_path = Path(task.code_file)
        code_path.parent.mkdir(parents=True, exist_ok=True)
        code_path.write_text(pending_code, encoding="utf-8")

        self._logger.file_written(str(code_path))
        state.total_files_generated += 1

    # ── Utilities ─────────────────────────────────────────────

    @staticmethod
    def _make_diff(old: str, new: str, from_file: str, to_file: str) -> str:
        diff_lines = list(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=from_file,
                tofile=to_file,
            )
        )
        return "".join(diff_lines) if diff_lines else "(no diff — new file)"

    @staticmethod
    def _strip_fences(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)
