"""Application configuration helpers for the backend layer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


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


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str
    base_url: str
    temperature: float
    timeout_seconds: int


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    log_level: str
    data_dir: Path
    evals_dir: Path
    llm: LLMConfig

    def ensure_runtime_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.evals_dir.mkdir(parents=True, exist_ok=True)


def load_app_config() -> AppConfig:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    data_dir_raw = _read_env("DATA_DIR", str(DEFAULT_DATA_DIR))
    data_dir = Path(data_dir_raw).expanduser()
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()

    evals_dir_raw = _read_env("EVALS_DIR", str(PROJECT_ROOT / "evals"))
    evals_dir = Path(evals_dir_raw).expanduser()
    if not evals_dir.is_absolute():
        evals_dir = (PROJECT_ROOT / evals_dir).resolve()

    return AppConfig(
        host=_read_env("APP_HOST", "127.0.0.1"),
        port=_read_int("APP_PORT", 8000),
        log_level=_read_env("LOG_LEVEL", "INFO"),
        data_dir=data_dir,
        evals_dir=evals_dir,
        llm=LLMConfig(
            model=_read_env("LLM_MODEL", "gpt-4.1-mini"),
            api_key=_read_env("LLM_API_KEY", ""),
            base_url=_read_env("LLM_BASE_URL", "https://api.openai.com/v1"),
            temperature=_read_float("LLM_TEMPERATURE", 0.2),
            timeout_seconds=_read_int("LLM_TIMEOUT_SECONDS", 120),
        ),
    )
