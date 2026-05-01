"""
agents/reviewer.py
───────────────────
Reviewer / Security Agent — FR-14 (EXTENDED).

Two-layer review:
  Layer 1 — Static pattern matching (fast, deterministic, no LLM call).
             Runs BEFORE the LLM to catch hard blockers immediately.
  Layer 2 — LLM-powered semantic security + quality review.

Outputs:     ReviewerOutput (models/schemas.py)
Prompt src:  agents/prompts/reviewer_prompts.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from agents.base import BaseAgent
from agents.prompts import reviewer_prompts as P
from models.schemas import (
    CodeQualityNote,
    ReviewerOutput,
    SecurityIssue,
    SecuritySeverity,
)
from models.workflow import DiffPayload, WorkflowState


# ── Static blocked patterns (NFR-05 + general safety) ────────

_BLOCKED_PATTERNS: List[Tuple[str, str, str]] = [
    # (regex pattern, reason, cwe_id)
    (r"subprocess\.[a-z_]+\(.*shell\s*=\s*True", "shell=True in subprocess call", "CWE-78"),
    (r"os\.system\s*\(", "os.system() call", "CWE-78"),
    (r"os\.popen\s*\(", "os.popen() call", "CWE-78"),
    (r"eval\s*\(\s*[^)]*input", "eval() on user input", "CWE-95"),
    (r"exec\s*\(\s*[^)]*input", "exec() on user input", "CWE-95"),
    (r"__import__\s*\(", "dynamic __import__()", "CWE-95"),
    (r"shutil\.rmtree\s*\(\s*['\"/]", "rmtree on root/absolute path", "CWE-73"),
    (r"rm\s+-rf\s+/", "rm -rf / in shell command", "CWE-73"),
    (r"(password|secret|api_key|token)\s*=\s*['\"][a-zA-Z0-9+/]{8,}", "Potential hard-coded secret", "CWE-798"),
    (r"GEMINI_API_KEY\s*=\s*['\"][A-Za-z0-9]", "Hard-coded Gemini API key", "CWE-798"),
    (r"sqlite3\.connect.*execute.*%[^)]*%", "Possible SQL injection via %s formatting", "CWE-89"),
    (r'cursor\.execute\s*\(\s*f["\']', "SQL injection via f-string", "CWE-89"),
    (r'cursor\.execute\s*\(\s*["\'].*\+', "SQL injection via string concat", "CWE-89"),
]


class ReviewerAgent(BaseAgent):

    def run(self, state: WorkflowState) -> WorkflowState:
        """Review all unapproved diffs in state."""
        for diff in state.diffs:
            if not diff.is_approved and not diff.flagged_by_reviewer:
                output = self._review(diff, state)
                if not output.is_safe_to_apply:
                    diff.flagged_by_reviewer = True
                    diff.reviewer_notes = output.reviewer_notes or output.diff_summary
        return state

    def review_diff(
        self, diff: DiffPayload, state: WorkflowState
    ) -> Tuple[bool, str, ReviewerOutput]:
        """
        Review a specific diff — called by the Orchestrator before approval.

        Returns:
            (is_safe, reviewer_notes_summary, full_ReviewerOutput)
        """
        self._log_start(task_id=diff.task_id)
        output = self._review(diff, state)
        state.__dict__.setdefault("_review_outputs", {})[diff.task_id] = output
        is_safe = output.is_safe_to_apply and not output.has_blocking_issues()
        notes = self._build_notes_summary(output)
        state.record_api_call()
        self._log_end(success=is_safe, task_id=diff.task_id)
        return is_safe, notes, output

    def audit_module(
        self, module_name: str, task_ids: List[str], state: WorkflowState
    ) -> ReviewerOutput:
        """
        Full security audit of a completed module (FR-14 extended).
        Called by the Orchestrator after all tasks in a module are complete.
        """
        self._log_start()
        files_block = self._build_file_contents_block(module_name, task_ids, state)
        spec = state.spec
        criteria = "\n".join(
            f"  - {c}" for c in (spec.acceptance_criteria if spec else [])
        )

        prompt = P.MODULE_AUDIT_PROMPT_TEMPLATE.format(
            module_name=module_name,
            task_ids=", ".join(task_ids),
            file_contents_block=files_block[:6000],
            acceptance_criteria=criteria,
        )
        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        output = self._parse_output(raw, f"{module_name}_audit")
        state.record_api_call()
        self._log_end(success=True)
        return output

    # ── Internal review pipeline ──────────────────────────────

    def _review(self, diff: DiffPayload, state: WorkflowState) -> ReviewerOutput:
        """Layer 1 (static) → Layer 2 (LLM) pipeline."""
        # Layer 1: static check
        static_passed, blocked = self._static_check(diff.diff_text)

        if not static_passed:
            # Hard block — skip LLM to save API calls
            return ReviewerOutput(
                task_id=diff.task_id,
                is_safe_to_apply=False,
                security_issues=[
                    SecurityIssue(
                        severity=SecuritySeverity.CRITICAL,
                        category="file_safety",
                        location=diff.file_path,
                        description=f"Blocked pattern detected: {p}",
                        recommendation="Remove the unsafe pattern entirely.",
                        cwe_id=cwe,
                        auto_fixable=False,
                    )
                    for p, cwe in blocked
                ],
                static_check_passed=False,
                diff_summary="Blocked by static pattern check.",
                recommendation="reject",
                reviewer_notes="Static analysis found critical patterns. Change rejected.",
                blocked_patterns_found=[p for p, _ in blocked],
            )

        # Layer 2: LLM review
        return self._llm_review(diff, state, static_passed)

    def _static_check(self, diff_text: str) -> Tuple[bool, List[Tuple[str, str]]]:
        """
        Check diff against the blocked pattern list.
        Returns (passed, [(matched_pattern, cwe_id), ...]).
        """
        found = []
        for pattern, reason, cwe in _BLOCKED_PATTERNS:
            if re.search(pattern, diff_text, re.IGNORECASE):
                found.append((reason, cwe))
        return (len(found) == 0), found

    def _llm_review(
        self, diff: DiffPayload, state: WorkflowState, static_passed: bool
    ) -> ReviewerOutput:
        # Read the full file if it exists (for context beyond the diff)
        full_content = ""
        if diff.file_path and Path(diff.file_path).exists():
            try:
                full_content = Path(diff.file_path).read_text(encoding="utf-8")[:3000]
            except OSError:
                pass

        # Determine module and risk from state
        task_risk = "medium"
        module_name = ""
        if state.plan:
            task = next((t for t in state.plan.tasks if t.id == diff.task_id), None)
            if task:
                task_risk = task.risk_level
                module_name = task.__dict__.get("module", "")

        prompt = P.DIFF_REVIEW_PROMPT_TEMPLATE.format(
            task_id=diff.task_id,
            module_name=module_name or "unknown",
            risk_level=task_risk,
            diff_content=diff.diff_text[:4000],
            full_file_content=full_content,
        )
        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        output = self._parse_output(raw, diff.task_id)
        output.static_check_passed = static_passed
        return output

    # ── Parsing ───────────────────────────────────────────────

    def _parse_output(self, raw: str, task_id: str) -> ReviewerOutput:
        try:
            data = json.loads(raw)

            security_issues: List[SecurityIssue] = []
            for issue in data.get("security_issues", []):
                try:
                    severity = SecuritySeverity(issue.get("severity", "low"))
                except ValueError:
                    severity = SecuritySeverity.LOW
                security_issues.append(SecurityIssue(
                    severity=severity,
                    category=issue.get("category", "other"),
                    location=issue.get("location", "unknown"),
                    description=issue.get("description", ""),
                    recommendation=issue.get("recommendation", ""),
                    cwe_id=issue.get("cwe_id"),
                    auto_fixable=bool(issue.get("auto_fixable", False)),
                ))

            quality_notes: List[CodeQualityNote] = []
            for note in data.get("quality_notes", []):
                quality_notes.append(CodeQualityNote(
                    category=note.get("category", "maintainability"),
                    location=note.get("location", ""),
                    note=note.get("note", ""),
                    suggestion=note.get("suggestion", ""),
                ))

            rec = data.get("recommendation", "approve")
            if rec not in ("approve", "approve_with_notes", "reject", "escalate"):
                rec = "approve_with_notes"

            return ReviewerOutput(
                task_id=task_id,
                is_safe_to_apply=bool(data.get("is_safe_to_apply", True)),
                security_issues=security_issues,
                quality_notes=quality_notes,
                static_check_passed=bool(data.get("static_check_passed", True)),
                diff_summary=data.get("diff_summary", "No summary available."),
                recommendation=rec,
                reviewer_notes=data.get("reviewer_notes", ""),
                blocked_patterns_found=data.get("blocked_patterns_found", []),
            )

        except (json.JSONDecodeError, TypeError, KeyError, Exception) as exc:
            self._logger.error(f"ReviewerAgent parse error for {task_id}: {exc}")
            # Safe default — uncertain output → approve_with_notes
            return ReviewerOutput(
                task_id=task_id,
                is_safe_to_apply=True,
                static_check_passed=True,
                diff_summary="Review inconclusive — proceeding with caution.",
                recommendation="approve_with_notes",
                reviewer_notes=f"Parse error during review: {exc}",
            )

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_notes_summary(output: ReviewerOutput) -> str:
        if not output.security_issues and not output.blocked_patterns_found:
            return f"Review: {output.recommendation}. {output.diff_summary}"
        issues_text = "; ".join(
            f"[{i.severity.value.upper()}] {i.description}"
            for i in output.security_issues[:3]
        )
        return f"Review: {output.recommendation}. Issues: {issues_text}"

    def _build_file_contents_block(
        self, module_name: str, task_ids: List[str], state: WorkflowState
    ) -> str:
        blocks = []
        for task_id in task_ids:
            coder_output = state.__dict__.get("_pending_code", {}).get(task_id)
            if coder_output:
                for gf in coder_output.generated_files:
                    blocks.append(f"# === {gf.file_path} ===\n{gf.content[:1000]}")
        return "\n\n".join(blocks) or "(no file contents available)"

    @staticmethod
    def get_output(state: WorkflowState, task_id: str) -> Optional[ReviewerOutput]:
        return state.__dict__.get("_review_outputs", {}).get(task_id)
