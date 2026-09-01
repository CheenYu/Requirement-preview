"""Agent assembly for the requirement pre-review workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.models import AgentKind, AgentProfile

from .config import WorkflowConfig, load_workflow_config
from .prompts import PROMPT_TEMPLATES, build_prompt_library
from .tools import ToolRuntime, get_tool_runtime


@dataclass(frozen=True)
class FunctionInterfaceBoundary:
    provider_agnostic: bool = True
    native_function_calling_required: bool = False
    notes: tuple[str, ...] = (
        "Primary execution path uses internal Python functions with Pydantic input/output contracts.",
        "External model providers should adapt to the internal tool runtime instead of redefining tool schemas.",
        "Provider-specific native function calling is optional and should be attached through adapters only.",
    )


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    display_name: str
    kind: AgentKind
    responsibility: str
    allowed_tools: list[str] = field(default_factory=list)
    handoff_to: str | None = None
    expected_output: str = ""
    system_prompt: str = ""


@dataclass
class RequirementPreReviewTeam:
    config: WorkflowConfig
    tool_runtime: ToolRuntime
    function_boundary: FunctionInterfaceBoundary
    agents: dict[str, AgentDefinition]
    execution_order: list[str]

    def list_agents(self) -> list[AgentDefinition]:
        return [self.agents[agent_id] for agent_id in self.execution_order]

    def get_agent(self, agent_id: str) -> AgentDefinition:
        return self.agents[agent_id]

    def list_tool_contracts(self) -> list[dict[str, Any]]:
        return [self.tool_runtime.describe_tool(tool_name) for tool_name in self.tool_runtime.list_tools()]

    def as_backend_profiles(self) -> list[AgentProfile]:
        profiles: list[AgentProfile] = []
        for agent in self.list_agents():
            profiles.append(
                AgentProfile(
                    agent_id=agent.agent_id,
                    name=agent.display_name,
                    kind=agent.kind,
                    description=agent.responsibility,
                    system_prompt=agent.system_prompt,
                    tools=agent.allowed_tools,
                    metadata={
                        "handoff_to": agent.handoff_to,
                        "expected_output": agent.expected_output,
                        "function_boundary": {
                            "provider_agnostic": self.function_boundary.provider_agnostic,
                            "native_function_calling_required": self.function_boundary.native_function_calling_required,
                        },
                    },
                )
            )
        return profiles

    def build_external_function_specs(self) -> list[dict[str, Any]]:
        return self.list_tool_contracts()

    def build_hello_agents_tool_registry(self) -> Any:
        try:
            from hello_agents.tools import Tool, ToolParameter, ToolRegistry
        except Exception as exc:  # pragma: no cover - import path depends on runtime package
            raise RuntimeError("hello_agents is not available for optional tool registry bridging") from exc

        runtime = self.tool_runtime

        class ContractBridgeTool(Tool):
            def __init__(self, tool_name: str, description: str) -> None:
                super().__init__(name=tool_name, description=description)
                self._tool_name = tool_name

            def run(self, parameters: dict[str, Any]) -> str:
                raw_payload = parameters.get("payload", parameters.get("input", "{}"))
                if isinstance(raw_payload, str):
                    try:
                        payload = json.loads(raw_payload)
                    except json.JSONDecodeError:
                        payload = {"requirement_text": raw_payload}
                elif isinstance(raw_payload, dict):
                    payload = raw_payload
                else:
                    payload = {"payload": raw_payload}

                result = runtime.invoke(self._tool_name, payload)
                return json.dumps(
                    {
                        "success": result.success,
                        "output": result.output,
                        "error": result.error.model_dump(mode="json") if result.error else None,
                    },
                    ensure_ascii=False,
                )

            def get_parameters(self) -> list[Any]:
                return [
                    ToolParameter(
                        name="payload",
                        type="string",
                        description="JSON object serialized as string for the internal tool contract.",
                        required=True,
                    )
                ]

        registry = ToolRegistry()
        for tool_spec in self.list_tool_contracts():
            registry.register_tool(ContractBridgeTool(tool_spec["name"], tool_spec["description"]))
        return registry


def build_agent_team(
    *,
    config: WorkflowConfig | None = None,
    tool_runtime: ToolRuntime | None = None,
) -> RequirementPreReviewTeam:
    active_config = config or load_workflow_config()
    active_runtime = tool_runtime or get_tool_runtime(active_config)
    prompt_library = build_prompt_library(active_config)

    agents = {
        "requirement_analyst": AgentDefinition(
            agent_id="requirement_analyst",
            display_name="Requirement Analyst",
            kind=AgentKind.intake,
            responsibility="Audit the requirement package, identify missing dimensions, and apply the clarity gate.",
            allowed_tools=["requirement-audit", "clarity-score"],
            handoff_to="solution_architect",
            expected_output="Audit summary, clarification questions, numbered requirements, and gate decision.",
            system_prompt=prompt_library["requirement_analyst"],
        ),
        "solution_architect": AgentDefinition(
            agent_id="solution_architect",
            display_name="Solution Architect",
            kind=AgentKind.analyzer,
            responsibility="Draft scope and implementation approach only after the clarity gate passes.",
            allowed_tools=["requirement-audit", "clarity-score", "report-export"],
            handoff_to="risk_reviewer",
            expected_output="Scope proposal, solution modules, interface draft, and milestone outline.",
            system_prompt=prompt_library["solution_architect"],
        ),
        "risk_reviewer": AgentDefinition(
            agent_id="risk_reviewer",
            display_name="Risk Reviewer",
            kind=AgentKind.reviewer,
            responsibility="Run a fixed risk taxonomy review and identify mitigations before report synthesis.",
            allowed_tools=["risk-taxonomy-check", "clarity-score"],
            handoff_to="report_synthesizer",
            expected_output="Risk list with severity, mitigation, owner, and missing risk categories.",
            system_prompt=prompt_library["risk_reviewer"],
        ),
        "report_synthesizer": AgentDefinition(
            agent_id="report_synthesizer",
            display_name="Report Synthesizer",
            kind=AgentKind.synthesizer,
            responsibility="Merge structured artifacts into a fixed-format report and validate final quality.",
            allowed_tools=["report-quality-check", "report-export"],
            handoff_to=None,
            expected_output="RequirementReviewReport JSON plus fixed-section Markdown export.",
            system_prompt=prompt_library["report_synthesizer"],
        ),
    }

    return RequirementPreReviewTeam(
        config=active_config,
        tool_runtime=active_runtime,
        function_boundary=FunctionInterfaceBoundary(),
        agents=agents,
        execution_order=list(PROMPT_TEMPLATES.keys()),
    )
