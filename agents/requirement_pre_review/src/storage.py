"""Artifact persistence for workflow runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.maintenance import ensure_runtime_dirs, get_task_run_dir, get_task_runs_dir

from .schemas import RequirementReviewReport, WorkflowIntermediateArtifacts
from .tool_contracts import ToolCallRecord


class PersistedArtifactIndex(BaseModel):
    run_dir: str
    paths: dict[str, str] = Field(default_factory=dict)


class WorkflowArtifactStore:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_task(cls, task_id: str | None = None) -> "WorkflowArtifactStore":
        ensure_runtime_dirs()
        if task_id:
            return cls(get_task_run_dir(task_id))
        run_dir = get_task_runs_dir() / f"manual-{uuid4().hex[:12]}"
        return cls(run_dir)

    def persist_input(self, payload: dict[str, Any]) -> dict[str, str]:
        requirement_text = str(payload.get("requirement_text", ""))
        return {
            "input_json": self._write_json("input.json", payload),
            "input_text": self._write_text("input.txt", requirement_text),
        }

    def persist_intermediate_artifacts(self, artifacts: WorkflowIntermediateArtifacts) -> dict[str, str]:
        paths = {
            "audit": self._write_json("audit.json", artifacts.audit),
            "clarity": self._write_json("clarity.json", artifacts.clarity),
            "analysis_markdown": self._write_text("analysis.md", artifacts.analysis_markdown),
            "architecture_markdown": self._write_text("architecture.md", artifacts.architecture_markdown),
            "risk_review_markdown": self._write_text("risk_review.md", artifacts.risk_review_markdown),
        }
        return paths

    def persist_report(
        self,
        *,
        report: RequirementReviewReport,
        report_markdown: str,
        report_json_text: str,
        decision_log: list[dict[str, Any]],
        quality_check: dict[str, Any],
        tool_calls: list[ToolCallRecord],
        meta: dict[str, Any],
        stage_results: list[dict[str, Any]],
    ) -> dict[str, str]:
        paths = {
            "report_markdown": self._write_text("report.md", report_markdown),
            "report_json": self._write_text("report.json", report_json_text),
            "decision_log": self._write_json("decision_log.json", decision_log),
            "quality_check": self._write_json("quality_check.json", quality_check),
            "tool_calls": self._write_json(
                "tool_calls.json",
                [record.model_dump(mode="json") for record in tool_calls],
            ),
            "meta": self._write_json("meta.json", meta),
            "stage_results": self._write_json("stage_results.json", stage_results),
            "report_snapshot": self._write_json("report_snapshot.json", report.model_dump(mode="json")),
        }
        return paths

    def persist_index(self, paths: dict[str, str]) -> str:
        index = PersistedArtifactIndex(run_dir=str(self.run_dir), paths=paths)
        return self._write_json("artifact_index.json", index.model_dump(mode="json"))

    def _write_text(self, filename: str, content: str) -> str:
        path = self.run_dir / filename
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _write_json(self, filename: str, payload: Any) -> str:
        path = self.run_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
