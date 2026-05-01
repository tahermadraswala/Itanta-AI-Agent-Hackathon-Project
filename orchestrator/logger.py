"""
orchestrator/logger.py
───────────────────────
Append-only, human-readable activity logger (NFR-02).

Every action taken by the framework — API calls, file writes, test runs,
checkpoint saves, human approvals — is written to a timestamped log file.
A structured JSON record is written in parallel so the summary module can
aggregate metrics without parsing free text.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class ActivityLogger:
    """
    Two-channel logger:
      1. Human-readable  → <log_dir>/activity.log
      2. Machine-readable → <log_dir>/activity.jsonl   (one JSON obj per line)
    """

    def __init__(self, log_dir: str = "./logs", run_id: str = "run") -> None:
        self._run_id   = run_id
        self._log_dir  = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._text_path = self._log_dir / "activity.log"
        self._json_path = self._log_dir / "activity.jsonl"

        # Configure stdlib logger that writes to file + console
        self._logger = logging.getLogger(f"itanta.{run_id}")
        self._logger.setLevel(logging.DEBUG)

        if not self._logger.handlers:
            # File handler — full detail
            fh = logging.FileHandler(self._text_path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(
                logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
            )
            self._logger.addHandler(fh)

            # Console handler — INFO and above only
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(
                logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                                  datefmt="%H:%M:%S")
            )
            self._logger.addHandler(ch)

    # ── Core logging methods ─────────────────────────────────

    def log(
        self,
        action: str,
        level: str = "INFO",
        stage: Optional[str] = None,
        agent: Optional[str] = None,
        task_id: Optional[str] = None,
        detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write one activity record to both channels."""
        record: Dict[str, Any] = {
            "ts":      datetime.utcnow().isoformat(),
            "run_id":  self._run_id,
            "level":   level.upper(),
            "action":  action,
        }
        if stage:    record["stage"]   = stage
        if agent:    record["agent"]   = agent
        if task_id:  record["task_id"] = task_id
        if detail:   record["detail"]  = detail
        if metadata: record["meta"]    = metadata

        # Human-readable via stdlib logger
        parts = [f"[{action}]"]
        if agent:   parts.append(f"agent={agent}")
        if stage:   parts.append(f"stage={stage}")
        if task_id: parts.append(f"task={task_id}")
        if detail:  parts.append(detail)
        message = "  ".join(parts)

        getattr(self._logger, level.lower(), self._logger.info)(message)

        # Machine-readable JSONL
        with open(self._json_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    # ── Convenience helpers ──────────────────────────────────

    def stage_entered(self, stage: str) -> None:
        self.log("STAGE_ENTER", stage=stage, detail=f"Entering stage: {stage}")

    def stage_exited(self, stage: str) -> None:
        self.log("STAGE_EXIT", stage=stage, detail=f"Exiting stage: {stage}")

    def agent_called(self, agent: str, task_id: Optional[str] = None) -> None:
        self.log("AGENT_CALLED", agent=agent, task_id=task_id)

    def agent_returned(self, agent: str, task_id: Optional[str] = None, success: bool = True) -> None:
        status = "OK" if success else "FAIL"
        self.log(f"AGENT_RETURN_{status}", agent=agent, task_id=task_id)

    def checkpoint_saved(self, checkpoint_id: str, trigger: str) -> None:
        self.log("CHECKPOINT_SAVED", detail=f"id={checkpoint_id} trigger={trigger}")

    def checkpoint_restored(self, checkpoint_id: str) -> None:
        self.log("CHECKPOINT_RESTORED", detail=f"id={checkpoint_id}", level="WARNING")

    def human_approval_requested(self, trigger: str) -> None:
        self.log("HUMAN_APPROVAL_REQUEST", detail=f"trigger={trigger}", level="WARNING")

    def human_approved(self, trigger: str) -> None:
        self.log("HUMAN_APPROVED", detail=f"trigger={trigger}")

    def human_rejected(self, trigger: str, reason: str = "") -> None:
        self.log("HUMAN_REJECTED", detail=f"trigger={trigger} reason={reason}", level="WARNING")

    def failure_recorded(self, failure_type: str, task_id: Optional[str] = None, message: str = "") -> None:
        self.log("FAILURE", level="ERROR", task_id=task_id,
                 detail=f"type={failure_type}  {message}")

    def retry_attempt(self, task_id: str, attempt: int, max_attempts: int) -> None:
        self.log("RETRY", level="WARNING", task_id=task_id,
                 detail=f"attempt {attempt}/{max_attempts}")

    def rollback_triggered(self, to_checkpoint: str) -> None:
        self.log("ROLLBACK", level="WARNING", detail=f"rolling back to checkpoint {to_checkpoint}")

    def escalation_triggered(self, reason: str) -> None:
        self.log("ESCALATION", level="ERROR", detail=reason)

    def api_call(self, model: str, tokens_approx: int = 0) -> None:
        self.log("LLM_CALL", detail=f"model={model} tokens≈{tokens_approx}")

    def file_written(self, path: str) -> None:
        self.log("FILE_WRITE", detail=path)

    def test_run(self, task_id: str, passed: bool, summary: str = "") -> None:
        level = "INFO" if passed else "ERROR"
        status = "PASS" if passed else "FAIL"
        self.log(f"TEST_{status}", level=level, task_id=task_id, detail=summary)

    def info(self, message: str) -> None:
        self.log("INFO", detail=message)

    def warning(self, message: str) -> None:
        self.log("WARNING", level="WARNING", detail=message)

    def error(self, message: str) -> None:
        self.log("ERROR", level="ERROR", detail=message)

    # ── Log path accessors ────────────────────────────────────

    @property
    def text_log_path(self) -> Path:
        return self._text_path

    @property
    def jsonl_log_path(self) -> Path:
        return self._json_path
