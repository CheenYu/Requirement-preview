from __future__ import annotations

import json
from pathlib import Path

from evals.runner import DEFAULT_CASES_DIR, load_eval_cases, run_eval_suite


def test_load_eval_cases_returns_standard_suite() -> None:
    cases = load_eval_cases(DEFAULT_CASES_DIR)

    case_ids = [case.case_id for case in cases]
    assert len(cases) >= 5
    assert "clear_order_export" in case_ids
    assert "ambiguous_admin_page" in case_ids
    assert len(case_ids) == len(set(case_ids))


def test_run_eval_suite_generates_suite_outputs(tmp_path: Path, workflow_config) -> None:
    output_dir = tmp_path / "eval-suite"
    report = run_eval_suite(
        cases_dir=DEFAULT_CASES_DIR,
        output_dir=output_dir,
        config=workflow_config,
        case_ids=["clear_order_export", "ambiguous_admin_page"],
    )

    assert report.summary.total_cases == 2
    assert report.summary.schema_pass_rate == 1.0
    assert report.summary.average_section_completeness == 100.0
    assert report.summary.gate_decision_consistency == 1.0
    assert report.summary.tool_error_rate == 0.0
    assert (output_dir / "eval_report.json").exists()
    assert (output_dir / "eval_summary.md").exists()
    assert (output_dir / "cases" / "clear_order_export" / "case_result.json").exists()
    assert (output_dir / "cases" / "clear_order_export" / "workflow_artifacts" / "report.md").exists()

    summary_text = (output_dir / "eval_summary.md").read_text(encoding="utf-8")
    assert "Schema Pass Rate: 100.00%" in summary_text
    assert "clear_order_export" in summary_text
    assert "ambiguous_admin_page" in summary_text

    report_payload = json.loads((output_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert report_payload["summary"]["total_cases"] == 2
    assert len(report_payload["results"]) == 2
    assert all(item["gate_match"] for item in report_payload["results"])
    assert report_payload["results"][0]["evaluation"]["tool_call_count"] >= 4
