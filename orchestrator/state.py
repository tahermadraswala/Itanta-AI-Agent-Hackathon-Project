"""
orchestrator/state.py
──────────────────────
WorkflowStateManager — owns the lifecycle of WorkflowState.

Responsibilities:
  • Advance the stage after each successful step.
  • Guard against illegal transitions (no skipping required stages).
  • Persist state between runs so a crash can be resumed.
  • Provide clean accessors used by the Router and agents.

The Orchestrator is the only entity that should call advance_stage();
agents may read state freely but never mutate the stage directly.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.workflow import (
    WorkflowStage,
    WorkflowState,
    ProjectSpec,
    ImplementationPlan,
)
from orchestrator.logger import ActivityLogger


# Ordered stage progression — the Orchestrator advances along this list.
# Recovery can step backwards by restoring checkpoints.
STAGE_ORDER = [
    WorkflowStage.INTAKE,
    WorkflowStage.CLARIFICATION,
    WorkflowStage.ARCHITECTURE,
    WorkflowStage.PLANNING,
    WorkflowStage.HUMAN_PLAN_APPROVAL,
    WorkflowStage.TDD,
    WorkflowStage.CODE_GEN,
    WorkflowStage.DIFF_REVIEW,
    WorkflowStage.VALIDATION,
    WorkflowStage.SECURITY,
    WorkflowStage.COMPLETE,
]


class WorkflowStateManager:
    """
    Creates, advances, and persists WorkflowState.

    Usage
    -----
        mgr = WorkflowStateManager(logger=logger)
        state = mgr.create("my-project", "Build a REST API …")
        mgr.advance(state)          # INTAKE → CLARIFICATION
        mgr.set_spec(state, spec)
        …
    """

    def __init__(
        self,
        state_dir: str = "./state",
        logger: Optional[ActivityLogger] = None,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logger

    # ── Lifecycle ─────────────────────────────────────────────

    def create(self, project_name: str, raw_input: str) -> WorkflowState:
        """Create a brand-new WorkflowState for a fresh run."""
        run_id = f"{project_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
        state = WorkflowState(
            run_id=run_id,
            project_name=project_name,
            current_stage=WorkflowStage.INTAKE,
        )
        # Seed the spec with the raw input
        state.spec = ProjectSpec(raw_input=raw_input)
        self._persist(state)
        if self._logger:
            self._logger.info(f"New workflow state created — run_id={run_id}")
        return state

    def load(self, run_id: str) -> WorkflowState:
        """Load a previously persisted state (for crash recovery / resume)."""
        path = self._state_dir / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No persisted state found for run_id={run_id}")
        with open(path, encoding="utf-8") as fh:
            return WorkflowState(**json.load(fh))

    def save(self, state: WorkflowState) -> None:
        """Persist the current state to disk."""
        self._persist(state)

    # ── Stage transitions ─────────────────────────────────────

    def advance(self, state: WorkflowState) -> WorkflowStage:
        """
        Move to the next stage in the pipeline.
        Raises ValueError if already at a terminal stage.
        """
        current = state.current_stage
        if current == WorkflowStage.COMPLETE:
            raise ValueError("Workflow is already complete.")
        if current == WorkflowStage.ABORTED:
            raise ValueError("Workflow was aborted — cannot advance.")

        if current in STAGE_ORDER:
            idx = STAGE_ORDER.index(current)
            if idx + 1 < len(STAGE_ORDER):
                new_stage = STAGE_ORDER[idx + 1]
            else:
                new_stage = WorkflowStage.COMPLETE
        else:
            # RECOVERY → return to validation
            new_stage = WorkflowStage.VALIDATION

        if self._logger:
            self._logger.stage_exited(current.value)
            self._logger.stage_entered(new_stage.value)

        state.current_stage = new_stage
        self._persist(state)
        return new_stage

    def jump_to(self, state: WorkflowState, stage: WorkflowStage) -> None:
        """
        Jump directly to a given stage.  Used by the Recovery agent after
        a rollback to re-enter from the correct position.
        """
        if self._logger:
            self._logger.info(
                f"Stage jump: {state.current_stage.value} → {stage.value}"
            )
        state.current_stage = stage
        self._persist(state)

    def abort(self, state: WorkflowState, reason: str = "") -> None:
        state.current_stage = WorkflowStage.ABORTED
        state.finished_at   = datetime.utcnow()
        if self._logger:
            self._logger.error(f"Workflow aborted. reason={reason}")
        self._persist(state)

    def complete(self, state: WorkflowState) -> None:
        state.current_stage = WorkflowStage.COMPLETE
        state.finished_at   = datetime.utcnow()
        if self._logger:
            self._logger.info("Workflow marked complete.")
        self._persist(state)

    # ── Setters ───────────────────────────────────────────────

    def set_spec(self, state: WorkflowState, spec: ProjectSpec) -> None:
        state.spec = spec
        self._persist(state)

    def set_plan(self, state: WorkflowState, plan: ImplementationPlan) -> None:
        state.plan = plan
        self._persist(state)

    def increment_api_calls(self, state: WorkflowState, count: int = 1) -> None:
        state.api_call_count += count
        self._persist(state)

    def increment_files(self, state: WorkflowState, count: int = 1) -> None:
        state.total_files_generated += count
        self._persist(state)

    # ── Private ───────────────────────────────────────────────

    def _persist(self, state: WorkflowState) -> None:
        path = self._state_dir / f"{state.run_id}.json"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(state.model_dump_json(indent=2))
