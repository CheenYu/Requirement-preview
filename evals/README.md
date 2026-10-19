# Eval Harness

本目录提供 `Phase 10` 的最小评测回归 harness，用于在调整 prompt、工具规则或门禁阈值后，快速确认工作流没有明显回退。

## 目录结构

- `cases/`：标准化 JSON 样例集，每个文件对应一个回归 case。
- `runner.py`：批量加载 case，运行现有 workflow，并输出 suite 级评测结果。
- `metrics.py`：计算 schema、章节完整度、门禁一致性、工具错误率和工作流耗时。
- `outputs/`：默认运行产物目录，不纳入版本管理。

## Case 格式

每个 case 是一个 JSON 文件，最小字段如下：

```json
{
  "case_id": "clear_order_export",
  "title": "订单导出流程优化",
  "requirement_text": "目标是...",
  "expected_gate_opened": true
}
```

可选字段包括 `target_users`、`explicit_constraints`、`supplemental_context`、`tags`、`notes` 和 `metadata`。

## 评测指标

- `schema_pass_rate`：结构化 `report.json` 是否通过 `RequirementReviewReport` schema 校验。
- `section_completeness`：Markdown 报告是否覆盖固定 8 个章节。
- `gate_decision_consistency`：实际门禁结果与 `expected_gate_opened` 的一致性。
- `tool_error_rate`：工具失败次数 / 工具调用次数。
- `average_workflow_latency_ms`：工作流平均耗时。

## 运行方式

在项目根目录执行：

```bash
python -m evals.runner
```

只跑指定 case：

```bash
python -m evals.runner --case-id clear_order_export --case-id ambiguous_admin_page
```

指定输出目录：

```bash
python -m evals.runner --output-dir /tmp/requirement-pre-review-evals
```

## 输出文件

- `eval_report.json`：suite 级结构化结果，包含 summary 和每个 case 的执行详情。
- `eval_summary.md`：便于快速查看的 Markdown 摘要。
- `cases/<case_id>/case_result.json`：单 case 的评测结果。
- `cases/<case_id>/workflow_artifacts/`：该 case 对应的 workflow 原始产物。
