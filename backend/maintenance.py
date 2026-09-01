"""Runtime directory helpers and cleanup for generated artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config import load_app_config


TASK_RUN_RETENTION_DAYS = 7
EVAL_OUTPUT_RETENTION_DAYS = 14


def ensure_runtime_dirs() -> dict[str, str]:
    config = load_app_config()
    config.ensure_runtime_dirs()

    task_runs_dir = get_task_runs_dir()
    eval_outputs_dir = get_eval_outputs_dir()
    task_runs_dir.mkdir(parents=True, exist_ok=True)
    eval_outputs_dir.mkdir(parents=True, exist_ok=True)

    return {
        "data_dir": str(config.data_dir),
        "evals_dir": str(config.evals_dir),
        "task_runs_dir": str(task_runs_dir),
        "eval_outputs_dir": str(eval_outputs_dir),
    }


def get_task_runs_dir() -> Path:
    return load_app_config().data_dir / "task_runs"


def get_task_run_dir(task_id: str) -> Path:
    run_dir = get_task_runs_dir() / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def get_eval_outputs_dir() -> Path:
    return load_app_config().evals_dir / "outputs"


def cleanup_runtime_artifacts(*, force: bool = False) -> dict[str, Any]:
    ensure_runtime_dirs()
    task_stats = _cleanup_children(
        get_task_runs_dir(),
        retention_days=TASK_RUN_RETENTION_DAYS,
        delete_dirs=True,
        force=force,
    )
    eval_stats = _cleanup_children(
        get_eval_outputs_dir(),
        retention_days=EVAL_OUTPUT_RETENTION_DAYS,
        delete_dirs=True,
        force=force,
    )
    return {
        "task_runs": task_stats,
        "eval_outputs": eval_stats,
    }


def _cleanup_children(
    root: Path,
    *,
    retention_days: int,
    delete_dirs: bool,
    force: bool,
) -> dict[str, int]:
    stats = {"deleted_files": 0, "deleted_dirs": 0, "deleted_bytes": 0}
    if not root.exists():
        return stats

    cutoff = datetime.now() - timedelta(days=retention_days)
    for child in root.iterdir():
        if not force and datetime.fromtimestamp(child.stat().st_mtime) >= cutoff:
            continue
        if child.is_dir() and delete_dirs:
            stats["deleted_bytes"] += _directory_size(child)
            shutil.rmtree(child)
            stats["deleted_dirs"] += 1
            continue
        if child.is_file():
            stats["deleted_bytes"] += child.stat().st_size
            child.unlink()
            stats["deleted_files"] += 1
    return stats


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
