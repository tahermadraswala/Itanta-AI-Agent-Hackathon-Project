"""
agents/coder.py
────────────────
Coder Agent — FR-08, FR-09.

Generates production Python code that makes pre-written TDD tests pass.
On retry, receives the error output from the previous run and fixes it.
Presents all changes as a unified diff BEFORE writing to disk.

Outputs:     CoderOutput (models/schemas.py)
Prompt src:  agents/prompts/coder_prompts.py
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import List, Optional

from agents.base import BaseAgent
from agents.architect import ArchitectAgent
from agents.qa_agent import QAAgent
from agents.prompts import coder_prompts as P
from models.schemas import CoderOutput, GeneratedFile
from models.workflow import DiffPayload, ImplementationTask, TaskStatus, WorkflowState


class CoderAgent(BaseAgent):

    def __init__(self, *args, project_dir: str = "./generated_project", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._project_dir = Path(project_dir)
        self._project_dir.mkdir(parents=True, exist_ok=True)

    # ── Public interface ──────────────────────────────────────

    def run(self, state: WorkflowState) -> WorkflowState:
        """Generate code for the first PENDING task in the plan."""
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
        lint_output: str = "",
        attempt_number: int = 1,
    ) -> WorkflowState:
        self._log_start(task_id=task.id)

        if task.test_file is None:
            self._logger.warning(
                f"CoderAgent: task {task.id} has no test file — skipping."
            )
            self._log_end(success=False, task_id=task.id)
            return state

        qa_output = QAAgent.get_output(state, task.id)
        test_content = (
            qa_output.test_file_content
            if qa_output and qa_output.test_file_content
            else Path(task.test_file).read_text(encoding="utf-8")
            if task.test_file and Path(task.test_file).exists()
            else ""
        )

        arch = ArchitectAgent.get_output(state)

        if error_output:
            # Retry: fix the broken code
            current_code_block = self._read_current_files(task)
            prompt = P.RETRY_PROMPT_TEMPLATE.format(
                task_id=task.id,
                attempt_number=attempt_number,
                max_retries=3,
                current_code_block=current_code_block[:4000],
                error_output=error_output[:2000],
                lint_output=lint_output[:500],
                error_summary=task.error_output or error_output[:500],
            )
        else:
            # Initial generation
            prompt = P.MAIN_PROMPT_TEMPLATE.format(
                task_id=task.id,
                task_title=task.title,
                task_description=task.description,
                module_name=task.__dict__.get("module", "core"),
                estimated_files="\n".join(
                    f"  - {f}" for f in task.estimated_files
                ) or "  (TBD by implementation)",
                test_file_content=test_content[:4000],
                data_models=self._format_data_models(arch),
                api_endpoints=self._format_api_endpoints(arch),
                module_public_interface=self._format_public_interface(arch, task),
                external_dependencies=self._format_dependencies(arch),
            )

        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        output = self._parse_output(raw, task.id)

        errors = output.validate_completeness()
        if errors:
            self._logger.warning(f"CoderOutput validation issues for {task.id}: {errors}")

        # Build diffs and attach to state
        for gf in output.generated_files:
            diff = self._make_diff(gf, self._project_dir)
            dp = DiffPayload(
                task_id=task.id,
                file_path=str(self._project_dir / gf.file_path),
                diff_text=diff,
                is_approved=False,
            )
            state.diffs.append(dp)

        task.diff_summary = (
            f"{len(output.generated_files)} file(s) changed"
        )
        task.code_file = (
            str(self._project_dir / output.generated_files[0].file_path)
            if output.generated_files else None
        )

        # Stash pending code on state; Orchestrator calls apply_code() after approval
        state.__dict__.setdefault("_pending_code", {})[task.id] = output

        state.record_api_call()
        self._log_end(success=bool(output.generated_files), task_id=task.id)
        return state

    def apply_code(self, task: ImplementationTask, state: WorkflowState) -> None:
        """
        Write all generated files to disk.
        Called by the Orchestrator ONLY after human diff approval.
        """
        output: Optional[CoderOutput] = state.__dict__.get("_pending_code", {}).get(task.id)
        if not output:
            return

        for gf in output.generated_files:
            dest = self._project_dir / gf.file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(gf.content, encoding="utf-8")
            self._logger.file_written(str(dest))
            state.total_files_generated += 1

        self._logger.info(
            f"Coder: applied {len(output.generated_files)} file(s) for task {task.id}."
        )

    # ── Parsing ───────────────────────────────────────────────

    def _parse_output(self, raw: str, task_id: str) -> CoderOutput:
        try:
            data = json.loads(raw)
            files: List[GeneratedFile] = []
            for gf in data.get("generated_files", []):
                content = self._strip_fences(gf.get("content", ""))
                files.append(GeneratedFile(
                    file_path=gf.get("file_path", f"src/{task_id}.py"),
                    content=content,
                    language=gf.get("language", "python"),
                    is_new=bool(gf.get("is_new", True)),
                    description=gf.get("description", ""),
                ))

            return CoderOutput(
                task_id=task_id,
                generated_files=files,
                implementation_notes=data.get("implementation_notes", ""),
                tests_expected_to_pass=data.get("tests_expected_to_pass", []),
                dependencies_added=data.get("dependencies_added", []),
                follow_up_tasks=data.get("follow_up_tasks", []),
            )

        except (json.JSONDecodeError, TypeError, KeyError, Exception) as exc:
            self._logger.error(f"CoderAgent parse error for {task_id}: {exc}")
            return CoderOutput(task_id=task_id, generated_files=[])

    # ── Diff generation ───────────────────────────────────────

    @staticmethod
    def _make_diff(gf: GeneratedFile, project_dir: Path) -> str:
        target = project_dir / gf.file_path
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        diff_lines = list(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                gf.content.splitlines(keepends=True),
                fromfile=f"a/{gf.file_path}",
                tofile=f"b/{gf.file_path}",
                lineterm="",
            )
        )
        return "\n".join(diff_lines) if diff_lines else f"(new file: {gf.file_path})"

    # ── Context helpers ───────────────────────────────────────

    def _read_current_files(self, task: ImplementationTask) -> str:
        blocks = []
        for fpath in task.estimated_files:
            p = self._project_dir / fpath
            if p.exists():
                blocks.append(f"# --- {fpath} ---\n{p.read_text(encoding='utf-8')}")
        return "\n\n".join(blocks) or "(no files exist yet)"

    @staticmethod
    def _format_data_models(arch) -> str:
        if not arch or not arch.data_models:
            return "  (none)"
        return "\n".join(
            f"  {dm.name}: " + ", ".join(
                f"{f.get('name')}({f.get('type','any')})" for f in dm.fields[:6]
            )
            for dm in arch.data_models
        )

    @staticmethod
    def _format_api_endpoints(arch) -> str:
        if not arch or not arch.api_endpoints:
            return "  (none)"
        return "\n".join(
            f"  {ep.method} {ep.path} — {ep.description}"
            for ep in arch.api_endpoints
        )

    @staticmethod
    def _format_public_interface(arch, task: ImplementationTask) -> str:
        if not arch:
            return "  (none)"
        module_name = task.__dict__.get("module", "")
        module = next(
            (m for m in arch.modules if m.name == module_name), None
        )
        if module:
            return "\n".join(f"  - {fn}" for fn in module.public_interface)
        return "  (see architecture for interface contracts)"

    @staticmethod
    def _format_dependencies(arch) -> str:
        if not arch or not arch.external_dependencies:
            return "  standard library only"
        return ", ".join(arch.external_dependencies)

    @staticmethod
    def _strip_fences(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)

    @staticmethod
    def get_output(state: WorkflowState, task_id: str) -> Optional[CoderOutput]:
        return state.__dict__.get("_pending_code", {}).get(task_id)
