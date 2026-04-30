"""
agents/clarifier.py
────────────────────
Clarifier Agent — FR-01, FR-02.

Responsibilities:
  1. Analyse the raw project specification for ambiguities.
  2. Generate a minimal, targeted set of clarifying questions.
  3. After answers are provided, produce the Structured Specification
     (ProjectSpec) that the Architect will consume.
"""
from __future__ import annotations

import json
import re
from typing import List

from agents.base import BaseAgent
from models.workflow import ProjectSpec, WorkflowState


_SYSTEM = (
    "You are the Clarifier Agent in a multi-agent software development "
    "framework.  Your job is to identify ambiguities in project specifications "
    "and generate the minimal set of questions needed to remove them. "
    "Be concise and precise. Never ask for information that can be reasonably inferred."
)


class ClarifierAgent(BaseAgent):

    # ── Entry point ───────────────────────────────────────────

    def run(self, state: WorkflowState) -> WorkflowState:
        self._log_start()
        spec = state.spec
        if spec is None:
            raise ValueError("ClarifierAgent: state.spec is None — nothing to clarify.")

        # Step 1 — identify ambiguities and generate questions
        if not spec.clarifying_questions:
            questions = self._identify_ambiguities(spec.raw_input)
            spec.clarifying_questions = questions
            self._logger.info(
                f"ClarifierAgent generated {len(questions)} clarifying question(s)."
            )

        # Step 2 — if questions have been answered, produce the structured spec
        if spec.clarifying_questions and spec.clarification_answers:
            structured = self._produce_structured_spec(spec)
            state.spec = structured

        state.record_api_call()
        self._log_end(success=True)
        return state

    # ── Private helpers ───────────────────────────────────────

    def _identify_ambiguities(self, raw_input: str) -> List[str]:
        prompt = f"""
Analyse the following project specification and identify the top 3-5 ambiguities
or missing details that would prevent building the system correctly.

For each ambiguity, write one concise clarifying question (max 20 words each).
Return ONLY a JSON array of question strings.

Project specification:
\"\"\"
{raw_input}
\"\"\"
"""
        raw = self._call_llm_json(prompt, system=_SYSTEM)
        try:
            questions = json.loads(raw)
            if isinstance(questions, list):
                return [str(q) for q in questions[:5]]
        except (json.JSONDecodeError, TypeError):
            # Fallback: extract lines that look like questions
            return self._extract_questions_from_text(raw)
        return []

    def _produce_structured_spec(self, spec: ProjectSpec) -> ProjectSpec:
        answers_text = "\n".join(
            f"Q: {q}\nA: {spec.clarification_answers.get(q, '(no answer)')}"
            for q in spec.clarifying_questions
        )

        prompt = f"""
You are producing a Structured Specification Document based on:

ORIGINAL SPECIFICATION:
{spec.raw_input}

CLARIFICATION Q&A:
{answers_text}

Produce a JSON object with these exact keys:
  "project_summary"       : string (2-3 sentences)
  "acceptance_criteria"   : list of strings (one criterion per item)
  "proposed_architecture" : string (high-level description)
  "known_constraints"     : list of strings

Return ONLY the JSON object.
"""
        raw = self._call_llm_json(prompt, system=_SYSTEM)
        try:
            data = json.loads(raw)
            spec.project_summary       = data.get("project_summary", "")
            spec.proposed_architecture = data.get("proposed_architecture", "")
            spec.acceptance_criteria   = data.get("acceptance_criteria", [])
            spec.known_constraints     = data.get("known_constraints", [])
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            self._logger.error(f"ClarifierAgent failed to parse spec JSON: {exc}")
        return spec

    @staticmethod
    def _extract_questions_from_text(text: str) -> List[str]:
        """Fallback: extract lines ending in '?' from freeform text."""
        return [
            line.strip(" -•*1234567890.")
            for line in text.splitlines()
            if "?" in line and len(line.strip()) > 5
        ][:5]
