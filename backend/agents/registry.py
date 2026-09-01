"""Platform agent registry."""

from __future__ import annotations

from backend.agents.adapters.requirement_pre_review import RequirementPreReviewAgent
from backend.agents.base import BasePlatformAgent
from backend.agents.profiles import PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BasePlatformAgent] = {}

    def register(self, agent: BasePlatformAgent) -> None:
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> BasePlatformAgent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent_id: {agent_id}") from exc

    def list(self) -> list[BasePlatformAgent]:
        return list(self._agents.values())

    def list_profiles(self):
        return [agent.get_profile() for agent in self.list()]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents


def build_default_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(RequirementPreReviewAgent())
    return registry


agent_registry = build_default_registry()

__all__ = [
    "AgentRegistry",
    "PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID",
    "agent_registry",
    "build_default_registry",
]
