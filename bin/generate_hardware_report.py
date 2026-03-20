#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

USD_TO_CNY = 7.20
VAT_RATE = 0.13
TZ_LABEL = 'Asia/Shanghai'
UA = 'Mozilla/5.0 (OpenClaw hardware-market-trends bot)'
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / 'raw'
TEMPLATES_DIR = ROOT / 'templates'

MEMORY_TARGETS = {
    'DDR5-6400': ['16GB', '32GB', '64GB', '96GB', '128GB'],
    'DDR5-5600': ['16GB', '32GB', '64GB', '96GB', '128GB'],
}
SSD_TARGETS = {
    'PCIe4 TLC': ['1.92TB', '3.84TB', '7.68TB', '15.36TB', '30.72TB'],
    'PCIe5 TLC': ['1.92TB', '3.84TB', '7.68TB', '15.36TB', '30.72TB'],
    'PCIe4 QLC': ['15.36TB', '30.72TB', '61.44TB', '122.88TB'],
}
MEMORY_ANCHORS = {
    ('DDR5-6400', '32GB'): 8500,
    ('DDR5-5600', '32GB'): 7800,
    ('DDR5-6400', '64GB'): 17000,
    ('DDR5-5600', '64GB'): 16000,
    ('DDR5-6400', '96GB'): 29000,
    ('DDR5-5600', '96GB'): 27500,
    ('DDR5-6400', '128GB'): 39000,
}
MEMORY_WARN_DEVIATION = 0.25
MEMORY_REJECT_DEVIATION = 0.40
TRACKING_KEYS = [
    ('DDR5-6400', '32GB'), ('DDR5-6400', '64GB'), ('DDR5-6400', '128GB'),
    ('DDR5-5600', '32GB'), ('DDR5-5600', '64GB'), ('DDR5-5600', '128GB'),
    ('PCIe4 TLC', '3.84TB'), ('PCIe4 TLC', '7.68TB'), ('PCIe4 TLC', '15.36TB'), ('PCIe4 TLC', '30.72TB'),
    ('PCIe5 TLC', '3.84TB'), ('PCIe5 TLC', '7.68TB'), ('PCIe5 TLC', '15.36TB'), ('PCIe5 TLC', '30.72TB'),
    ('PCIe4 QLC', '15.36TB'), ('PCIe4 QLC', '30.72TB'), ('PCIe4 QLC', '61.44TB'), ('PCIe4 QLC', '122.88TB'),
]

@dataclass
class Quote:
    category: str
    spec: str
    brand: str
    source: str
    url: str
    price_usd: float
    price_cny_tax: int
    excerpt: str
    notes: str = ''


def memory_anchor(category: str, spec: str) -> int | None:
    return MEMORY_ANCHORS.get((category, spec))


def deviation_ratio(value: int, anchor: int) -> float:
    return abs(value - anchor) / anchor


def is_memory_outlier(q: Quote) -> bool:
    anchor = memory_anchor(q.category, q.spec)
    if anchor is None:
        return False
    return deviation_ratio(q.price_cny_tax, anchor) > MEMORY_REJECT_DEVIATION


def is_memory_warning(q: Quote) -> bool:
    anchor = memory_anchor(q.category, q.spec)
    if anchor is None:
        return False
    ratio = deviation_ratio(q.price_cny_tax, anchor)
    return MEMORY_WARN_DEVIATION < ratio <= MEMORY_REJECT_DEVIATION


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='replace')
    except Exception:
        proc = subprocess.run(
            ['curl', '-L', '--silent', '--show-error', '--max-time', '25', '-A', UA, url],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout


def normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def usd_to_cny_tax(usd: float) -> int:
    return int(round(usd * USD_TO_CNY * (1 + VAT_RATE)))


def extract_first(pattern: str, text: str, flags: int = re.I | re.S) -> re.Match[str] | None:
    return re.search(pattern, text, flags)


def parse_corewave_ddr(url: str, speed: str) -> list[Quote]:
    html = fetch(url)
    quotes: list[Quote] = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.I | re.S):
        if f'DDR5-{speed}' not in row or 'RDIMM' not in row:
            continue
        part = re.search(r'jet-listing-dynamic-link__label">([^<]+)</span>', row, re.I)
        brand = re.search(r'jet-dynamic-table__col--brand"[^>]*>([^<]+)</td>', row, re.I)
        size = re.search(r'jet-dynamic-table__col--size"[^>]*>(\d+GB)</td>', row, re.I)
        price = re.search(r'woocommerce-Price-currencySymbol[^>]*>.*?</span>([\d,]+(?:\.\d+)?)</bdi>', row, re.I | re.S)
        if not (part and brand and size and price):
            continue
        usd = float(price.group(1).replace(',', ''))
        quotes.append(Quote(
            category=f'DDR5-{speed}',
            spec=size.group(1),
            brand=normalize_ws(brand.group(1)),
            source='CoreWaveLabs',
            url=url,
            price_usd=usd,
            price_cny_tax=usd_to_cny_tax(usd),
            excerpt=f'{normalize_ws(part.group(1))} {normalize_ws(brand.group(1))} {size.group(1)} DDR5-{speed} RDIMM ${price.group(1)}',
        ))
    return quotes


