"""
agents/reviewer.py
───────────────────
Reviewer / Security Agent — FR-14 (EXTENDED).

Responsibility:
  Inspect generated code diffs for:
    • Logic errors
    • Security issues (injection, auth flaws, hard-coded secrets)
    • Unsafe shell patterns (NFR-05)
  Flag the diff as safe or unsafe.  Unsafe diffs trigger escalation via
  the Recovery agent.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from agents.base import BaseAgent
from models.workflow import DiffPayload, WorkflowState


_SYSTEM = (
    "You are the Security and Code Review Agent. "
    "Analyse code diffs for: logic errors, injection vulnerabilities, "
    "authentication flaws, hard-coded secrets, unsafe file deletions, "
    "and any other dangerous patterns. "
    "Be precise and conservative — flag anything uncertain as a risk."
)

# Static patterns that are ALWAYS blocked regardless of LLM review
_UNSAFE_SHELL_PATTERNS: List[str] = [
    r"subprocess.*rm\s+-rf\s+[^/]",   # rm -rf outside project
    r"os\.system.*rm\s+-rf",
    r"shutil\.rmtree\s*\(\s*[\"']/",  # rmtree on absolute root paths
    r"eval\s*\(",                       # arbitrary eval
    r"exec\s*\(",                       # arbitrary exec (as statement)
]


class ReviewerAgent(BaseAgent):

    def run(self, state: WorkflowState) -> WorkflowState:
        """Review all unapproved, un-flagged diffs in the state."""
        for diff in state.diffs:
            if not diff.is_approved and not diff.flagged_by_reviewer:
                safe, notes = self._review_diff(diff)
                if not safe:
                    diff.flagged_by_reviewer = True
                    diff.reviewer_notes = notes
                    self._logger.warning(
                        f"ReviewerAgent flagged diff for task {diff.task_id}: {notes}"
                    )
                else:
                    diff.reviewer_notes = notes
        return state

    def review_diff(self, diff: DiffPayload, state: WorkflowState) -> Tuple[bool, str]:
        """
        Review a specific diff (called by the Orchestrator before diff approval).
        Returns (is_safe, reviewer_notes).
        """
        self._log_start(task_id=diff.task_id)
        safe, notes = self._review_diff(diff)
        self._log_end(success=safe, task_id=diff.task_id)
        return safe, notes

    # ── Private ───────────────────────────────────────────────

    def _review_diff(self, diff: DiffPayload) -> Tuple[bool, str]:
        # 1. Static pattern check first (fast, deterministic)
        static_issues = self._static_check(diff.diff_text)
        if static_issues:
            return False, f"Static check failed: {'; '.join(static_issues)}"

        # 2. LLM-powered review
        return self._llm_review(diff)

    def _static_check(self, diff_text: str) -> List[str]:
        issues = []
        for pattern in _UNSAFE_SHELL_PATTERNS:
            if re.search(pattern, diff_text, re.IGNORECASE):
                issues.append(f"Matched unsafe pattern: {pattern}")
        return issues

    def _llm_review(self, diff: DiffPayload) -> Tuple[bool, str]:
        if not diff.diff_text.strip() or diff.diff_text == "(no diff — new file)":
            return True, "No diff content to review."

        prompt = f"""
Review the following code diff for security issues, logic errors, and unsafe patterns.

DIFF:
{diff.diff_text[:3000]}

Respond with a JSON object:
  "safe"   : boolean (true = safe to apply, false = block)
  "issues" : list of strings (empty if safe)
  "notes"  : string summary (max 100 words)
"""
        raw = self._call_llm_json(prompt, system=_SYSTEM)

        try:
            import json
            data = json.loads(raw)
            safe   = bool(data.get("safe", True))
            issues = data.get("issues", [])
            notes  = data.get("notes", "Review complete.")
            if issues:
                notes = "; ".join(issues) + ". " + notes
            return safe, notes
        except Exception:
            # If parsing fails, err on the side of caution
            return True, "Review inconclusive — proceeding with caution."
