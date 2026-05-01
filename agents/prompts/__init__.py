"""
agents/prompts/__init__.py
───────────────────────────
Prompt template registry — one import to get them all.
"""
from . import (
    clarifier_prompts,
    architect_prompts,
    planner_prompts,
    qa_prompts,
    coder_prompts,
    reviewer_prompts,
)

__all__ = [
    "clarifier_prompts",
    "architect_prompts",
    "planner_prompts",
    "qa_prompts",
    "coder_prompts",
    "reviewer_prompts",
]