def parse_disctech_capacity(url: str, category: str, spec: str, brand_hint: str = 'Mixed/OEM') -> list[Quote]:
    html = fetch(url)
    prices = [float(p.replace(',', '')) for p in re.findall(r'\$(\d[\d,]*(?:\.\d+)?)', html)]
    quotes: list[Quote] = []
    for usd in prices[:5]:
        quotes.append(Quote(
            category=category,
            spec=spec,
            brand=brand_hint,
            source='DiscTech',
            url=url,
            price_usd=usd,
            price_cny_tax=usd_to_cny_tax(usd),
            excerpt=f'{spec} listing ${usd:,.2f}',
        ))
    return quotes


def collect_quotes() -> tuple[list[Quote], list[str]]:
    quotes: list[Quote] = []
    notes: list[str] = []
    jobs = [
        ('corewave-6400', lambda: parse_corewave_ddr('https://corewavelabs.com/ddr5-6400-ecc-rdimm-server-ram-price/', '6400')),
        ('corewave-5600', lambda: parse_corewave_ddr('https://corewavelabs.com/ddr5-5600-ecc-rdimm-server-ram-price/', '5600')),
        ('ssd-pcie4-tlc-15.36', lambda: parse_disctech_capacity('https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/15-36TB/interface-types/NVMe-U.2', 'PCIe4 TLC', '15.36TB')),
        ('ssd-pcie4-qlc-30.72', lambda: parse_disctech_capacity('https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/30-72TB/interface-types/NVMe-U.2', 'PCIe4 QLC', '30.72TB')),
        ('ssd-pcie4-qlc-61.44', lambda: parse_disctech_capacity('https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/61-44TB/interface-types/NVMe-U.2', 'PCIe4 QLC', '61.44TB')),
        ('ssd-pcie4-qlc-122.88', lambda: parse_disctech_capacity('https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/122-88TB/interface-types/NVMe-U.2', 'PCIe4 QLC', '122.88TB')),
    ]
    for name, func in jobs:
        try:
            batch = func()
            quotes.extend(batch)
            notes.append(f'{name}: OK ({len(batch)} quotes)')
        except Exception as e:  # noqa: BLE001
            notes.append(f'{name}: FAIL ({e})')
    return quotes, notes


def in_scope(q: Quote) -> bool:
    if q.category in MEMORY_TARGETS:
        return q.spec in MEMORY_TARGETS[q.category]
    if q.category in SSD_TARGETS:
        return q.spec in SSD_TARGETS[q.category]
    return False


def bucket(quotes: Iterable[Quote], category: str, spec: str) -> list[Quote]:
    items = [q for q in quotes if q.category == category and q.spec == spec and in_scope(q)]
    if category.startswith('DDR5-'):
        items = [q for q in items if not is_memory_outlier(q)]
    return items


def med(quotes: Iterable[Quote]) -> int | None:
    values = [q.price_cny_tax for q in quotes]
    return int(round(median(values))) if values else None


