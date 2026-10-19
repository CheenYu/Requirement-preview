from __future__ import annotations

from pathlib import Path

from agents.requirement_pre_review.src.schemas import RequirementReviewReport


EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "order_export_demo"


def test_order_export_example_files_are_present_and_valid() -> None:
    requirement_path = EXAMPLE_DIR / "sample_requirement.txt"
    markdown_path = EXAMPLE_DIR / "sample_report.md"
    json_path = EXAMPLE_DIR / "sample_report.json"

    assert requirement_path.exists()
    assert markdown_path.exists()
    assert json_path.exists()

    requirement_text = requirement_path.read_text(encoding="utf-8")
    markdown_text = markdown_path.read_text(encoding="utf-8")
    report = RequirementReviewReport.model_validate_json(json_path.read_text(encoding="utf-8"))

    assert "订单" in requirement_text
    assert "## 需求摘要" in markdown_text
    assert report.summary
    assert len(report.requirement_items) >= 1
    assert len(report.risks) >= 1
