"""
orchestrator/router.py
───────────────────────
AgentRouter — maps WorkflowStage → the correct agent to call.

This is the single source of truth for the routing table.  Adding a new
agent requires only a one-line change here — the Orchestrator loop stays
unchanged.

Design rule: the Router never mutates state; it only returns which agent
should run next and the input data for that agent.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from models.workflow import WorkflowStage, WorkflowState

if TYPE_CHECKING:
    from agents.base import BaseAgent


class AgentRouter:
    """
    Routes a WorkflowStage to the registered agent for that stage.

    Agents are registered via register(), typically done once at startup
    in main.py (or core.py).  The Orchestrator calls next_agent() each
    loop iteration.
    """

    def __init__(self) -> None:
        self._registry: dict[WorkflowStage, "BaseAgent"] = {}

    # ── Registration ──────────────────────────────────────────

    def register(self, stage: WorkflowStage, agent: "BaseAgent") -> None:
        """Bind an agent to a workflow stage."""
        self._registry[stage] = agent

    def register_many(self, mapping: dict[WorkflowStage, "BaseAgent"]) -> None:
        for stage, agent in mapping.items():
            self.register(stage, agent)

    # ── Routing ───────────────────────────────────────────────

    def next_agent(self, state: WorkflowState) -> Optional["BaseAgent"]:
        """
        Return the agent responsible for the current stage.
        Returns None if the stage has no registered agent (terminal or
        human-only stage).
        """
        return self._registry.get(state.current_stage)

    def has_agent(self, stage: WorkflowStage) -> bool:
        return stage in self._registry

    def registered_stages(self) -> list[WorkflowStage]:
        return list(self._registry.keys())

    def describe(self) -> str:
        lines = ["AgentRouter routing table:"]
        for stage, agent in self._registry.items():
            lines.append(f"  {stage.value:25s} → {agent.__class__.__name__}")
        return "\n".join(lines)
