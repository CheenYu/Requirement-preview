from types import SimpleNamespace

from agents.requirement_pre_review.src.config import WorkflowLLMSettings
from agents.requirement_pre_review.src.providers import OpenAICompatibleProvider
from agents.requirement_pre_review.src.schemas import SolutionPlan


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _settings() -> WorkflowLLMSettings:
    return WorkflowLLMSettings(
        model="test-model",
        api_key="test-key",
        base_url="https://example.com/v1",
        temperature=0.2,
        timeout_seconds=30,
        enabled=True,
    )


def test_provider_parses_and_validates_structured_output() -> None:
    provider = OpenAICompatibleProvider(_settings())
    completions = _FakeCompletions(
        [
            _response(
                '{"goal":"完成预审","modules":[],"data_flow":[],"interfaces":[],"milestones":[]}'
            )
        ]
    )
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_structured(
        stage="solution_design",
        system_prompt="生成方案。",
        payload={"requirement_text": "导出订单"},
        output_model=SolutionPlan,
    )

    assert result.output is not None
    assert result.output.goal == "完成预审"
    assert result.record.success is True
    assert result.record.total_tokens == 15
    assert completions.requests[0]["response_format"] == {"type": "json_object"}
    assert completions.requests[0]["max_tokens"] == 4096


def test_provider_reports_invalid_output_for_workflow_fallback() -> None:
    provider = OpenAICompatibleProvider(_settings())
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions([_response("not-json")]))
    )

    result = provider.generate_structured(
        stage="solution_design",
        system_prompt="生成方案。",
        payload={"requirement_text": "导出订单"},
        output_model=SolutionPlan,
    )

    assert result.output is None
    assert result.record.success is False
    assert result.record.fallback_used is True
    assert "JSON" in (result.record.error or "")
