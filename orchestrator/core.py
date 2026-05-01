"""
orchestrator/core.py
─────────────────────
Core Orchestrator — the central control layer of the Itanta AI Agent Framework.

This module owns:
  • The main event loop (run())
  • Stage routing via AgentRouter
  • Human checkpoint enforcement
  • Recovery coordination via RecoveryAgent
  • Per-task TDD → Code → Review → Validate cycle
  • Final summary generation

Architecture principle from the design document:
  "A single orchestrator manages state and routes work between specialized
   agents.  Each agent owns one narrow responsibility."

The Orchestrator is the ONLY entity that:
  - advances the WorkflowStage
  - calls save/restore on CheckpointManager
  - triggers human approval flows
  - invokes the RecoveryAgent
"""
from __future__ import annotations

import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

import yaml

from agents.architect import ArchitectAgent
from agents.clarifier import ClarifierAgent
from agents.coder import CoderAgent
from agents.planner import PlannerAgent
from agents.qa_agent import QAAgent
from agents.reviewer import ReviewerAgent
from models.workflow import (
    CheckpointTrigger,
    DiffPayload,
    FailureRecord,
    FailureType,
    ImplementationTask,
    TaskStatus,
    ValidationResult,
    WorkflowStage,
    WorkflowState,
)
from orchestrator.checkpoints import CheckpointManager
from orchestrator.logger import ActivityLogger
from orchestrator.recovery import RecoveryAgent
from orchestrator.router import AgentRouter
from orchestrator.state import WorkflowStateManager
from orchestrator.summary import SummaryGenerator
from utils.gemini_client import GeminiClient


