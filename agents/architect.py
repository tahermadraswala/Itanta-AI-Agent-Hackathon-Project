"""
agents/architect.py
────────────────────
Architect Agent — FR-04.

Receives an approved ClarifierOutput (via WorkflowState.spec) and
produces an ArchitectOutput: directory tree, module boundaries,
data models, API contracts, and external dependencies.

Outputs:     ArchitectOutput (models/schemas.py)
Prompt src:  agents/prompts/architect_prompts.py
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agents.base import BaseAgent
from agents.prompts import architect_prompts as P
from models.schemas import (
    ApiEndpoint,
    ArchitectOutput,
    DataModel,
    DirectoryNode,
    ModuleBoundary,
)
from models.workflow import ImplementationPlan, WorkflowState


class ArchitectAgent(BaseAgent):

    def run(self, state: WorkflowState) -> WorkflowState:
        self._log_start()

        spec = state.spec
        if spec is None or not spec.is_complete():
            raise ValueError("ArchitectAgent: spec is missing or incomplete.")

        # Build context from spec
        tech_stack  = spec.__dict__.get("tech_stack", [])
        out_of_scope = spec.__dict__.get("out_of_scope", [])

        prompt = P.MAIN_PROMPT_TEMPLATE.format(
            project_summary=spec.project_summary,
            proposed_architecture=spec.proposed_architecture,
            tech_stack=", ".join(tech_stack) if tech_stack else "Python, standard library",
            acceptance_criteria="\n".join(f"  - {c}" for c in spec.acceptance_criteria),
            known_constraints="\n".join(f"  - {c}" for c in spec.known_constraints) or "  None specified.",
            out_of_scope="\n".join(f"  - {c}" for c in out_of_scope) or "  None specified.",
        )

        raw = self._call_llm_json(prompt, system=P.SYSTEM_PROMPT)
        output = self._parse_output(raw)

        errors = output.validate_completeness()
        if errors:
            self._logger.warning(f"ArchitectOutput validation issues: {errors}")

        # Write into plan
        plan = state.plan or ImplementationPlan()
        plan.directory_layout  = self._tree_to_dict(output.directory_tree)
        plan.module_boundaries = [m.responsibility for m in output.modules]
        plan.api_contracts     = [
            f"{ep.method} {ep.path} — {ep.description}"
            for ep in output.api_endpoints
        ]

        # Store full ArchitectOutput on state for downstream agents
        state.__dict__["_architect_output"] = output
        state.plan = plan

        self._log_architect_summary(output)
        state.record_api_call()
        self._log_end(success=True)
        return state

    # ── Parsing ───────────────────────────────────────────────

    def _parse_output(self, raw: str) -> ArchitectOutput:
        try:
            data = json.loads(raw)

            directory_tree = [
                DirectoryNode(
                    path=n.get("path", ""),
                    node_type=n.get("node_type", "file"),
                    purpose=n.get("purpose", ""),
                    module=n.get("module"),
                )
                for n in data.get("directory_tree", [])
            ]

            modules = [
                ModuleBoundary(
                    name=m.get("name", ""),
                    responsibility=m.get("responsibility", ""),
                    public_interface=m.get("public_interface", []),
                    dependencies=m.get("dependencies", []),
                    files=m.get("files", []),
                )
                for m in data.get("modules", [])
            ]

            data_models = []
            for dm in data.get("data_models", []):
                data_models.append(
                    DataModel(
                        name=dm.get("name", ""),
                        description=dm.get("description", ""),
                        fields=dm.get("fields", []),
                        relationships=dm.get("relationships", []),
                    )
                )

            api_endpoints = []
            for ep in data.get("api_endpoints", []):
                api_endpoints.append(
                    ApiEndpoint(
                        method=ep.get("method", "GET"),
                        path=ep.get("path", "/"),
                        description=ep.get("description", ""),
                        request_body=ep.get("request_body"),
                        response_schema=ep.get("response_schema", {}),
                        auth_required=bool(ep.get("auth_required", False)),
                        error_codes=ep.get("error_codes", []),
                    )
                )

            return ArchitectOutput(
                project_root=data.get("project_root", "generated_project"),
                directory_tree=directory_tree,
                modules=modules,
                data_models=data_models,
                api_endpoints=api_endpoints,
                external_dependencies=data.get("external_dependencies", []),
                architectural_decisions=data.get("architectural_decisions", []),
            )

        except (json.JSONDecodeError, TypeError, KeyError, Exception) as exc:
            self._logger.error(f"ArchitectAgent parse error: {exc}")
            return ArchitectOutput(project_root="generated_project")

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _tree_to_dict(tree: List[DirectoryNode]) -> Dict[str, str]:
        return {node.path: node.purpose for node in tree}

    def _log_architect_summary(self, output: ArchitectOutput) -> None:
        self._logger.info(
            f"ArchitectAgent produced: "
            f"{len(output.directory_tree)} files/dirs, "
            f"{len(output.modules)} modules, "
            f"{len(output.data_models)} data models, "
            f"{len(output.api_endpoints)} API endpoints."
        )

    @staticmethod
    def get_output(state: WorkflowState) -> ArchitectOutput | None:
        """Retrieve the stored ArchitectOutput from state."""
        return state.__dict__.get("_architect_output")