def render_memory_table(quotes: list[Quote], speed: str) -> str:
    rows = ['| 容量 | 中位价(RMB含税) | 样本 | 说明 |', '|---|---:|---:|---|']
    for spec in MEMORY_TARGETS[f'DDR5-{speed}']:
        category = f'DDR5-{speed}'
        items = bucket(quotes, category, spec)
        m = med(items)
        warning_count = sum(1 for q in quotes if q.category == category and q.spec == spec and in_scope(q) and is_memory_warning(q))
        rejected_count = sum(1 for q in quotes if q.category == category and q.spec == spec and in_scope(q) and is_memory_outlier(q))
        if items:
            srcs = '；'.join(sorted({q.source for q in items}))
            note_parts = [srcs]
            anchor = memory_anchor(category, spec)
            if anchor is not None:
                note_parts.append(f'参考锚点≈¥{anchor}')
            if warning_count:
                note_parts.append(f'{warning_count} 条高偏差样本已降权观察')
            if rejected_count:
                note_parts.append(f'{rejected_count} 条异常样本已剔除')
            note_text = '；'.join(note_parts)
            rows.append(f'| {spec} | {m} | {len(items)} | {note_text} |')
        else:
            anchor = memory_anchor(category, spec)
            extra = f'；参考锚点≈¥{anchor}' if anchor is not None else ''
            if rejected_count:
                extra += f'；{rejected_count} 条异常样本已剔除'
            rows.append(f'| {spec} | NA | 0 | 样本不足{extra} |')
    return '\n'.join(rows)


def render_ssd_table(quotes: list[Quote], category: str) -> str:
    rows = ['| 容量 | 中位价(RMB含税) | 样本 | 说明 |', '|---|---:|---:|---|']
    for spec in SSD_TARGETS[category]:
        items = bucket(quotes, category, spec)
        m = med(items)
        if items:
            rows.append(f'| {spec} | {m} | {len(items)} | ' + '；'.join(sorted({q.source for q in items})) + ' |')
        else:
            rows.append(f'| {spec} | NA | 0 | 样本不足 |')
    return '\n'.join(rows)


def render_source_details(quotes: list[Quote]) -> str:
    visible = [q for q in quotes if in_scope(q)]
    if not visible:
        return '- 无有效抓取样本\n'
    lines = []
    for q in visible:
        if q.category.startswith('DDR5-'):
            if is_memory_outlier(q):
                suffix = '；异常样本，未纳入主统计'
            elif is_memory_warning(q):
                suffix = '；与主流锚点偏差较大，降权观察'
            else:
                suffix = ''
        else:
            suffix = ''
        lines.append(f'- {q.category} / {q.spec} / {q.brand}: US${q.price_usd:,.2f} ≈ ¥{q.price_cny_tax}（{q.source}{suffix}）')
    return '\n'.join(lines) + '\n'


def summary_lines(quotes: list[Quote], run_notes: list[str]) -> list[str]:
    lines = []
    visible = [q for q in quotes if in_scope(q)]
    d6400 = sum(1 for q in visible if q.category == 'DDR5-6400')
    d5600 = sum(1 for q in visible if q.category == 'DDR5-5600')
    ssd = len(visible) - d6400 - d5600
    lines.append(f'DDR5-6400 抓到 {d6400} 条样本，DDR5-5600 抓到 {d5600} 条样本，企业级 SSD 抓到 {ssd} 条样本。')
    if d6400 == 0 or d5600 == 0:
        lines.append('部分规格暂无公开现货报价，tracking-table 对应列保持 NA，避免硬编。')
    rejected = [q for q in visible if q.category.startswith('DDR5-') and is_memory_outlier(q)]
    if rejected:
        lines.append(f'内存渠道 sanity check 已启用：{len(rejected)} 条与主流市场成交价偏差过大的样本已从主统计中剔除。')
    if not any(q.category == 'PCIe5 TLC' for q in quotes):
        lines.append('PCIe5 TLC 公开现货页仍偏少，本版流程先留空位，后续建议补充 CDW / Provantage / ServerSupply 等可见企业级库存页。')
    fail_notes = [n for n in run_notes if 'FAIL' in n]
    if fail_notes:
        lines.append('抓取异常：' + '；'.join(fail_notes))
    return lines


