# 每日分析快照字段约定

每日任务在完成研究后，应额外写入 `analysis/daily-analysis-YYYY-MM-DD.json`。

推荐字段如下：

```json
{
  "date": "2026-04-03",
  "generatedAt": "2026-04-03T09:25:00+08:00",
  "coverage": {
    "DDR5-6400": {"filled": 1, "total": 5},
    "DDR5-5600": {"filled": 2, "total": 5},
    "PCIe4 TLC": {"filled": 4, "total": 5},
    "PCIe5 TLC": {"filled": 1, "total": 5},
    "PCIe4 QLC": {"filled": 1, "total": 4}
  },
  "newSourcesTried": ["Provantage", "CDW"],
  "newSourcesWithUsefulData": ["Provantage"],
  "keyChangesVsYesterday": [
    "PCIe4 TLC 3.84TB 中位价小幅回落",
    "DDR5-5600 64GB 恢复到可见报价"
  ],
  "trendJudgement": {
    "DDR5-6400": "unknown",
    "DDR5-5600": "flat_or_mixed",
    "PCIe4 TLC": "flat_or_mixed",
    "PCIe5 TLC": "unknown",
    "PCIe4 QLC": "unknown"
  },
  "procurementView": {
    "DDR5-6400": {
      "recommendation": "insufficient_evidence",
      "reason": "连续缺样本，无法形成可信趋势"
    },
    "PCIe4 TLC": {
      "recommendation": "wait",
      "reason": "价格仍处近7日中高位，且新增信号有限"
    }
  },
  "gaps": [
    {
      "category": "PCIe5 TLC",
      "spec": "7.68TB",
      "reasonCode": "no_public_sample",
      "note": "今日尝试两家备源，仍无公开现货价"
    }
  ]
}
```

## 规则

- `recommendation` 建议值：`buy_now` / `wait` / `split_buy` / `urgent_only` / `insufficient_evidence`
- `reasonCode` 建议值：`no_public_sample` / `parser_gap` / `out_of_scope` / `outlier_only` / `stale_repeated_sample`
- 如果没有足够证据，宁可写 `insufficient_evidence`，不要硬给建议。
