"""
orchestrator/checkpoints.py
────────────────────────────
Checkpoint creation, persistence, and restoration (FR-17).

Design decisions:
  • Each checkpoint is a full JSON snapshot of WorkflowState at a specific
    control point.  This is intentionally verbose — correctness > storage.
  • Checkpoints are written atomically (write to tmp, then rename) so a
    crash mid-write never leaves a corrupt checkpoint file.
  • The CheckpointManager keeps an in-memory index so restores are O(1).
  • Only the Orchestrator calls save/restore; agents never touch checkpoints
    directly.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models.workflow import (
    CheckpointRecord,
    CheckpointTrigger,
    WorkflowStage,
    WorkflowState,
)
from orchestrator.logger import ActivityLogger


class CheckpointManager:
    """
    Saves and restores workflow state snapshots.

    Directory layout:
        <checkpoint_dir>/
            <run_id>/
                <checkpoint_id>.json
                index.json            ← ordered list of checkpoint ids
    """

    def __init__(
        self,
        checkpoint_dir: str = "./checkpoints",
        run_id: str = "run",
        logger: Optional[ActivityLogger] = None,
    ) -> None:
        self._base_dir  = Path(checkpoint_dir) / run_id
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base_dir / "index.json"
        self._logger     = logger
        self._index: List[str] = self._load_index()

    # ── Public interface ──────────────────────────────────────

    def save(
        self,
        state: WorkflowState,
        trigger: CheckpointTrigger,
    ) -> CheckpointRecord:
        """Snapshot current WorkflowState; return the CheckpointRecord."""
        cp_id = f"cp_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        record = CheckpointRecord(
            id=cp_id,
            trigger=trigger,
            stage=state.current_stage,
            task_snapshot=list(state.plan.tasks) if state.plan else [],
            spec_snapshot=state.spec,
            metadata={
                "api_call_count":        state.api_call_count,
                "total_files_generated": state.total_files_generated,
                "failure_count":         len(state.failures),
            },
        )

        # Add the record to the live state's checkpoint list
        state.checkpoints.append(record)

        # Persist to disk (atomic write)
        self._atomic_write(cp_id, state)

        # Update the index
        self._index.append(cp_id)
        self._save_index()

        if self._logger:
            self._logger.checkpoint_saved(cp_id, trigger.value)

        return record

    def restore(
        self,
        state: WorkflowState,
        checkpoint_id: str,
    ) -> WorkflowState:
        """
        Load a previously saved snapshot and overwrite the relevant fields of
        the live state.  Returns the (mutated) state for convenience.
        """
        cp_path = self._base_dir / f"{checkpoint_id}.json"
        if not cp_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")

        with open(cp_path, encoding="utf-8") as fh:
            raw: Dict = json.load(fh)

        saved_state = WorkflowState(**raw)

        # Restore mutable fields only — keep run metadata intact
        state.current_stage         = saved_state.current_stage
        state.spec                  = saved_state.spec
        state.plan                  = saved_state.plan
        state.diffs                 = saved_state.diffs
        state.validation_results    = saved_state.validation_results
        state.failures              = saved_state.failures
        state.api_call_count        = saved_state.api_call_count
        state.total_files_generated = saved_state.total_files_generated

        if self._logger:
            self._logger.checkpoint_restored(checkpoint_id)

        return state

    def restore_latest(self, state: WorkflowState) -> Optional[WorkflowState]:
        """Restore the most recent checkpoint.  Returns None if none exist."""
        if not self._index:
            return None
        return self.restore(state, self._index[-1])

    def restore_nth_latest(
        self, state: WorkflowState, n: int = 1
    ) -> Optional[WorkflowState]:
        """
        Restore n checkpoints back from the current head (1 = most recent).
        Used by the Recovery agent to roll back multiple steps.
        """
        if len(self._index) < n:
            return None
        target_id = self._index[-(n)]
        return self.restore(state, target_id)

    def list_checkpoints(self) -> List[str]:
        """Return ordered list of all checkpoint IDs for this run."""
        return list(self._index)

    def checkpoint_count(self) -> int:
        return len(self._index)

    # ── Private helpers ───────────────────────────────────────

    def _atomic_write(self, cp_id: str, state: WorkflowState) -> None:
        """Write state JSON to a temp file then rename (atomic on POSIX)."""
        target_path = self._base_dir / f"{cp_id}.json"
        dir_fd = os.open(str(self._base_dir), os.O_RDONLY)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=str(self._base_dir),
                delete=False,
                suffix=".tmp",
                encoding="utf-8",
            ) as tmp:
                tmp.write(state.model_dump_json(indent=2))
                tmp_path = tmp.name
            os.replace(tmp_path, target_path)
            # fsync the directory to flush the rename
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _load_index(self) -> List[str]:
        if self._index_path.exists():
            with open(self._index_path, encoding="utf-8") as fh:
                return json.load(fh)
        return []

    def _save_index(self) -> None:
        with open(self._index_path, "w", encoding="utf-8") as fh:
            json.dump(self._index, fh, indent=2)
