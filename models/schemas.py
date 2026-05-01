"""
models/schemas.py
──────────────────
Pydantic v2 output schemas for every agent in the pipeline.

Each schema represents the EXACT structured data an agent must return.
All inter-agent hand-offs go through these schemas — no free-form dicts.

Design principle:
  • Every field has a description so the LLM prompt can reference it.
  • Every schema has a .validate_completeness() method so the Orchestrator
    can reject under-specified outputs before they propagate downstream.
  • Schemas are versioned via the class docstring (bump on breaking change).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────
#  Shared enumerations
# ─────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class SecuritySeverity(str, Enum):
    INFO     = "info"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class TestType(str, Enum):
    UNIT        = "unit"
    INTEGRATION = "integration"
    E2E         = "e2e"
    SECURITY    = "security"
    PERFORMANCE = "performance"


# ─────────────────────────────────────────────────────────────
#  1. Clarifier Agent Output Schema
# ─────────────────────────────────────────────────────────────

class ClarifyingQuestion(BaseModel):
    """A single targeted clarifying question with its rationale."""
    question: str = Field(
        description="The clarifying question text (max 30 words)."
    )
    aspect: str = Field(
        description="Which aspect of the spec this question addresses "
                    "(e.g. 'authentication', 'data model', 'scale')."
    )
    impact: str = Field(
        description="What downstream design decisions this answer affects."
    )
    default_assumption: str = Field(
        default="",
        description="What the system will assume if no answer is provided."
    )


class ClarifierOutput(BaseModel):
    """
    v1 — Output schema for the Clarifier Agent.
    Produced after step 1 (question generation) and step 2 (spec production).
    """
    # ── Step 1: ambiguity analysis ────────────────────────────
    ambiguities_found: List[str] = Field(
        default_factory=list,
        description="List of identified ambiguities or missing details in the raw spec."
    )
    clarifying_questions: List[ClarifyingQuestion] = Field(
        default_factory=list,
        description="Minimal set of targeted questions to resolve ambiguities (3-5 max)."
    )

    # ── Step 2: structured specification ─────────────────────
    project_summary: str = Field(
        default="",
        description="2-3 sentence plain-English summary of what will be built."
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="Concrete, testable acceptance criteria. Each item starts with 'The system must …'."
    )
    proposed_architecture: str = Field(
        default="",
        description="High-level description of the proposed system architecture."
    )
    tech_stack: List[str] = Field(
        default_factory=list,
        description="Technologies, frameworks, and libraries the project will use."
    )
    known_constraints: List[str] = Field(
        default_factory=list,
        description="Known technical, business, or timeline constraints."
    )
    out_of_scope: List[str] = Field(
        default_factory=list,
        description="Items explicitly excluded from this implementation."
    )

    def validate_completeness(self) -> List[str]:
        """Return list of validation errors (empty = valid)."""
        errors = []
        if not self.project_summary:
            errors.append("project_summary is empty")
        if not self.acceptance_criteria:
            errors.append("acceptance_criteria is empty")
        if len(self.acceptance_criteria) < 2:
            errors.append("acceptance_criteria must have at least 2 criteria")
        return errors


# ─────────────────────────────────────────────────────────────
#  2. Architect Agent Output Schema
# ─────────────────────────────────────────────────────────────

class DataModel(BaseModel):
    """A single data model / entity in the system."""
    name: str = Field(description="Model name in PascalCase (e.g. 'UserProfile').")
    description: str = Field(description="What this model represents.")
    fields: List[Dict[str, str]] = Field(
        description="List of {name, type, description} dicts for each field."
    )
    relationships: List[str] = Field(
        default_factory=list,
        description="Relationships to other models (e.g. 'belongs to User')."
    )


class ApiEndpoint(BaseModel):
    """A single API endpoint contract."""
    method: str = Field(description="HTTP method: GET | POST | PUT | PATCH | DELETE.")
    path: str = Field(description="URL path with path params in {braces} (e.g. /users/{id}).")
    description: str = Field(description="What this endpoint does.")
    request_body: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON schema of the request body (null for GET/DELETE)."
    )
    response_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema of the success response body."
    )
    auth_required: bool = Field(default=False, description="Whether authentication is required.")
    error_codes: List[str] = Field(
        default_factory=list,
        description="Expected HTTP error codes and their meanings (e.g. '404: Task not found')."
    )


class DirectoryNode(BaseModel):
    """One node in the project directory tree."""
    path: str = Field(description="Relative path from project root (e.g. 'src/api/routes.py').")
    node_type: str = Field(description="'file' or 'directory'.")
    purpose: str = Field(description="What this file/directory contains or does.")
    module: Optional[str] = Field(
        default=None,
        description="Which logical module this file belongs to."
    )


class ModuleBoundary(BaseModel):
    """A logical module with clear boundaries."""
    name: str = Field(description="Module name (e.g. 'auth', 'tasks', 'notifications').")
    responsibility: str = Field(description="Single-sentence description of what this module owns.")
    public_interface: List[str] = Field(
        description="Functions / classes / endpoints that other modules may call."
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="Other modules this module depends on."
    )
    files: List[str] = Field(
        default_factory=list,
        description="Files that belong to this module."
    )


class ArchitectOutput(BaseModel):
    """
    v1 — Output schema for the Architect Agent.
    Produces the structural blueprint for the generated project.
    """
    project_root: str = Field(
        description="Name of the root project directory (snake_case)."
    )
    directory_tree: List[DirectoryNode] = Field(
        description="All files and directories in the project, ordered top-down."
    )
    modules: List[ModuleBoundary] = Field(
        description="Logical module boundaries with clear responsibilities."
    )
    data_models: List[DataModel] = Field(
        default_factory=list,
        description="Data models / entities the system will use."
    )
    api_endpoints: List[ApiEndpoint] = Field(
        default_factory=list,
        description="All API endpoints the system exposes."
    )
    external_dependencies: List[str] = Field(
        default_factory=list,
        description="Third-party libraries needed (e.g. 'fastapi', 'sqlalchemy')."
    )
    architectural_decisions: List[str] = Field(
        default_factory=list,
        description="Key architectural decisions and their rationale."
    )

    def validate_completeness(self) -> List[str]:
        errors = []
        if not self.directory_tree:
            errors.append("directory_tree is empty")
        if not self.modules:
            errors.append("modules list is empty")
        if len(self.modules) < 2:
            errors.append("at least 2 modules expected")
        return errors


# ─────────────────────────────────────────────────────────────
#  3. Planner Agent Output Schema
# ─────────────────────────────────────────────────────────────

class TaskCheckpoint(BaseModel):
    """A human or automated checkpoint embedded within a task."""
    trigger: str = Field(description="What triggers this checkpoint (e.g. 'before applying auth changes').")
    approver: str = Field(description="'human' | 'automated'.")
    reason: str = Field(description="Why this checkpoint is required.")


class PlannerTask(BaseModel):
    """A single atomic implementation task in the ordered plan."""
    id: str = Field(description="Unique task identifier (e.g. 'task_001').")
    title: str = Field(description="Short task title (max 8 words).")
    description: str = Field(description="Clear description of what this task implements (2-3 sentences).")
    order: int = Field(description="Execution order (1-based integer, no gaps).")
    module: str = Field(description="Which module boundary this task belongs to.")
    depends_on: List[str] = Field(
        default_factory=list,
        description="IDs of tasks that must complete before this one starts."
    )
    estimated_files: List[str] = Field(
        description="Relative file paths this task will create or modify."
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW,
        description="Risk level: low | medium | high."
    )
    requires_checkpoint: bool = Field(
        default=False,
        description="True if this task requires human review before execution."
    )
    checkpoint: Optional[TaskCheckpoint] = Field(
        default=None,
        description="Checkpoint details (only if requires_checkpoint=true)."
    )
    acceptance_test: str = Field(
        description="One sentence describing how to verify this task is complete."
    )
    estimated_complexity: str = Field(
        default="medium",
        description="Complexity estimate: trivial | low | medium | high | very_high."
    )

    @field_validator("id")
    @classmethod
    def id_format(cls, v: str) -> str:
        if not v.startswith("task_"):
            raise ValueError("Task id must start with 'task_'")
        return v


class PlannerOutput(BaseModel):
    """
    v1 — Output schema for the Planner Agent.
    Produces an ordered, dependency-resolved atomic task graph.
    """
    tasks: List[PlannerTask] = Field(
        description="Ordered list of atomic implementation tasks."
    )
    total_estimated_complexity: str = Field(
        description="Overall project complexity estimate."
    )
    critical_path: List[str] = Field(
        description="Ordered list of task IDs forming the critical path."
    )
    parallel_groups: List[List[str]] = Field(
        default_factory=list,
        description="Groups of task IDs that can be executed in parallel."
    )
    implementation_notes: List[str] = Field(
        default_factory=list,
        description="High-level notes about implementation strategy."
    )

    def validate_completeness(self) -> List[str]:
        errors = []
        if not self.tasks:
            errors.append("tasks list is empty")
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            errors.append("duplicate task IDs found")
        # Check all depends_on reference valid IDs
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in ids:
                    errors.append(f"task {task.id} depends on unknown task {dep}")
        return errors


# ─────────────────────────────────────────────────────────────
#  4. QA / TDD Agent Output Schema
# ─────────────────────────────────────────────────────────────

class TestCase(BaseModel):
    """Metadata for a single test function."""
    function_name: str = Field(description="Test function name (must start with 'test_').")
    test_type: TestType = Field(description="Type of test.")
    description: str = Field(description="What this test verifies (one sentence).")
    acceptance_criterion: str = Field(
        description="Which acceptance criterion from the spec this test covers."
    )
    should_fail_initially: bool = Field(
        default=True,
        description="True because TDD: no implementation exists yet."
    )
    fixtures_needed: List[str] = Field(
        default_factory=list,
        description="pytest fixture names this test requires."
    )


class QAOutput(BaseModel):
    """
    v1 — Output schema for the QA / TDD Agent.
    Describes the test file produced for one implementation task.
    """
    task_id: str = Field(description="ID of the task these tests cover.")
    test_file_path: str = Field(description="Relative path where the test file will be written.")
    test_file_content: str = Field(description="Complete Python source of the pytest test file.")
    test_cases: List[TestCase] = Field(
        description="Metadata for each test function in the file."
    )
    fixtures: List[str] = Field(
        default_factory=list,
        description="Names of pytest fixtures defined in the file."
    )
    imports_required: List[str] = Field(
        description="Python import statements the test file uses."
    )
    module_under_test: str = Field(
        description="Import path of the module these tests target (e.g. 'src.tasks.service')."
    )
    coverage_summary: str = Field(
        description="Brief description of what acceptance criteria are covered."
    )

    def validate_completeness(self) -> List[str]:
        errors = []
        if not self.test_file_content:
            errors.append("test_file_content is empty")
        if not self.test_cases:
            errors.append("test_cases list is empty")
        for tc in self.test_cases:
            if not tc.function_name.startswith("test_"):
                errors.append(f"test function '{tc.function_name}' must start with 'test_'")
        return errors


# ─────────────────────────────────────────────────────────────
#  5. Coder Agent Output Schema
# ─────────────────────────────────────────────────────────────

class GeneratedFile(BaseModel):
    """A single file generated by the Coder agent."""
    file_path: str = Field(description="Relative path from project root.")
    content: str = Field(description="Complete file content (source code).")
    language: str = Field(default="python", description="Programming language.")
    is_new: bool = Field(default=True, description="True if creating, False if modifying.")
    description: str = Field(description="What this file does.")


class CoderOutput(BaseModel):
    """
    v1 — Output schema for the Coder Agent.
    Contains all files generated for one implementation task.
    """
    task_id: str = Field(description="ID of the task this code implements.")
    generated_files: List[GeneratedFile] = Field(
        description="All files created or modified by this task."
    )
    implementation_notes: str = Field(
        default="",
        description="Notes about implementation decisions made."
    )
    tests_expected_to_pass: List[str] = Field(
        default_factory=list,
        description="Names of test functions expected to pass after applying this code."
    )
    dependencies_added: List[str] = Field(
        default_factory=list,
        description="New pip dependencies introduced by this code."
    )
    follow_up_tasks: List[str] = Field(
        default_factory=list,
        description="Tasks that should be scheduled as a result of this implementation."
    )

    def validate_completeness(self) -> List[str]:
        errors = []
        if not self.generated_files:
            errors.append("generated_files is empty")
        for gf in self.generated_files:
            if not gf.content.strip():
                errors.append(f"file {gf.file_path} has empty content")
        return errors


# ─────────────────────────────────────────────────────────────
#  6. Reviewer / Security Agent Output Schema
# ─────────────────────────────────────────────────────────────

class SecurityIssue(BaseModel):
    """A single security or quality issue found during review."""
    severity: SecuritySeverity
    category: str = Field(
        description="Issue category: 'injection' | 'auth' | 'secrets' | 'logic' | "
                    "'data_exposure' | 'file_safety' | 'dependency' | 'other'."
    )
    location: str = Field(
        description="File path and line number or function name where the issue is."
    )
    description: str = Field(description="Clear description of the issue.")
    recommendation: str = Field(description="How to fix or mitigate this issue.")
    cwe_id: Optional[str] = Field(
        default=None,
        description="CWE identifier if applicable (e.g. 'CWE-89' for SQL injection)."
    )
    auto_fixable: bool = Field(
        default=False,
        description="Whether the framework can auto-fix this without human review."
    )


class CodeQualityNote(BaseModel):
    """A non-security code quality observation."""
    category: str = Field(
        description="'readability' | 'performance' | 'maintainability' | 'testing' | 'documentation'."
    )
    location: str = Field(description="File path or function name.")
    note: str = Field(description="The observation.")
    suggestion: str = Field(description="Suggested improvement.")


class ReviewerOutput(BaseModel):
    """
    v1 — Output schema for the Reviewer / Security Agent.
    Produced after reviewing a code diff or a complete module.
    """
    task_id: str = Field(description="ID of the task being reviewed.")
    is_safe_to_apply: bool = Field(
        description="True only if there are no HIGH or CRITICAL security issues "
                    "and no unsafe shell patterns detected."
    )
    security_issues: List[SecurityIssue] = Field(
        default_factory=list,
        description="All security issues found. Empty if code is clean."
    )
    quality_notes: List[CodeQualityNote] = Field(
        default_factory=list,
        description="Non-blocking code quality observations."
    )
    static_check_passed: bool = Field(
        description="Whether static pattern checks (shell injection, hardcoded secrets) passed."
    )
    diff_summary: str = Field(
        description="1-2 sentence plain-English summary of what the diff does."
    )
    recommendation: str = Field(
        description="'approve' | 'approve_with_notes' | 'reject' | 'escalate'."
    )
    reviewer_notes: str = Field(
        default="",
        description="Any additional notes for the human reviewer."
    )
    blocked_patterns_found: List[str] = Field(
        default_factory=list,
        description="Specific blocked patterns detected in the diff (e.g. 'rm -rf /')."
    )

    def validate_completeness(self) -> List[str]:
        errors = []
        if self.recommendation not in ("approve", "approve_with_notes", "reject", "escalate"):
            errors.append(f"invalid recommendation: {self.recommendation}")
        if not self.is_safe_to_apply and self.recommendation == "approve":
            errors.append("is_safe_to_apply=False but recommendation=approve — contradiction")
        return errors

    def has_blocking_issues(self) -> bool:
        return any(
            i.severity in (SecuritySeverity.HIGH, SecuritySeverity.CRITICAL)
            for i in self.security_issues
        ) or bool(self.blocked_patterns_found)
