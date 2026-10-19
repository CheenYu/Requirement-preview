"""LLM provider adapters for OpenAI-compatible chat completion APIs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .config import WorkflowConfig, WorkflowLLMSettings


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class LLMCallRecord(BaseModel):
    stage: str
    provider: str = "openai-compatible"
    model: str
    success: bool
    fallback_used: bool = False
    duration_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    json_mode_used: bool = True
    error: str | None = None


@dataclass(frozen=True)
class StructuredGeneration(Generic[StructuredOutputT]):
    output: StructuredOutputT | None
    record: LLMCallRecord


class OpenAICompatibleProvider:
    """Generate Pydantic-validated output through an OpenAI-compatible API."""

    def __init__(self, settings: WorkflowLLMSettings) -> None:
        if not settings.api_key:
            raise ValueError("LLM_API_KEY is required when LLM_ENABLED=true")

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency failure
            raise RuntimeError("The `openai` package is required for LLM provider access") from exc

        self.settings = settings
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=1,
        )

    def generate_structured(
        self,
        *,
        stage: str,
        system_prompt: str,
        payload: dict[str, Any],
        output_model: type[StructuredOutputT],
    ) -> StructuredGeneration[StructuredOutputT]:
        started_at = perf_counter()
        json_mode_used = True
        try:
            response = self._create_completion(
                system_prompt=system_prompt,
                payload=payload,
                output_model=output_model,
                json_mode=True,
            )
        except Exception as exc:
            if not self._is_json_mode_compatibility_error(exc):
                return self._failure(stage, started_at, exc, json_mode_used=True)
            json_mode_used = False
            try:
                response = self._create_completion(
                    system_prompt=system_prompt,
                    payload=payload,
                    output_model=output_model,
                    json_mode=False,
                )
            except Exception as retry_exc:
                return self._failure(stage, started_at, retry_exc, json_mode_used=False)

        try:
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Provider returned an empty response")
            parsed = output_model.model_validate_json(self._extract_json(content))
        except (IndexError, AttributeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            return self._failure(stage, started_at, exc, json_mode_used=json_mode_used)

        usage = getattr(response, "usage", None)
        record = LLMCallRecord(
            stage=stage,
            model=self.settings.model,
            success=True,
            duration_ms=int((perf_counter() - started_at) * 1000),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            json_mode_used=json_mode_used,
        )
        return StructuredGeneration(output=parsed, record=record)

    def _create_completion(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        output_model: type[BaseModel],
        json_mode: bool,
    ):
        schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    "只输出一个 JSON 对象，不要输出 Markdown 代码块或额外解释。"
                    "输出必须满足下面的 JSON Schema；缺失信息用空数组或空字符串表示，不得捏造事实。\n"
                    f"JSON Schema:\n{schema}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ]
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        return self.client.chat.completions.create(**request)

    @staticmethod
    def _extract_json(content: str) -> str:
        stripped = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            stripped = fenced.group(1).strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Provider response does not contain a JSON object")
        return stripped[start : end + 1]

    @staticmethod
    def _is_json_mode_compatibility_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {400, 404, 415, 422}:
            return True
        return isinstance(exc, TypeError)

    def _failure(
        self,
        stage: str,
        started_at: float,
        exc: Exception,
        *,
        json_mode_used: bool,
    ) -> StructuredGeneration[Any]:
        record = LLMCallRecord(
            stage=stage,
            model=self.settings.model,
            success=False,
            fallback_used=True,
            duration_ms=int((perf_counter() - started_at) * 1000),
            json_mode_used=json_mode_used,
            error=f"{type(exc).__name__}: {exc}",
        )
        return StructuredGeneration(output=None, record=record)


def build_llm_provider(config: WorkflowConfig) -> OpenAICompatibleProvider | None:
    if not config.llm.enabled:
        return None
    return OpenAICompatibleProvider(config.llm)


__all__ = [
    "LLMCallRecord",
    "OpenAICompatibleProvider",
    "StructuredGeneration",
    "build_llm_provider",
]
