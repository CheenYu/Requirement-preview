"""Workflow runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read_env(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _read_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _read_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _read_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean value")


@dataclass(frozen=True)
class WorkflowLLMSettings:
    model: str
    api_key: str
    base_url: str
    temperature: float
    timeout_seconds: int
    enabled: bool = False
    max_tokens: int = 4096


@dataclass(frozen=True)
class WorkflowConfig:
    llm: WorkflowLLMSettings
    max_requirement_length: int
    clarity_gate_threshold: int
    max_open_questions: int
    max_risks_per_run: int

    def validate(self) -> None:
        if self.llm.max_tokens <= 0:
            raise ValueError("LLM_MAX_TOKENS must be positive")
        if self.max_requirement_length <= 0:
            raise ValueError("max_requirement_length must be positive")
        if not 0 <= self.clarity_gate_threshold <= 100:
            raise ValueError("clarity_gate_threshold must be between 0 and 100")
        if self.max_open_questions <= 0:
            raise ValueError("max_open_questions must be positive")
        if self.max_risks_per_run <= 0:
            raise ValueError("max_risks_per_run must be positive")


def load_workflow_config() -> WorkflowConfig:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    config = WorkflowConfig(
        llm=WorkflowLLMSettings(
            model=_read_env("LLM_MODEL", "gpt-4.1-mini"),
            api_key=_read_env("LLM_API_KEY", ""),
            base_url=_read_env("LLM_BASE_URL", "https://api.openai.com/v1"),
            temperature=_read_float("LLM_TEMPERATURE", 0.2),
            timeout_seconds=_read_int("LLM_TIMEOUT_SECONDS", 120),
            enabled=_read_bool("LLM_ENABLED", False),
            max_tokens=_read_int("LLM_MAX_TOKENS", 4096),
        ),
        max_requirement_length=_read_int("MAX_REQUIREMENT_LENGTH", 50000),
        clarity_gate_threshold=_read_int("CLARITY_GATE_THRESHOLD", 65),
        max_open_questions=_read_int("MAX_OPEN_QUESTIONS", 12),
        max_risks_per_run=_read_int("MAX_RISKS_PER_RUN", 12),
    )
    config.validate()
    return config