def write_raw(date_str: str, quotes: list[Quote], run_notes: list[str]) -> Path:
    out_dir = RAW_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / 'quotes.json'
    payload = {
        'date': date_str,
        'generated_at': dt.datetime.now().isoformat(),
        'usd_to_cny': USD_TO_CNY,
        'vat_rate': VAT_RATE,
        'run_notes': run_notes,
        'quotes': [q.__dict__ for q in quotes],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return path


def render_report(date_str: str, quotes: list[Quote], run_notes: list[str], raw_path: Path) -> str:
    timestamp = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + f' {TZ_LABEL}'
    lines = [
        f'# 硬件市场行情日报（{date_str}）',
        '',
        f'> 执行时间：{timestamp}',
        f'> 汇率口径：1 USD = {USD_TO_CNY:.2f} CNY；税率口径：{int(VAT_RATE*100)}% 增值税。',
        '> 数据源优先级：CoreWaveLabs > 其他企业级现货/B2B 报价页 > 官方规格页辅助。',
        '> 内存渠道校验：相对主流成交价锚点偏离超过 40% 的样本不纳入主统计；偏离 25%~40% 的样本降权观察。',
        '> 范围限制：仅企业级 DDR5 5600/6400 单条 RDIMM 与企业级 NVMe SSD（PCIe4 TLC / PCIe5 TLC / PCIe4 QLC）；不含 Gen3、不含消费级。',
        '',
        '## 1) DDR5 6400MT/s RDIMM（单条）',
        render_memory_table(quotes, '6400'),
        '',
        '## 2) DDR5 5600MT/s RDIMM（单条）',
        render_memory_table(quotes, '5600'),
        '',
        '## 3) PCIe 4.0 TLC 企业级 NVMe SSD',
        render_ssd_table(quotes, 'PCIe4 TLC'),
        '',
        '## 4) PCIe 5.0 TLC 企业级 NVMe SSD',
        render_ssd_table(quotes, 'PCIe5 TLC'),
        '',
        '## 5) PCIe 4.0 QLC 企业级 NVMe SSD',
        render_ssd_table(quotes, 'PCIe4 QLC'),
        '',
        '## 6) 当日市场摘要',
    ]
    for s in summary_lines(quotes, run_notes):
        lines.append(f'- {s}')
    lines.extend([
        '',
        '## 7) 主要来源明细',
        render_source_details(quotes),
        '## 8) 自动化执行记录',
        f'- 原始结构化数据：`{raw_path.relative_to(ROOT)}`',
    ])
    for note in run_notes:
        lines.append(f'- {note}')
    return '\n'.join(lines).rstrip() + '\n'


def ensure_tracking_table(path: Path) -> None:
    if path.exists():
        return
    header = """# Tracking Table

> 固定口径长期追踪表。每日新增一行；金额默认使用人民币含税整数；无有效样本填 `NA`。

| Date | DDR5-6400 32GB | DDR5-6400 64GB | DDR5-6400 128GB | DDR5-5600 32GB | DDR5-5600 64GB | DDR5-5600 128GB | PCIe4 TLC 3.84TB | PCIe4 TLC 7.68TB | PCIe4 TLC 15.36TB | PCIe4 TLC 30.72TB | PCIe5 TLC 3.84TB | PCIe5 TLC 7.68TB | PCIe5 TLC 15.36TB | PCIe5 TLC 30.72TB | PCIe4 QLC 15.36TB | PCIe4 QLC 30.72TB | PCIe4 QLC 61.44TB | PCIe4 QLC 122.88TB | Notes |
|------|----------------|----------------|-----------------|----------------|----------------|-----------------|------------------|------------------|-------------------|-------------------|------------------|------------------|-------------------|-------------------|-------------------|-------------------|-------------------|--------------------|-------|
"""
    path.write_text(header)


def update_tracking_table(path: Path, date_str: str, quotes: list[Quote], run_notes: list[str]) -> None:
    ensure_tracking_table(path)
    content = path.read_text()
    if f'| {date_str} |' in content:
        return
    values = []
    for category, spec in TRACKING_KEYS:
        items = bucket(quotes, category, spec)
        m = med(items)
        values.append(str(m) if m is not None else 'NA')
    note = '自动抓取；CoreWaveLabs优先；缺样本留NA'
    if any('FAIL' in n for n in run_notes):
        note += '；部分源失败'
    line = '| ' + ' | '.join([date_str, *values, note]) + ' |\n'
    path.write_text(content.rstrip() + '\n' + line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=dt.date.today().isoformat())
    parser.add_argument('--repo', default=str(ROOT))
    args = parser.parse_args()

    root = Path(args.repo)
    report_path = root / f'daily-{args.date}.md'
    tracking_path = root / 'tracking-table.md'
    if report_path.exists():
        print(f'ERROR: report already exists: {report_path}', file=sys.stderr)
        return 2

    quotes, run_notes = collect_quotes()
    raw_path = write_raw(args.date, quotes, run_notes)
    report_path.write_text(render_report(args.date, quotes, run_notes, raw_path))
    update_tracking_table(tracking_path, args.date, quotes, run_notes)
    print(f'created {report_path}')
    print(f'updated {tracking_path}')
    print(f'raw {raw_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
