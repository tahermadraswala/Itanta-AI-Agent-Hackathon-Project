"""
agents/clarifier.py
────────────────────
Clarifier Agent — FR-01, FR-02.

Two-step agent:
  Step 1: Identify ambiguities in raw spec → generate clarifying questions.
  Step 2: After Q&A answers are supplied, produce the full structured
          ClarifierOutput (ProjectSpec equivalent).

Outputs:     ClarifierOutput (models/schemas.py)
Prompt src:  agents/prompts/clarifier_prompts.py
"""
from __future__ import annotations

import json
from typing import Dict, List

from agents.base import BaseAgent
from agents.prompts import clarifier_prompts as P
from models.schemas import ClarifierOutput, ClarifyingQuestion
from models.workflow import ProjectSpec, WorkflowState


class ClarifierAgent(BaseAgent):
    """
    Runs in two phases:
      Phase A — question generation
      Phase B — structured spec production (requires answers)
    The Orchestrator calls run(), which handles both internally.
    """

    # ── Public interface ──────────────────────────────────────

    def run(self, state: WorkflowState) -> WorkflowState:
        self._log_start()
        spec = state.spec
        if spec is None:
            raise ValueError("ClarifierAgent: state.spec is None.")

        # Phase A: generate questions (only if not already done)
        if not spec.clarifying_questions:
            output_a = self._run_phase_a(spec.raw_input)
            spec.clarifying_questions = [q.question for q in output_a.clarifying_questions]
            self._logger.info(
                f"ClarifierAgent phase A: "
                f"{len(output_a.clarifying_questions)} questions generated."
            )

        # Phase B: produce structured spec (only once answers are available)
        if spec.clarification_answers:
            output_b = self._run_phase_b(spec.raw_input, spec.clarification_answers)
            errors = output_b.validate_completeness()
            if errors:
                self._logger.warning(f"ClarifierOutput validation issues: {errors}")
            self._apply_to_spec(output_b, spec)
            self._logger.info("ClarifierAgent phase B: structured spec produced.")
        elif not spec.clarifying_questions:
            # No back-and-forth — produce spec in one shot
            output_os = self._run_oneshot(spec.raw_input)
            self._apply_to_spec(output_os, spec)

        state.spec = spec
        state.record_api_call()
        self._log_end(success=True)
        return state

    # ── Phase A ───────────────────────────────────────────────

    def _run_phase_a(self, raw_input: str) -> ClarifierOutput:
        prompt = P.STEP1_PROMPT_TEMPLATE.format(raw_input=raw_input)
        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        return self._parse_phase_a(raw)

    def _parse_phase_a(self, raw: str) -> ClarifierOutput:
        try:
            data = json.loads(raw)
            questions = [
                ClarifyingQuestion(
                    question=q.get("question", ""),
                    aspect=q.get("aspect", "general"),
                    impact=q.get("impact", ""),
                    default_assumption=q.get("default_assumption", ""),
                )
                for q in data.get("clarifying_questions", [])
            ]
            return ClarifierOutput(
                ambiguities_found=data.get("ambiguities_found", []),
                clarifying_questions=questions,
            )
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            self._logger.error(f"ClarifierAgent phase A parse error: {exc}")
            return ClarifierOutput()

    # ── Phase B ───────────────────────────────────────────────

    def _run_phase_b(self, raw_input: str, answers: Dict[str, str]) -> ClarifierOutput:
        qa_block = "\n".join(f"  Q: {q}\n  A: {a}" for q, a in answers.items())
        prompt = P.STEP2_PROMPT_TEMPLATE.format(raw_input=raw_input, qa_block=qa_block)
        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        return self._parse_phase_b(raw)

    def _parse_phase_b(self, raw: str) -> ClarifierOutput:
        try:
            data = json.loads(raw)
            return ClarifierOutput(
                project_summary=data.get("project_summary", ""),
                acceptance_criteria=data.get("acceptance_criteria", []),
                proposed_architecture=data.get("proposed_architecture", ""),
                tech_stack=data.get("tech_stack", []),
                known_constraints=data.get("known_constraints", []),
                out_of_scope=data.get("out_of_scope", []),
            )
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            self._logger.error(f"ClarifierAgent phase B parse error: {exc}")
            return ClarifierOutput()

    # ── One-shot mode ─────────────────────────────────────────

    def _run_oneshot(self, raw_input: str) -> ClarifierOutput:
        prompt = P.ONESHOT_PROMPT_TEMPLATE.format(raw_input=raw_input)
        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        try:
            data = json.loads(raw)
            questions = [
                ClarifyingQuestion(
                    question=q.get("question", ""),
                    aspect=q.get("aspect", "general"),
                    impact=q.get("impact", ""),
                    default_assumption=q.get("default_assumption", ""),
                )
                for q in data.get("clarifying_questions", [])
            ]
            return ClarifierOutput(
                ambiguities_found=data.get("ambiguities_found", []),
                clarifying_questions=questions,
                project_summary=data.get("project_summary", ""),
                acceptance_criteria=data.get("acceptance_criteria", []),
                proposed_architecture=data.get("proposed_architecture", ""),
                tech_stack=data.get("tech_stack", []),
                known_constraints=data.get("known_constraints", []),
                out_of_scope=data.get("out_of_scope", []),
            )
        except (json.JSONDecodeError, TypeError) as exc:
            self._logger.error(f"ClarifierAgent one-shot parse error: {exc}")
            return ClarifierOutput()

    # ── Write-back ────────────────────────────────────────────

    @staticmethod
    def _apply_to_spec(output: ClarifierOutput, spec: ProjectSpec) -> None:
        if output.project_summary:
            spec.project_summary = output.project_summary
        if output.acceptance_criteria:
            spec.acceptance_criteria = output.acceptance_criteria
        if output.proposed_architecture:
            spec.proposed_architecture = output.proposed_architecture
        if output.known_constraints:
            spec.known_constraints = output.known_constraints
        spec.__dict__["tech_stack"]  = output.tech_stack
        spec.__dict__["out_of_scope"] = output.out_of_scope

    def get_question_objects(self, state: WorkflowState) -> List[ClarifyingQuestion]:
        if not state.spec or not state.spec.clarifying_questions:
            return []
        return [
            ClarifyingQuestion(question=q, aspect="general", impact="", default_assumption="")
            for q in state.spec.clarifying_questions
        ]
