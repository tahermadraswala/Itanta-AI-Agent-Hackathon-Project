"""
orchestrator/summary.py
────────────────────────
Final Workflow Summary Report generator (NFR-06, Section 8 of problem statement).

Produces:
  • A human-readable Markdown summary  → <log_dir>/workflow_summary.md
  • A machine-readable JSON report      → <log_dir>/workflow_summary.json

Contents:
  • Tasks completed / skipped / failed
  • Files generated
  • Tests passed / failed
  • Total API calls made
  • Failure history
  • Checkpoint history
  • Total wall-clock duration
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from models.workflow import TaskStatus, WorkflowState


class SummaryGenerator:

    def __init__(self, output_dir: str = "./logs") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public ────────────────────────────────────────────────

    def generate(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Build the summary dict, write both output files, and return the dict.
        """
        summary = self._build_summary(state)
        self._write_json(summary)
        self._write_markdown(summary, state)
        return summary

    # ── Building ─────────────────────────────────────────────

    def _build_summary(self, state: WorkflowState) -> Dict[str, Any]:
        tasks = state.plan.tasks if state.plan else []

        completed   = [t for t in tasks if t.status == TaskStatus.PASSED]
        failed      = [t for t in tasks if t.status == TaskStatus.FAILED]
        skipped     = [t for t in tasks if t.status == TaskStatus.SKIPPED]
        rolled_back = [t for t in tasks if t.status == TaskStatus.ROLLED_BACK]

        val_results  = state.validation_results
        tests_passed = sum(1 for v in val_results if v.passed)
        tests_failed = sum(1 for v in val_results if not v.passed)

        duration_secs: float = 0.0
        if state.finished_at and state.started_at:
            duration_secs = (state.finished_at - state.started_at).total_seconds()

        failures_summary = [
            {
                "type":      f.failure_type.value,
                "task_id":   f.task_id,
                "stage":     f.stage.value,
                "message":   f.message,
                "resolved":  f.resolved,
                "escalated": f.escalated,
            }
            for f in state.failures
        ]

        checkpoints_summary = [
            {
                "id":      cp.id,
                "trigger": cp.trigger.value,
                "stage":   cp.stage.value,
                "saved_at": cp.created_at.isoformat(),
            }
            for cp in state.checkpoints
        ]

        return {
            "run_id":           state.run_id,
            "project_name":     state.project_name,
            "final_stage":      state.current_stage.value,
            "started_at":       state.started_at.isoformat(),
            "finished_at":      state.finished_at.isoformat() if state.finished_at else None,
            "duration_seconds": round(duration_secs, 2),
            "tasks": {
                "total":       len(tasks),
                "completed":   len(completed),
                "failed":      len(failed),
                "skipped":     len(skipped),
                "rolled_back": len(rolled_back),
                "details":     [
                    {
                        "id":          t.id,
                        "title":       t.title,
                        "status":      t.status.value,
                        "retry_count": t.retry_count,
                    }
                    for t in tasks
                ],
            },
            "files_generated":  state.total_files_generated,
            "tests": {
                "total":  tests_passed + tests_failed,
                "passed": tests_passed,
                "failed": tests_failed,
                "pass_rate": (
                    f"{tests_passed / (tests_passed + tests_failed) * 100:.1f}%"
                    if (tests_passed + tests_failed) > 0 else "N/A"
                ),
            },
            "api_calls_total":  state.api_call_count,
            "failures":         failures_summary,
            "checkpoints":      checkpoints_summary,
            "spec_approved":    state.spec.is_approved if state.spec else False,
            "plan_approved":    state.plan.is_approved if state.plan else False,
        }

    # ── Output writers ────────────────────────────────────────

    def _write_json(self, summary: Dict[str, Any]) -> None:
        path = self._output_dir / "workflow_summary.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)

    def _write_markdown(self, summary: Dict[str, Any], state: WorkflowState) -> None:
        path = self._output_dir / "workflow_summary.md"
        lines = [
            "# Itanta AI Agent Hackathon 2026 — Workflow Summary Report",
            "",
            f"**Project:** {summary['project_name']}  ",
            f"**Run ID:**  `{summary['run_id']}`  ",
            f"**Status:**  `{summary['final_stage'].upper()}`  ",
            f"**Duration:** {summary['duration_seconds']}s  ",
            f"**Started:**  {summary['started_at']}  ",
            f"**Finished:** {summary['finished_at'] or 'N/A'}  ",
            "",
            "---",
            "",
            "## Tasks",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total      | {summary['tasks']['total']} |",
            f"| Completed  | {summary['tasks']['completed']} |",
            f"| Failed     | {summary['tasks']['failed']} |",
            f"| Skipped    | {summary['tasks']['skipped']} |",
            f"| Rolled back| {summary['tasks']['rolled_back']} |",
            "",
        ]

        if summary["tasks"]["details"]:
            lines += [
                "### Task Breakdown",
                "",
                "| # | Title | Status | Retries |",
                "|---|-------|--------|---------|",
            ]
            for t in summary["tasks"]["details"]:
                lines.append(
                    f"| {t['id']} | {t['title']} | `{t['status']}` | {t['retry_count']} |"
                )
            lines.append("")

        lines += [
            "---",
            "",
            "## Test Results",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Tests run    | {summary['tests']['total']} |",
            f"| Passed       | {summary['tests']['passed']} |",
            f"| Failed       | {summary['tests']['failed']} |",
            f"| Pass rate    | {summary['tests']['pass_rate']} |",
            "",
            "---",
            "",
            "## Infrastructure",
            "",
            f"- **Files generated:** {summary['files_generated']}",
            f"- **Total LLM API calls:** {summary['api_calls_total']}",
            f"- **Spec approved:** {'✅' if summary['spec_approved'] else '❌'}",
            f"- **Plan approved:** {'✅' if summary['plan_approved'] else '❌'}",
            f"- **Checkpoints saved:** {len(summary['checkpoints'])}",
            "",
        ]

        if summary["failures"]:
            lines += [
                "---",
                "",
                "## Failures",
                "",
                "| Type | Task | Stage | Resolved | Escalated |",
                "|------|------|-------|----------|-----------|",
            ]
            for f in summary["failures"]:
                lines.append(
                    f"| `{f['type']}` | {f['task_id'] or '-'} | {f['stage']} "
                    f"| {'✅' if f['resolved'] else '❌'} | {'⚠️' if f['escalated'] else '-'} |"
                )
            lines.append("")

        if summary["checkpoints"]:
            lines += [
                "---",
                "",
                "## Checkpoints",
                "",
                "| ID | Trigger | Stage | Saved At |",
                "|----|---------|-------|----------|",
            ]
            for cp in summary["checkpoints"]:
                lines.append(
                    f"| `{cp['id']}` | {cp['trigger']} | {cp['stage']} | {cp['saved_at']} |"
                )
            lines.append("")

        lines += [
            "---",
            "",
            "*Generated by Team Intent — Itanta AI Agent Hackathon 2026*",
        ]

        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