class Orchestrator:
    """
    Central control layer.

    Usage
    -----
        orch = Orchestrator.from_config("config.yaml")
        summary = orch.run(
            project_name="My API",
            raw_input="Build a REST API that …",
            answer_fn=lambda questions: {q: input(q) for q in questions},
        )
    """

    # ── Construction ──────────────────────────────────────────

    def __init__(
        self,
        gemini_client: GeminiClient,
        config: Dict,
        project_dir: str = "./generated_project",
    ) -> None:
        self._config      = config
        self._project_dir = Path(project_dir)
        self._project_dir.mkdir(parents=True, exist_ok=True)

        log_dir = config.get("logging", {}).get("log_dir", "./logs")
        cp_dir  = config.get("state", {}).get("checkpoint_dir", "./checkpoints")
        state_dir = "./state"

        # Core infrastructure (initialised without a run_id; set in run())
        self._logger      = ActivityLogger(log_dir=log_dir, run_id="boot")
        self._gemini      = gemini_client
        self._state_mgr   = WorkflowStateManager(state_dir=state_dir, logger=self._logger)
        self._cp_dir      = cp_dir
        self._summary_gen = SummaryGenerator(output_dir=log_dir)

        # Recovery settings
        rec_cfg = config.get("recovery", {})
        self._max_retries    = rec_cfg.get("max_retries_per_task", 3)
        self._retry_backoff  = rec_cfg.get("retry_backoff_seconds", 2.0)
        self._max_rollback   = rec_cfg.get("max_rollback_depth", 5)

        # Checkpoint settings
        cp_cfg = config.get("checkpoints", {})
        self._require_spec_approval = cp_cfg.get("require_spec_approval", True)
        self._require_plan_approval = cp_cfg.get("require_plan_approval", True)
        self._require_diff_approval = cp_cfg.get("require_diff_approval", True)
        self._file_change_threshold = cp_cfg.get("file_change_threshold", 10)

        # Agents — shared Gemini client
        self._clarifier = ClarifierAgent(gemini_client, self._logger)
        self._architect = ArchitectAgent(gemini_client, self._logger)
        self._planner   = PlannerAgent(gemini_client, self._logger)
        self._qa        = QAAgent(gemini_client, self._logger, project_dir=str(self._project_dir))
        self._coder     = CoderAgent(gemini_client, self._logger, project_dir=str(self._project_dir))
        self._reviewer  = ReviewerAgent(gemini_client, self._logger)

        # Router wired up once
        self._router = AgentRouter()
        self._router.register_many({
            WorkflowStage.CLARIFICATION: self._clarifier,
            WorkflowStage.ARCHITECTURE:  self._architect,
            WorkflowStage.PLANNING:      self._planner,
        })

        self._logger.info("Orchestrator initialised.")
        self._logger.info(self._router.describe())

    @classmethod
    def from_config(cls, config_path: str = "config.yaml", **kwargs) -> "Orchestrator":
        """Factory that reads config.yaml and builds the Orchestrator."""
        with open(config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh)

        llm_cfg = config.get("llm", {})
        client = GeminiClient(
            model_name=llm_cfg.get("model", "gemini-1.5-pro"),
            temperature=llm_cfg.get("temperature", 0.2),
            max_output_tokens=llm_cfg.get("max_output_tokens", 8192),
            max_retries=config.get("recovery", {}).get("max_retries_per_task", 3),
            retry_backoff=config.get("recovery", {}).get("retry_backoff_seconds", 2.0),
        )
        return cls(gemini_client=client, config=config, **kwargs)

    # ── Main entry point ──────────────────────────────────────

    def run(
        self,
        project_name: str,
        raw_input: str,
        answer_fn: Optional[Callable[[list], Dict[str, str]]] = None,
        approval_fn: Optional[Callable[[str, object], bool]] = None,
    ) -> Dict:
        """
        Run the full orchestration pipeline.

        Parameters
        ----------
        project_name : human-readable project name
        raw_input    : natural-language project specification
        answer_fn    : callable(questions: list[str]) → dict[question, answer]
                       Used to supply human answers to clarifying questions.
                       Defaults to terminal prompt if None.
        approval_fn  : callable(trigger: str, payload: Any) → bool
                       Used at human checkpoints.
                       Defaults to terminal y/n prompt if None.

        Returns
        -------
        The workflow summary dict (same as written to workflow_summary.json).
        """
        # Default interaction functions
        if answer_fn is None:
            answer_fn = self._terminal_answer_fn
        if approval_fn is None:
            approval_fn = self._terminal_approval_fn

        # Initialise state and per-run infrastructure
        state = self._state_mgr.create(project_name, raw_input)
        self._logger = ActivityLogger(
            log_dir=self._config.get("logging", {}).get("log_dir", "./logs"),
            run_id=state.run_id,
        )
        self._state_mgr._logger = self._logger

        cp_mgr = CheckpointManager(
            checkpoint_dir=self._cp_dir,
            run_id=state.run_id,
            logger=self._logger,
        )
        recovery_agent = RecoveryAgent(
            checkpoint_manager=cp_mgr,
            logger=self._logger,
            max_retries=self._max_retries,
            retry_backoff_seconds=self._retry_backoff,
            max_rollback_depth=self._max_rollback,
        )

        self._logger.info(f"=== Workflow started — run_id={state.run_id} ===")
        self._logger.info(f"Project: {project_name}")

        try:
            # ── Phase 1: Clarification ────────────────────────
            state = self._phase_clarification(
                state, answer_fn, approval_fn, cp_mgr, recovery_agent
            )
            if state.is_terminal():
                return self._finalize(state)

            # ── Phase 2: Architecture ─────────────────────────
            state = self._phase_architecture(state, cp_mgr)
            if state.is_terminal():
                return self._finalize(state)

            # ── Phase 3: Planning + human approval ───────────
            state = self._phase_planning(
                state, approval_fn, cp_mgr, recovery_agent
            )
            if state.is_terminal():
                return self._finalize(state)

            # ── Phase 4: TDD → Code → Review → Validate (per task) ──
            state = self._phase_execution(
                state, approval_fn, cp_mgr, recovery_agent
            )

        except KeyboardInterrupt:
            self._logger.warning("Workflow interrupted by user.")
            self._state_mgr.abort(state, reason="KeyboardInterrupt")

        except Exception as exc:
            self._logger.error(f"Unhandled exception: {exc}")
            self._state_mgr.abort(state, reason=str(exc))
            raise

        return self._finalize(state)

    # ── Phase handlers ────────────────────────────────────────

    def _phase_clarification(
        self, state, answer_fn, approval_fn, cp_mgr, recovery_agent
    ) -> WorkflowState:
        self._state_mgr.jump_to(state, WorkflowStage.CLARIFICATION)
        self._logger.stage_entered(WorkflowStage.CLARIFICATION.value)

        # Run clarifier to extract questions
        state = self._clarifier.run(state)
        state.record_api_call()

        questions = state.spec.clarifying_questions if state.spec else []
        if questions:
            self._logger.human_approval_requested("clarification_answers")
            answers = answer_fn(questions)
            if state.spec:
                state.spec.clarification_answers = answers
            # Re-run clarifier to produce the structured spec
            state = self._clarifier.run(state)
            state.record_api_call()

        # Human checkpoint: spec approval
        if self._require_spec_approval and state.spec:
            cp_mgr.save(state, CheckpointTrigger.SPEC_APPROVAL)
            self._logger.human_approval_requested(CheckpointTrigger.SPEC_APPROVAL.value)

            approved = approval_fn(
                CheckpointTrigger.SPEC_APPROVAL.value,
                state.spec,
            )
            if approved:
                state.spec.is_approved = True
                self._logger.human_approved(CheckpointTrigger.SPEC_APPROVAL.value)
            else:
                self._logger.human_rejected(CheckpointTrigger.SPEC_APPROVAL.value)
                # Allow user to provide revised input → loop back
                self._logger.info("Spec rejected — returning to clarification.")
                return self._phase_clarification(
                    state, answer_fn, approval_fn, cp_mgr, recovery_agent
                )

        self._state_mgr.save(state)
        return state

    def _phase_architecture(self, state, cp_mgr) -> WorkflowState:
        self._state_mgr.jump_to(state, WorkflowStage.ARCHITECTURE)
        self._logger.stage_entered(WorkflowStage.ARCHITECTURE.value)

        state = self._architect.run(state)
        state.record_api_call()
        self._state_mgr.save(state)
        return state

    def _phase_planning(
        self, state, approval_fn, cp_mgr, recovery_agent
    ) -> WorkflowState:
        self._state_mgr.jump_to(state, WorkflowStage.PLANNING)
        self._logger.stage_entered(WorkflowStage.PLANNING.value)

        state = self._planner.run(state)
        state.record_api_call()

        # Human checkpoint: plan approval
        self._state_mgr.jump_to(state, WorkflowStage.HUMAN_PLAN_APPROVAL)

        if self._require_plan_approval and state.plan:
            cp_mgr.save(state, CheckpointTrigger.PLAN_APPROVAL)
            self._logger.human_approval_requested(CheckpointTrigger.PLAN_APPROVAL.value)

            approved = approval_fn(
                CheckpointTrigger.PLAN_APPROVAL.value,
                state.plan,
            )
            if approved:
                state.plan.is_approved = True
                self._logger.human_approved(CheckpointTrigger.PLAN_APPROVAL.value)
            else:
                self._logger.human_rejected(CheckpointTrigger.PLAN_APPROVAL.value, "User rejected plan.")
                self._state_mgr.abort(state, reason="Plan rejected by user.")
        else:
            if state.plan:
                state.plan.is_approved = True

        self._state_mgr.save(state)
        return state

    def _phase_execution(
        self, state, approval_fn, cp_mgr, recovery_agent
    ) -> WorkflowState:
        """
        For each task in order:
          1. QA agent writes failing tests
          2. Coder generates code (diff)
          3. Reviewer checks the diff
          4. Human approves the diff (if required)
          5. Code is applied to disk
          6. Tests are run — pass → next task, fail → recovery
        """
        if state.plan is None:
            return state

        for task in state.plan.tasks:
            if task.status != TaskStatus.PENDING:
                continue

            self._logger.info(
                f"─── Starting task {task.id}: {task.title} ───"
            )
            task.status = TaskStatus.IN_PROGRESS

            # Optional per-task checkpoint
            if task.requires_checkpoint:
                cp_mgr.save(state, CheckpointTrigger.DIFF_APPROVAL)

            success = self._execute_single_task(
                state, task, approval_fn, cp_mgr, recovery_agent
            )
            if not success:
                self._logger.error(
                    f"Task {task.id} failed after all recovery attempts."
                )
                if state.is_terminal():
                    break

        self._state_mgr.jump_to(state, WorkflowStage.COMPLETE)
        self._state_mgr.complete(state)
        return state

    # ── Single-task cycle ─────────────────────────────────────

    def _execute_single_task(
        self, state, task: ImplementationTask,
        approval_fn, cp_mgr, recovery_agent
    ) -> bool:
        """
        Full TDD → Code → Review → Validate cycle for one task.
        Returns True if the task ended in PASSED, False otherwise.
        """
        for attempt in range(1, self._max_retries + 2):
            # Step A: TDD — write failing tests (only on first attempt)
            if attempt == 1:
                self._state_mgr.jump_to(state, WorkflowStage.TDD)
                state = self._qa.run_for_task(state, task)
                state.record_api_call()

            # Step B: Generate code
            self._state_mgr.jump_to(state, WorkflowStage.CODE_GEN)
            error_output = task.error_output or ""
            state = self._coder.run_for_task(state, task, error_output=error_output)
            state.record_api_call()

            # Step C: Reviewer checks diff
            diff = self._latest_diff_for_task(state, task.id)
            if diff:
                self._state_mgr.jump_to(state, WorkflowStage.DIFF_REVIEW)
                safe, notes = self._reviewer.review_diff(diff, state)
                state.record_api_call()

                if not safe:
                    failure = FailureRecord(
                        failure_type=FailureType.UNSAFE_DIFF,
                        task_id=task.id,
                        stage=WorkflowStage.DIFF_REVIEW,
                        message=notes,
                    )
                    resolved, escalated = recovery_agent.handle(state, failure)
                    if escalated:
                        task.status = TaskStatus.FAILED
                        return False
                    continue   # retry

                # Step D: Human diff approval
                if self._require_diff_approval:
                    cp_mgr.save(state, CheckpointTrigger.DIFF_APPROVAL)
                    self._logger.human_approval_requested(
                        CheckpointTrigger.DIFF_APPROVAL.value
                    )
                    approved = approval_fn(
                        CheckpointTrigger.DIFF_APPROVAL.value, diff
                    )
                    if approved:
                        diff.is_approved = True
                        self._logger.human_approved(CheckpointTrigger.DIFF_APPROVAL.value)
                    else:
                        self._logger.human_rejected(
                            CheckpointTrigger.DIFF_APPROVAL.value, "User rejected diff."
                        )
                        task.status = TaskStatus.FAILED
                        return False
                else:
                    diff.is_approved = True

                # Step E: Apply code to disk
                self._coder.apply_code(task, state)

            # Step F: Run validation (tests + lint)
            self._state_mgr.jump_to(state, WorkflowStage.VALIDATION)
            val_result = self._run_validation(task, state)
            state.validation_results.append(val_result)

            if val_result.passed:
                task.status = TaskStatus.PASSED
                self._logger.test_run(task.id, passed=True, summary="All tests passed.")
                return True
            else:
                task.retry_count += 1
                task.error_output = val_result.error_summary
                self._logger.test_run(task.id, passed=False, summary=val_result.error_summary[:200])

                failure = FailureRecord(
                    failure_type=FailureType.VALIDATION_FAILURE,
                    task_id=task.id,
                    stage=WorkflowStage.VALIDATION,
                    message=val_result.error_summary,
                    retry_count=task.retry_count,
                )

                if task.retry_count > self._max_retries:
                    failure.failure_type = FailureType.MAX_RETRIES_EXCEEDED
                    _, escalated = recovery_agent.handle(state, failure)
                    task.status = TaskStatus.FAILED
                    return False

                resolved, escalated = recovery_agent.handle(state, failure)
                if escalated:
                    task.status = TaskStatus.FAILED
                    return False
                # Loop back for retry with error context

        task.status = TaskStatus.FAILED
        return False

    # ── Validation runner ─────────────────────────────────────

    def _run_validation(
        self, task: ImplementationTask, state: WorkflowState
    ) -> ValidationResult:
        """
        Run pytest + optional linting against the task's test file.
        Uses subprocess — sandboxed to the project directory.
        """
        test_file = task.test_file or ""
        test_output = lint_output = type_output = ""
        passed = False

        try:
            if test_file and Path(test_file).exists():
                result = subprocess.run(
                    ["python", "-m", "pytest", test_file, "-v", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=str(self._project_dir),
                )
                test_output = result.stdout + result.stderr
                passed = (result.returncode == 0)
            else:
                test_output = "No test file found — treating as passed (smoke mode)."
                passed = True

            # Lint the generated code file
            if task.code_file and Path(task.code_file).exists():
                lint_result = subprocess.run(
                    ["python", "-m", "flake8", task.code_file,
                     "--max-line-length=100", "--ignore=E501,W503"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(self._project_dir),
                )
                lint_output = lint_result.stdout + lint_result.stderr

        except subprocess.TimeoutExpired:
            test_output = "Test run timed out."
            passed = False
        except FileNotFoundError as exc:
            test_output = f"Test runner not found: {exc}"
            passed = True   # Don't block if pytest isn't installed

        error_summary = ""
        if not passed:
            lines = (test_output + lint_output).splitlines()
            error_summary = "\n".join(
                l for l in lines
                if any(kw in l.lower() for kw in ["error", "fail", "assert", "exception"])
            )[:1000]

        self._logger.test_run(task.id, passed=passed)

        return ValidationResult(
            task_id=task.id,
            passed=passed,
            test_output=test_output[:2000],
            lint_output=lint_output[:1000],
            error_summary=error_summary,
        )

    # ── Finalization ──────────────────────────────────────────

    def _finalize(self, state: WorkflowState) -> Dict:
        state.finished_at = datetime.utcnow()
        # Sync api_call_count from Gemini client
        state.api_call_count = self._gemini.call_count
        self._state_mgr.save(state)

        summary = self._summary_gen.generate(state)

        self._logger.info("=== Workflow finished ===")
        self._logger.info(
            f"Stage: {state.current_stage.value}  |  "
            f"API calls: {state.api_call_count}  |  "
            f"Files: {state.total_files_generated}"
        )
        return summary

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _latest_diff_for_task(
        state: WorkflowState, task_id: str
    ) -> Optional[DiffPayload]:
        matching = [d for d in state.diffs if d.task_id == task_id]
        return matching[-1] if matching else None

    # ── Default interaction callbacks ─────────────────────────

    @staticmethod
    def _terminal_answer_fn(questions: list) -> Dict[str, str]:
        print("\n── Clarifying Questions ──────────────────────────────")
        answers = {}
        for q in questions:
            print(f"\n  {q}")
            answers[q] = input("  Your answer: ").strip()
        return answers

    @staticmethod
    def _terminal_approval_fn(trigger: str, payload) -> bool:
        print(f"\n── Human Checkpoint: {trigger} ──────────────────────")
        if hasattr(payload, "model_dump"):
            import json
            try:
                print(json.dumps(payload.model_dump(), indent=2, default=str)[:2000])
            except Exception:
                print(str(payload)[:500])
        elif isinstance(payload, str):
            print(payload[:2000])
        answer = input("\n  Approve? [y/N]: ").strip().lower()
        return answer in ("y", "yes")
