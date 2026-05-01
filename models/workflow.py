"""
models/workflow.py
──────────────────
Typed data models for every object that flows through the orchestrator.
All inter-agent hand-offs are represented as typed Pydantic models so that
schema violations surface immediately at the boundary, not buried inside
agent logic.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
#  Enumerations
# ─────────────────────────────────────────────────────────────

class WorkflowStage(str, Enum):
    """Ordered stages in the pipeline.  The Orchestrator advances through
    these in sequence; the Recovery agent may step backwards."""
    INTAKE        = "intake"
    CLARIFICATION = "clarification"
    ARCHITECTURE  = "architecture"
    PLANNING      = "planning"
    HUMAN_PLAN_APPROVAL = "human_plan_approval"
    TDD           = "tdd"
    CODE_GEN      = "code_gen"
    DIFF_REVIEW   = "diff_review"
    VALIDATION    = "validation"
    SECURITY      = "security"
    RECOVERY      = "recovery"
    COMPLETE      = "complete"
    ABORTED       = "aborted"


class TaskStatus(str, Enum):
    PENDING    = "pending"
    IN_PROGRESS = "in_progress"
    PASSED     = "passed"
    FAILED     = "failed"
    SKIPPED    = "skipped"
    ROLLED_BACK = "rolled_back"


class CheckpointTrigger(str, Enum):
    SPEC_APPROVAL  = "spec_approval"
    PLAN_APPROVAL  = "plan_approval"
    DIFF_APPROVAL  = "diff_approval"
    ESCALATION     = "escalation"
    RISK_REVIEW    = "risk_review"


class FailureType(str, Enum):
    AMBIGUOUS_REQUIREMENTS = "ambiguous_requirements"
    VALIDATION_FAILURE     = "validation_failure"
    TOOL_API_FAILURE       = "tool_api_failure"
    STATE_INCONSISTENCY    = "state_inconsistency"
    UNSAFE_DIFF            = "unsafe_diff"
    MAX_RETRIES_EXCEEDED   = "max_retries_exceeded"


# ─────────────────────────────────────────────────────────────
#  Core data objects
# ─────────────────────────────────────────────────────────────

class ProjectSpec(BaseModel):
    """Structured specification produced by the Clarifier agent."""
    raw_input: str
    project_summary: str = ""
    acceptance_criteria: List[str] = Field(default_factory=list)
    proposed_architecture: str = ""
    known_constraints: List[str] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)
    clarification_answers: Dict[str, str] = Field(default_factory=dict)
    is_approved: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def is_complete(self) -> bool:
        return bool(self.project_summary and self.acceptance_criteria)


class ImplementationTask(BaseModel):
    """A single atomic task in the execution plan."""
    id: str
    title: str
    description: str
    order: int
    depends_on: List[str] = Field(default_factory=list)   # task ids
    risk_level: str = "low"          # low | medium | high
    estimated_files: List[str] = Field(default_factory=list)
    requires_checkpoint: bool = False
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    test_file: Optional[str] = None
    code_file: Optional[str] = None
    diff_summary: Optional[str] = None
    error_output: Optional[str] = None


class ImplementationPlan(BaseModel):
    """Full ordered task graph produced by the Planner agent."""
    tasks: List[ImplementationTask] = Field(default_factory=list)
    directory_layout: Dict[str, Any] = Field(default_factory=dict)
    module_boundaries: List[str] = Field(default_factory=list)
    api_contracts: List[str] = Field(default_factory=list)
    is_approved: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def pending_tasks(self) -> List[ImplementationTask]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    def completed_tasks(self) -> List[ImplementationTask]:
        return [t for t in self.tasks if t.status == TaskStatus.PASSED]

    def failed_tasks(self) -> List[ImplementationTask]:
        return [t for t in self.tasks if t.status == TaskStatus.FAILED]


class DiffPayload(BaseModel):
    """Code diff produced by the Coder agent, shown to user before apply."""
    task_id: str
    file_path: str
    diff_text: str
    is_approved: bool = False
    flagged_by_reviewer: bool = False
    reviewer_notes: str = ""


class ValidationResult(BaseModel):
    """Result of running tests / linting after code generation."""
    task_id: str
    passed: bool
    test_output: str = ""
    lint_output: str = ""
    type_check_output: str = ""
    error_summary: str = ""
    run_at: datetime = Field(default_factory=datetime.utcnow)


class FailureRecord(BaseModel):
    """Structured record of every detected failure."""
    failure_type: FailureType
    task_id: Optional[str] = None
    stage: WorkflowStage
    message: str
    retry_count: int = 0
    resolved: bool = False
    escalated: bool = False
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class CheckpointRecord(BaseModel):
    """Snapshot of orchestrator state at a control point."""
    id: str
    trigger: CheckpointTrigger
    stage: WorkflowStage
    task_snapshot: List[ImplementationTask] = Field(default_factory=list)
    spec_snapshot: Optional[ProjectSpec] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowState(BaseModel):
    """
    Central mutable state object owned exclusively by the Orchestrator.
    Every agent reads from / writes to a slice of this object; the
    Orchestrator is the only entity that advances the stage.
    """
    run_id: str
    project_name: str
    current_stage: WorkflowStage = WorkflowStage.INTAKE
    spec: Optional[ProjectSpec] = None
    plan: Optional[ImplementationPlan] = None
    diffs: List[DiffPayload] = Field(default_factory=list)
    validation_results: List[ValidationResult] = Field(default_factory=list)
    failures: List[FailureRecord] = Field(default_factory=list)
    checkpoints: List[CheckpointRecord] = Field(default_factory=list)
    api_call_count: int = 0
    total_files_generated: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None

    # ── helpers ──────────────────────────────────────────────

    def record_api_call(self) -> None:
        self.api_call_count += 1

    def add_failure(self, failure: FailureRecord) -> None:
        self.failures.append(failure)

    def last_checkpoint(self) -> Optional[CheckpointRecord]:
        return self.checkpoints[-1] if self.checkpoints else None

    def is_terminal(self) -> bool:
        return self.current_stage in (WorkflowStage.COMPLETE, WorkflowStage.ABORTED)
