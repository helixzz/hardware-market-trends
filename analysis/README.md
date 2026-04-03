# analysis/

这个目录用于保存每日市场调研任务的辅助分析结果，而不是替代正式日报。

## 文件说明

- `market-history-summary.json`：从 `tracking-table.md` 与最近几天 `raw/*/quotes.json` 汇总得到的滚动历史摘要
- `daily-analysis-YYYY-MM-DD.json`：每日研究任务完成后由 agent 或辅助脚本写入的当日分析快照

## 使用方式

在正式调研之前，先更新 `market-history-summary.json`，让 agent 能够看到：
- 最近 14 天主要价格列的覆盖率
- 相对昨日的变动方向
- 哪些类别长期缺样本
- 最近几天各来源抓取 run notes
