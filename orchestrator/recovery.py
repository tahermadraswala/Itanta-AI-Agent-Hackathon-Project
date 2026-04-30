"""
orchestrator/recovery.py
─────────────────────────
Recovery Agent — handles retries, rollback, and escalation (FR-15, FR-17).

Failure taxonomy (from Section 6 of the design document):
  ┌──────────────────────────┬────────────────────────────┬──────────────────┐
  │ Failure type             │ Detection                  │ Primary response │
  ├──────────────────────────┼────────────────────────────┼──────────────────┤
  │ Ambiguous requirements   │ Clarification stage        │ More questions   │
  │ Validation failure       │ Test/lint/type errors      │ Retry → code-gen │
  │ Tool / API failure       │ Timeout or API error       │ Retry w/ backoff │
  │ State inconsistency      │ Mismatch in saved state    │ Rollback         │
  │ Unsafe diff              │ Reviewer flags risk        │ Block + escalate │
  │ Max retries exceeded     │ Retry counter              │ Escalate         │
  └──────────────────────────┴────────────────────────────┴──────────────────┘
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

from models.workflow import (
    FailureRecord,
    FailureType,
    TaskStatus,
    WorkflowStage,
    WorkflowState,
    ImplementationTask,
)
from orchestrator.checkpoints import CheckpointManager
from orchestrator.logger import ActivityLogger


class RecoveryAgent:
    """
    Stateless agent called by the Orchestrator whenever a failure is detected.
    Returns a (resolved, escalated) tuple:
      • resolved=True  → caller may continue the workflow
      • resolved=False, escalated=False → caller should retry later
      • resolved=False, escalated=True  → human intervention required
    """

    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        logger: ActivityLogger,
        max_retries: int = 3,
        retry_backoff_seconds: float = 2.0,
        max_rollback_depth: int = 5,
    ) -> None:
        self._cp_mgr          = checkpoint_manager
        self._logger          = logger
        self._max_retries     = max_retries
        self._retry_backoff   = retry_backoff_seconds
        self._max_rollback    = max_rollback_depth

    # ── Entry point ───────────────────────────────────────────

    def handle(
        self,
        state: WorkflowState,
        failure: FailureRecord,
        retry_fn: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, bool]:
        """
        Route a failure to the appropriate handler.

        Parameters
        ----------
        state    : live WorkflowState (mutated in-place on rollback)
        failure  : the structured failure record
        retry_fn : callable that re-runs the failed operation; None = no retry

        Returns
        -------
        (resolved, escalated)
        """
        state.add_failure(failure)
        self._logger.failure_recorded(
            failure.failure_type.value,
            task_id=failure.task_id,
            message=failure.message,
        )

        handlers = {
            FailureType.AMBIGUOUS_REQUIREMENTS: self._handle_ambiguity,
            FailureType.VALIDATION_FAILURE:     self._handle_validation_failure,
            FailureType.TOOL_API_FAILURE:       self._handle_api_failure,
            FailureType.STATE_INCONSISTENCY:    self._handle_state_inconsistency,
            FailureType.UNSAFE_DIFF:            self._handle_unsafe_diff,
            FailureType.MAX_RETRIES_EXCEEDED:   self._handle_max_retries,
        }

        handler = handlers.get(failure.failure_type, self._handle_generic)
        resolved, escalated = handler(state, failure, retry_fn)

        if resolved:
            failure.resolved = True
        if escalated:
            failure.escalated = True
            self._logger.escalation_triggered(failure.message)

        return resolved, escalated

    # ── Specific handlers ─────────────────────────────────────

    def _handle_ambiguity(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        """Ambiguity is resolved by returning to the Clarifier — not an error."""
        self._logger.info("Ambiguity detected — returning to clarification stage.")
        state.current_stage = WorkflowStage.CLARIFICATION
        return True, False   # resolved by routing, not escalated

    def _handle_validation_failure(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        """
        Validation failures are retried by passing the error back to the
        code generation agent (FR-15).
        """
        task = self._find_task(state, failure.task_id)
        if task is None:
            return False, True   # can't find task → escalate

        if task.retry_count >= self._max_retries:
            self._logger.warning(
                f"Task {task.id} exceeded max retries ({self._max_retries})."
            )
            task.status = TaskStatus.FAILED
            return False, True   # escalate

        task.retry_count += 1
        self._logger.retry_attempt(task.id, task.retry_count, self._max_retries)
        self._sleep_with_backoff(task.retry_count)

        if retry_fn is not None:
            success = retry_fn()
            return success, False
        return False, False

    def _handle_api_failure(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        """Transient API failures use exponential back-off retry."""
        task = self._find_task(state, failure.task_id)
        retry_count = task.retry_count if task else 0

        if retry_count >= self._max_retries:
            return False, True  # escalate after max retries

        if task:
            task.retry_count += 1
            self._sleep_with_backoff(task.retry_count)
        else:
            self._sleep_with_backoff(1)

        if retry_fn:
            success = retry_fn()
            return success, False
        return False, False

    def _handle_state_inconsistency(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        """State inconsistency → rollback to last clean checkpoint."""
        return self._attempt_rollback(state, failure)

    def _handle_unsafe_diff(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        """Unsafe diff is always blocked and immediately escalated."""
        self._logger.warning(
            "Unsafe diff detected — blocking change and escalating to human."
        )
        # Mark the affected task as failed so the diff is not applied
        task = self._find_task(state, failure.task_id)
        if task:
            task.status = TaskStatus.FAILED
        return False, True   # escalate unconditionally

    def _handle_max_retries(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        """Max retries exceeded → attempt rollback, then escalate if needed."""
        resolved, escalated = self._attempt_rollback(state, failure)
        if not resolved:
            escalated = True
        return resolved, escalated

    def _handle_generic(
        self, state: WorkflowState, failure: FailureRecord, retry_fn
    ) -> Tuple[bool, bool]:
        self._logger.error(f"Unhandled failure type: {failure.failure_type}")
        return False, True

    # ── Rollback helper ───────────────────────────────────────

    def _attempt_rollback(
        self, state: WorkflowState, failure: FailureRecord
    ) -> Tuple[bool, bool]:
        """
        Walk back through checkpoints until we find one that pre-dates the
        failure, up to max_rollback_depth steps.
        """
        available = self._cp_mgr.checkpoint_count()
        if available == 0:
            self._logger.error("No checkpoints available for rollback — escalating.")
            return False, True

        depth = min(available, self._max_rollback)
        for n in range(1, depth + 1):
            result = self._cp_mgr.restore_nth_latest(state, n)
            if result is not None:
                self._logger.rollback_triggered(
                    f"Rolled back {n} checkpoint(s) — now at stage: {state.current_stage}"
                )
                return True, False

        self._logger.error("Rollback failed beyond max depth — escalating.")
        return False, True

    # ── Utilities ─────────────────────────────────────────────

    def _find_task(self, state: WorkflowState, task_id: Optional[str]):
        if state.plan is None or task_id is None:
            return None
        return next((t for t in state.plan.tasks if t.id == task_id), None)

    def _sleep_with_backoff(self, attempt: int) -> None:
        delay = self._retry_backoff * (2 ** (attempt - 1))
        self._logger.info(f"Back-off: sleeping {delay:.1f}s before retry …")
        time.sleep(delay)
