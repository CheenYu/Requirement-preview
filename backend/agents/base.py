"""Platform agent base abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models import AgentProfile, AgentRequest, AgentResponse


class BasePlatformAgent(ABC):
    """Shared platform-facing contract for runnable agents."""

    def __init__(self, profile: AgentProfile) -> None:
        self._profile = profile

    @property
    def agent_id(self) -> str:
        return self._profile.agent_id

    @property
    def profile(self) -> AgentProfile:
        return self._profile.model_copy(deep=True)

    def get_profile(self) -> AgentProfile:
        return self.profile

    def validate_request(self, request: AgentRequest) -> AgentRequest:
        return AgentRequest.model_validate(request)

    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the agent against a validated platform request."""
