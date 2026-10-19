# Risk Reviewer Output

## Risks
- RISK-001 [privacy_security/medium] 隐私与安全约束未被充分定义: 补充数据分级、权限边界、审计和脱敏要求。
- RISK-002 [reliability/medium] 可靠性与异常处理要求不完整: 补充异常流、幂等性、超时重试和监控告警策略。
- RISK-003 [cost_timeline/medium] 交付窗口或成本约束存在实现风险: 拆分里程碑，确认最小可交付范围和关键依赖。
- RISK-004 [operations/medium] 运维与上线准备考虑不足: 提前明确监控指标、日志留存和发布回滚方案。

## Missing Categories
- business_ambiguity, scope_creep, testability

## Notes
- 基于需求文本与方案摘要识别到 4 个风险分类。
- 尚未触达的风险分类：business_ambiguity, scope_creep, testability。
