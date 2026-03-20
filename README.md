# hardware-market-trends

每日维护两类内容：

1. **硬件市场行情日报**：`daily-YYYY-MM-DD.md`
2. **长期追踪总表**：`tracking-table.md`
3. **市场要闻早报**：`daily-news/daily-news-digest-YYYY-MM-DD.md`

## 当前约定
- 每天新增一个新的日报文件，不覆盖旧文件
- `tracking-table.md` 每天新增一行
- 不再以 CFM（闪存市场）作为主来源
- 优先参考 CoreWaveLabs 与其他企业级现货/B2B 报价网站
- 仅关注企业级产品，不看消费级，不看 PCIe Gen3

## 跟踪范围
### DDR5 企业级内存（单条）
- 6400MT/s：16GB / 32GB / 64GB / 96GB / 128GB
- 5600MT/s：16GB / 32GB / 64GB / 96GB / 128GB

### 企业级 SSD
- PCIe 4.0 TLC, Read-intensive, 1 DWPD：1.92TB / 3.84TB / 7.68TB / 15.36TB / 30.72TB
- PCIe 5.0 TLC, Read-intensive, 1 DWPD：1.92TB / 3.84TB / 7.68TB / 15.36TB / 30.72TB
- PCIe 4.0 QLC, Very-Read-intensive, 0.3–0.6 DWPD：15.36TB / 30.72TB / 61.44TB / 122.88TB

## 目录结构
```text
.
├── daily-YYYY-MM-DD.md
├── tracking-table.md
└── daily-news/
    └── daily-news-digest-YYYY-MM-DD.md
```
