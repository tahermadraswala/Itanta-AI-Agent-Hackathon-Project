"""
agents/base.py
───────────────
Abstract base class that every agent inherits.

Contract:
  • Every agent receives the live WorkflowState and the GeminiClient.
  • Every agent returns the (mutated) WorkflowState.
  • Agents never advance the stage — that is the Orchestrator's job.
  • Agents record every LLM call via state.record_api_call().
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from models.workflow import WorkflowState
from orchestrator.logger import ActivityLogger
from utils.gemini_client import GeminiClient


class BaseAgent(ABC):
    """
    All agents share:
      • a GeminiClient for LLM calls
      • an ActivityLogger for structured logging
      • a name property used in log messages
    """

    def __init__(self, client: GeminiClient, logger: ActivityLogger) -> None:
        self._client = client
        self._logger = logger

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def run(self, state: WorkflowState) -> WorkflowState:
        """
        Execute the agent's responsibility against the current state.
        Mutates and returns state.
        """
        ...

    # ── Helpers shared by all agents ─────────────────────────

    def _call_llm(self, prompt: str, system: str | None = None) -> str:
        """Wrapper that auto-increments api_call_count."""
        # state.record_api_call() is called inside core.py after return,
        # but we also log here for observability.
        self._logger.api_call(self._client.model_name)
        return self._client.generate(prompt, system_instruction=system)

    def _call_llm_json(self, prompt: str, system: str | None = None) -> str:
        self._logger.api_call(self._client.model_name)
        return self._client.generate_json(prompt, system_instruction=system)

    def _log_start(self, task_id: str | None = None) -> None:
        self._logger.agent_called(self.name, task_id=task_id)

    def _log_end(self, success: bool = True, task_id: str | None = None) -> None:
        self._logger.agent_returned(self.name, task_id=task_id, success=success)
