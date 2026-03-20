# hardware-market-trends

把“每日硬件市场跟踪”从手工模板升级成了可执行流程：

- 每次运行都会生成新的 `daily-YYYY-MM-DD.md`，已存在则拒绝覆盖
- 自动维护 `tracking-table.md`，每天只追加一行
- 保留结构化原始数据到 `raw/YYYY-MM-DD/quotes.json`
- 口径严格收敛到：
  - 企业级 DDR5 5600/6400 **单条 RDIMM**
  - 企业级 NVMe SSD：**PCIe4 TLC / PCIe5 TLC / PCIe4 QLC**
  - 不含 Gen3，不含消费级
- 数据源优先：**CoreWaveLabs**，再补充其他企业级现货 / B2B 报价页
- 不再以 CFM 为主来源
- DDR5 内存样本会先经过 **主流成交价锚点校验**，偏差过大的渠道不进入主统计

## 目录结构

```text
.
├── bin/
│   └── generate_hardware_report.py
├── daily-news/
├── raw/
│   └── YYYY-MM-DD/
│       └── quotes.json
├── templates/
│   ├── daily-report-template.md
│   └── tracking-table-template.md
├── daily-YYYY-MM-DD.md
└── tracking-table.md
```

## 数据口径

以 workspace 根目录下这两个文件为准：

- `../hardware-config.md`
- `../hardware-db.md`

本仓库里的脚本与模板按这两份文件落地，不再沿用旧的“DDR 颗粒 / 消费级 SSD / CFM 主导”思路。

## 当前自动化能力

### 已实现

1. **DDR5 6400 RDIMM / DDR5 5600 RDIMM**
   - 从 CoreWaveLabs 公开价格页抓取可见单条报价
   - 统一折算为人民币含税价
   - 先按主流市场锚点做 sanity check，异常低价/高价样本降权或剔除
   - 日报写全量规格位，缺样本填 `NA`

2. **企业级 NVMe SSD**
   - 从可见企业级现货/B2B 页面抓取 U.2 NVMe 报价
   - 当前优先解析 DiscTech 容量页里的 JSON-LD `ItemList`，只纳入能明确识别为企业级 Gen4/Gen5 的条目
   - 自动剔除 Gen3、Mixed Use、以及与目标口径不符的页面样本，避免把旧盘/非目标盘误写进 tracking-table
   - 当前已能稳定覆盖 PCIe4 TLC 的 1.92TB / 3.84TB / 7.68TB / 15.36TB；对缺少公开现货页面的规格保留空位，不硬编

3. **长期追踪**
   - 对固定代表列取中位价
   - 同一日期只追加一次

4. **可审计原始数据**
   - 每次运行会落盘 `raw/YYYY-MM-DD/quotes.json`
   - 便于后续调试、补源、改解析逻辑

### 还没完全解决

- PCIe5 TLC 的公开可见现货页样本仍少，当前会保留 `NA`
- 不同 B2B 站点 HTML 差异大，后续最好继续补更多规则源
- 部分企业级 DDR5 公开网页价与真实市场成交口径可能偏离较大，因此当前脚本只把“接近主流锚点”的样本纳入主表

## DDR5 主流成交价锚点（渠道校验）

以下数值用于判断渠道是否可信，不代表每天固定写死：

| 规格 | 锚点（RMB含税） |
|---|---:|
| DDR5-6400 32GB | 8500 |
| DDR5-5600 32GB | 7800 |
| DDR5-6400 64GB | 17000 |
| DDR5-5600 64GB | 16000 |
| DDR5-6400 96GB | 29000 |
| DDR5-5600 96GB | 27500 |
| DDR5-6400 128GB | 39000 |

当前策略：
- 偏离锚点 **25%~40%**：降权观察
- 偏离锚点 **40% 以上**：不纳入 tracking-table 和主行情统计

## 运行方式

在 workspace 根目录执行：

```bash
scripts/daily-hardware-market-check.sh
```

### 市场要闻早报

生成“市场要闻”早报：

```bash
scripts/daily-market-news-digest.sh
```

如已准备好外部中文改写器（可选），可通过环境变量接入批量重写；脚本会把 JSON 任务通过 stdin 传给该命令，要求其输出等长 JSON 数组：

```bash
export MARKET_NEWS_REWRITER_CMD='python3 /path/to/your_rewriter.py'
scripts/daily-market-news-digest.sh
```

约束与策略：
- 最多 10 条
- 单条摘要不超过 140 字
- 全部摘要总长不超过 2000 字
- 默认先按英文公开 RSS 聚合抓取，再做中文晨报式压缩
- 若外部改写器不可用、返回非 JSON、超时或失败，会自动回退到本地规则压缩，不影响日报生成

输出位置：
- `daily-news/daily-news-digest-YYYY-MM-DD.md`

或指定日期回填：

```bash
scripts/daily-hardware-market-check.sh 2026-03-20
```

也可以直接进仓库执行：

```bash
cd /Users/helixzz/.openclaw/workspace/hardware-market-trends
python3 bin/generate_hardware_report.py --date 2026-03-20
```

## 输出规则

- 日报：`daily-YYYY-MM-DD.md`
- 跟踪表：`tracking-table.md`
- 原始抓取：`raw/YYYY-MM-DD/quotes.json`

日报永不覆盖；如果当天文件已存在，脚本直接报错退出。

## Git 提交流程

```bash
cd /Users/helixzz/.openclaw/workspace/hardware-market-trends
git add .
git commit -m "Automate daily hardware market tracking"
```

如需把 workspace 里的包装脚本也一起提交：

```bash
cd /Users/helixzz/.openclaw/workspace
git add scripts/daily-hardware-market-check.sh hardware-config.md hardware-db.md hardware-market-trends
git commit -m "Upgrade hardware market tracking automation"
```
