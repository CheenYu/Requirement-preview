"""Platform agent profile definitions."""

from __future__ import annotations

from backend.models import AgentKind, AgentProfile

from agents.requirement_pre_review.src.agents import build_agent_team
from agents.requirement_pre_review.src.config import WorkflowConfig, load_workflow_config


PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID = "requirement_pre_review"


def build_requirement_pre_review_profile(config: WorkflowConfig | None = None) -> AgentProfile:
    active_config = config or load_workflow_config()
    team = build_agent_team(config=active_config)
    child_agents = team.as_backend_profiles()

    return AgentProfile(
        agent_id=PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
        name="Requirement Pre-Review Agent",
        kind=AgentKind.intake,
        description="Runs the full requirement clarification and solution pre-review workflow.",
        system_prompt=(
            "Orchestrate the requirement pre-review workflow using the internal provider-agnostic tool layer. "
            "Apply the clarity gate before detailed solution design."
        ),
        tools=team.tool_runtime.list_tools(),
        metadata={
            "workflow_entrypoint": "agents.requirement_pre_review.src.workflow.run_workflow",
            "phase": "phase5",
            "clarity_gate_threshold": active_config.clarity_gate_threshold,
            "child_agents": [profile.model_dump(mode="json") for profile in child_agents],
            "supported_outputs": ["markdown", "json"],
            "provider_agnostic": team.function_boundary.provider_agnostic,
        },
    )


def list_platform_profiles(config: WorkflowConfig | None = None) -> list[AgentProfile]:
    return [build_requirement_pre_review_profile(config=config)]
