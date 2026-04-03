#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable

USD_TO_CNY = 7.20
VAT_RATE = 0.13
TZ_LABEL = 'Asia/Shanghai'
UA = 'Mozilla/5.0 (OpenClaw hardware-market-trends bot)'
DEFAULT_ROOT = Path(__file__).resolve().parents[1]

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
DISCTECH_CAPACITY_URLS = {
    '1.92TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/1-92TB/interface-types/NVMe-U.2',
    '3.84TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/3-84TB/interface-types/NVMe-U.2',
    '7.68TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/7-68TB/interface-types/NVMe-U.2',
    '15.36TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/15-36TB/interface-types/NVMe-U.2',
    '30.72TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/30-72TB/interface-types/NVMe-U.2',
    '61.44TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/61-44TB/interface-types/NVMe-U.2',
    '122.88TB': 'https://www.disctech.com/data-storage/internal-storage/ssd-solid-state-drives/capacity/122-88TB/interface-types/NVMe-U.2',
}
PROVANTAGE_QUERY_URLS = {
    'provantage-ddr5-rdimm': 'https://www.provantage.com/service/searchsvcs?QUERY=DDR5+RDIMM+ECC',
    'provantage-pcie5': 'https://www.provantage.com/service/searchsvcs?QUERY=PM1743+U.2',
    'provantage-qlc': 'https://www.provantage.com/service/searchsvcs?QUERY=Solidigm+D5-P5336',
}
VALID_RECOMMENDATIONS = {'buy_now', 'wait', 'split_buy', 'urgent_only', 'insufficient_evidence'}
VALID_GAP_REASON_CODES = {'no_public_sample', 'parser_gap', 'out_of_scope', 'outlier_only', 'stale_repeated_sample'}


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
        with urllib.request.urlopen(req, timeout=25) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='replace')
    except Exception:
        proc = subprocess.run(
            ['curl', '-L', '--silent', '--show-error', '--max-time', '30', '-A', UA, url],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout


def normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def usd_to_cny_tax(usd: float) -> int:
    return int(round(usd * USD_TO_CNY * (1 + VAT_RATE)))


def parse_corewave_ddr(url: str, speed: str) -> list[Quote]:
    html_text = fetch(url)
    quotes: list[Quote] = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html_text, re.I | re.S):
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
    return dedupe_quotes(quotes)


def classify_memory_listing(name: str, description: str) -> tuple[str, str] | None:
    text = normalize_ws(f'{name} {description}').lower()
    if 'ddr5' not in text:
        return None
    if 'rdimm' not in text and 'registered' not in text:
        return None
    speed = None
    if '6400' in text or 'pc5-51200' in text:
        speed = '6400'
    elif '5600' in text or 'pc5-44800' in text:
        speed = '5600'
    if speed is None:
        return None
    spec = None
    for candidate in MEMORY_TARGETS[f'DDR5-{speed}']:
        if candidate.lower() in text:
            spec = candidate
            break
    if spec is None:
        return None
    return f'DDR5-{speed}', spec


def extract_jsonld_itemlist(html_text: str) -> list[dict]:
    for match in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html_text, re.I | re.S):
        raw = match.group(1).strip()
        if 'itemListElement' not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        graph = payload.get('@graph', []) if isinstance(payload, dict) else []
        for node in graph:
            if isinstance(node, dict) and node.get('@type') == 'ItemList':
                return node.get('itemListElement', [])
    return []


def parse_price_value(offers: object) -> float | None:
    if isinstance(offers, dict):
        value = offers.get('price')
        return float(value) if value is not None else None
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict) and offer.get('price') is not None:
                return float(offer['price'])
    return None


def classify_ssd_listing(name: str, description: str, spec: str) -> tuple[str, str] | None:
    text = normalize_ws(f'{name} {description}').lower()
    normalized_spec = spec.lower().replace(' ', '')
    if normalized_spec not in text.replace(' ', '') and spec.lower() not in text:
        return None
    if 'pcie 5.0' in text or 'pcie5' in text or 'gen5' in text:
        category = 'PCIe5 TLC'
    elif 'pcie 4.0' in text or 'pcie 4x4' in text or 'gen4' in text:
        category = 'PCIe4 TLC'
    else:
        return None

    qlc_markers = (' qlc', 'p5316', 'p5336', 'p5430', 'very read intensive', 'vri', 'solidigm d5-', 'd5-p')
    if any(marker in text for marker in qlc_markers):
        if category == 'PCIe4 TLC':
            category = 'PCIe4 QLC'
        else:
            return None

    if category == 'PCIe4 TLC' and ('mixed use' in text or 'mu ' in text or 'write intensive' in text or 'wi ' in text):
        return None

    if category == 'PCIe4 QLC' and spec not in SSD_TARGETS['PCIe4 QLC']:
        return None
    if category == 'PCIe5 TLC' and spec not in SSD_TARGETS['PCIe5 TLC']:
        return None
    if category == 'PCIe4 TLC' and spec not in SSD_TARGETS['PCIe4 TLC']:
        return None

    brand_match = re.match(r'([A-Za-z0-9-]+)', name.strip())
    brand = brand_match.group(1) if brand_match else 'Mixed/OEM'
    return category, brand


def parse_provantage_price(fragment: str) -> float | None:
    match = re.search(r'BOX5PRICE><sup class=DS>\$</sup>([\d,]+)\.<sup class=CENTS>(\d{2})</sup>', fragment, re.I)
    if not match:
        return None
    return float(match.group(1).replace(',', '') + '.' + match.group(2))


def strip_tags(text: str) -> str:
    return normalize_ws(html.unescape(re.sub(r'<[^>]+>', ' ', text)))


def provantage_blocks(html_text: str) -> list[tuple[str, str, str, str, str]]:
    pattern = re.compile(
        r"<div class=BOX5A>.*?<div class=BOX5B><p><a class=BOX5PRODUCT href='([^']+)'>(.*?)</a></p>"
        r"<p class=BOX5TEXT><b><a href='[^']+'>(.*?)</a></b>.*?</p><p class=BOX5TEXT>(.*?)</p></div>"
        r"<div class=BOX5C>(.*?)</div><div style='clear:both;'></div>",
        re.I | re.S,
    )
    return pattern.findall(html_text)


def infer_ssd_spec(text: str) -> str | None:
    lowered = text.lower().replace(' ', '')
    all_specs = set()
    for specs in SSD_TARGETS.values():
        all_specs.update(specs)
    for spec in sorted(all_specs, key=len, reverse=True):
        if spec.lower().replace(' ', '') in lowered:
            return spec
    return None


def parse_provantage_results(url: str) -> list[Quote]:
    html_text = fetch(url)
    quotes: list[Quote] = []
    for href, raw_name, raw_brand, raw_desc, raw_price_block in provantage_blocks(html_text):
        name = strip_tags(raw_name)
        brand = strip_tags(raw_brand)
        description = strip_tags(raw_desc)
        price_usd = parse_provantage_price(raw_price_block)
        if price_usd is None:
            continue
        memory_class = classify_memory_listing(name, description)
        if memory_class is not None:
            category, spec = memory_class
        else:
            spec = infer_ssd_spec(f'{name} {description}')
            if spec is None:
                continue
            classified = classify_ssd_listing(name, description, spec)
            if not classified:
                continue
            category, parsed_brand = classified
            if brand.lower() in {'', 'generic'}:
                brand = parsed_brand
        full_url = href if href.startswith('http') else f'https://www.provantage.com{href}'
        quotes.append(Quote(
            category=category,
            spec=spec,
            brand=brand,
            source='Provantage',
            url=full_url,
            price_usd=price_usd,
            price_cny_tax=usd_to_cny_tax(price_usd),
            excerpt=normalize_ws(f'{name} | {description}')[:260],
            notes='Provantage search result parsed',
        ))
    return dedupe_quotes(quotes)


def parse_disctech_jsonld(url: str, spec: str) -> list[Quote]:
    html_text = fetch(url)
    items = extract_jsonld_itemlist(html_text)
    quotes: list[Quote] = []
    for entry in items:
        item = entry.get('item', {}) if isinstance(entry, dict) else {}
        if not isinstance(item, dict):
            continue
        name = html.unescape(item.get('name', ''))
        description = html.unescape(re.sub('<[^>]+>', ' ', item.get('description', '')))
        price_usd = parse_price_value(item.get('offers'))
        if not name or price_usd is None:
            continue
        classified = classify_ssd_listing(name, description, spec)
        if not classified:
            continue
        category, brand = classified
        excerpt = normalize_ws(f'{name} | {description}')[:260]
        quotes.append(Quote(
            category=category,
            spec=spec,
            brand=brand,
            source='DiscTech',
            url=item.get('url', url),
            price_usd=price_usd,
            price_cny_tax=usd_to_cny_tax(price_usd),
            excerpt=excerpt,
            notes='JSON-LD itemList parsed and interface/gen filtered',
        ))
    return dedupe_quotes(quotes)


def dedupe_quotes(quotes: Iterable[Quote]) -> list[Quote]:
    seen: set[tuple[str, str, str, str, str, float]] = set()
    out: list[Quote] = []
    for q in quotes:
        key = (q.category, q.spec, q.brand, q.source, q.url, round(q.price_usd, 2))
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def load_history_summary(root: Path) -> dict[str, Any]:
    return load_json(root / 'analysis' / 'market-history-summary.json')


def load_sources_registry(root: Path) -> dict[str, Any]:
    return load_json(root / 'sources-registry.json')


def parse_attempted_sources(run_notes: list[str]) -> list[str]:
    sources: set[str] = set()
    mapping = {
        'corewave-': 'CoreWaveLabs',
        'disctech-': 'DiscTech',
        'provantage-': 'Provantage',
    }
    for note in run_notes:
        for prefix, label in mapping.items():
            if note.startswith(prefix):
                sources.add(label)
                break
    return sorted(sources)


def recent_known_sources(root: Path, days: int = 7, exclude_dates: set[str] | None = None) -> set[str]:
    raw_root = root / 'raw'
    if not raw_root.exists():
        return set()
    excluded = exclude_dates or set()
    sources: set[str] = set()
    history_dirs = [path for path in raw_root.iterdir() if path.is_dir() and path.name not in excluded]
    for day_dir in sorted(history_dirs)[-days:]:
        payload = load_json(day_dir / 'quotes.json')
        for item in payload.get('quotes', []):
            if isinstance(item, dict) and item.get('source'):
                sources.add(str(item['source']))
    return sources


def category_specs(category: str) -> list[str]:
    if category in MEMORY_TARGETS:
        return MEMORY_TARGETS[category]
    return SSD_TARGETS[category]


def all_categories() -> list[str]:
    return [*MEMORY_TARGETS, *SSD_TARGETS]


def coverage_for_category(quotes: list[Quote], category: str) -> dict[str, int]:
    specs = category_specs(category)
    filled = sum(1 for spec in specs if bucket(quotes, category, spec))
    return {'filled': filled, 'total': len(specs)}


def history_category(history_summary: dict[str, Any], category: str) -> dict[str, Any]:
    categories = history_summary.get('categories', {})
    value = categories.get(category, {})
    return value if isinstance(value, dict) else {}


def history_column(history_summary: dict[str, Any], category: str, spec: str) -> dict[str, Any]:
    category_data = history_category(history_summary, category)
    columns = category_data.get('columns', {})
    key = f'{category} {spec}'
    value = columns.get(key, {})
    return value if isinstance(value, dict) else {}


def median_map(quotes: list[Quote], category: str) -> dict[str, int | None]:
    return {spec: med(bucket(quotes, category, spec)) for spec in category_specs(category)}


def mean_ratio_against_history(current: dict[str, int | None], history_values: dict[str, Any]) -> float | None:
    ratios: list[float] = []
    for spec, value in current.items():
        if value is None:
            continue
        ref = history_values.get(spec)
        if isinstance(ref, (int, float)) and ref > 0:
            ratios.append((value - float(ref)) / float(ref))
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def classify_trend(category: str, current: dict[str, int | None], history_summary: dict[str, Any]) -> str:
    coverage = coverage_for_category_from_values(current)
    if coverage['filled'] == 0:
        return 'unknown'
    category_history = history_category(history_summary, category)
    previous_values = current_history_map(category, category_history.get('previousValues', {}))
    rolling_values = current_history_map(category, category_history.get('rollingMedians14d', {}))
    diff_prev = mean_ratio_against_history(current, previous_values)
    if diff_prev is not None:
        if diff_prev >= 0.03:
            return 'up'
        if diff_prev <= -0.03:
            return 'down'
    diff_roll = mean_ratio_against_history(current, rolling_values)
    if diff_roll is not None:
        if diff_roll >= 0.06:
            return 'up'
        if diff_roll <= -0.06:
            return 'down'
    return str(category_history.get('trend', 'flat_or_mixed') or 'flat_or_mixed')


def current_history_map(category: str, values: Any) -> dict[str, int | None]:
    if not isinstance(values, dict):
        return {}
    out: dict[str, int | None] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            continue
        prefix = f'{category} '
        spec = key[len(prefix):] if key.startswith(prefix) else key
        out[spec] = int(value) if isinstance(value, (int, float)) else None
    return out


def coverage_for_category_from_values(values: dict[str, int | None]) -> dict[str, int]:
    return {'filled': sum(1 for value in values.values() if value is not None), 'total': len(values)}


def useful_sources(quotes: list[Quote], category: str) -> list[str]:
    return sorted({q.source for q in quotes if q.category == category and in_scope(q)})


def classify_procurement(category: str, current_values: dict[str, int | None], history_summary: dict[str, Any], sources: list[str]) -> dict[str, str]:
    coverage = coverage_for_category_from_values(current_values)
    category_history = history_category(history_summary, category)
    rolling_values = current_history_map(category, category_history.get('rollingMedians14d', {}))
    diff_roll = mean_ratio_against_history(current_values, rolling_values)
    if coverage['filled'] == 0:
        missing_columns = category_history.get('missingColumns', [])
        reason = '连续缺样本，无法形成可信趋势。' if missing_columns else '当前没有足够有效样本，无法形成可信趋势。'
        return {'recommendation': 'insufficient_evidence', 'reason': reason}
    if coverage['filled'] < max(1, coverage['total'] // 2):
        return {'recommendation': 'urgent_only', 'reason': '覆盖率偏低，且样本不足以支撑常规采购判断，仅建议应急采购。'}
    if diff_roll is not None and diff_roll >= 0.08:
        return {'recommendation': 'wait', 'reason': '当前价格整体高于近14天中位水平，且没有看到足够强的改善信号。'}
    if diff_roll is not None and diff_roll <= -0.08 and len(sources) >= 1:
        return {'recommendation': 'buy_now', 'reason': '当前价格整体低于近14天中位水平，且已有可见公开样本支撑。'}
    if len(sources) <= 1:
        return {'recommendation': 'split_buy', 'reason': '价格信号有限且来源集中，适合分批采购而不是一次性重仓。'}
    return {'recommendation': 'split_buy', 'reason': '价格接近近期中位水平，建议分批采购并继续观察新增来源。'}


def classify_gap_reason(category: str, spec: str, quotes: list[Quote], history_summary: dict[str, Any]) -> tuple[str, str]:
    direct_quotes = [q for q in quotes if q.category == category and q.spec == spec and in_scope(q)]
    if category.startswith('DDR5-') and direct_quotes and all(is_memory_outlier(q) for q in direct_quotes):
        return 'outlier_only', '仅发现明显偏离主流锚点的样本，未写入主表。'
    column_history = history_column(history_summary, category, spec)
    last_seen = column_history.get('lastSeenDate')
    missing_days = column_history.get('consecutiveMissingDays')
    if isinstance(last_seen, str) and isinstance(missing_days, int) and missing_days >= 3:
        return 'no_public_sample', f'最近已连续缺样本 {missing_days} 天，上次可见于 {last_seen}。'
    return 'no_public_sample', '当前来源下未看到符合口径的公开报价。'


def build_gap_summary_lines(analysis: dict[str, Any]) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for gap in analysis.get('gaps', []):
        if not isinstance(gap, dict):
            continue
        category = str(gap.get('category', '未知类别'))
        grouped.setdefault(category, []).append(gap)
    lines: list[str] = []
    for category in all_categories():
        items = grouped.get(category, [])
        if not items:
            continue
        details = []
        for item in items[:4]:
            spec = item.get('spec', '未知规格')
            reason = item.get('reasonCode', 'unknown')
            details.append(f'{spec}({reason})')
        lines.append(f'{category} 仍缺关键容量位：' + '、'.join(details) + '。')
    return lines


def build_market_summary_lines(quotes: list[Quote], run_notes: list[str], analysis: dict[str, Any]) -> list[str]:
    lines = []
    visible = [q for q in quotes if in_scope(q)]
    d6400 = sum(1 for q in visible if q.category == 'DDR5-6400')
    d5600 = sum(1 for q in visible if q.category == 'DDR5-5600')
    ssd = len(visible) - d6400 - d5600
    lines.append(f'DDR5-6400 抓到 {d6400} 条样本，DDR5-5600 抓到 {d5600} 条样本，企业级 SSD 抓到 {ssd} 条样本。')
    coverage_parts = []
    for category in all_categories():
        coverage = analysis.get('coverage', {}).get(category, {})
        if isinstance(coverage, dict):
            coverage_parts.append(f'{category} 覆盖 {coverage.get("filled", 0)}/{coverage.get("total", 0)}')
    if coverage_parts:
        lines.append('；'.join(coverage_parts))
    new_sources = analysis.get('newSourcesWithUsefulData', [])
    if new_sources:
        lines.append('今日新增有效来源：' + ' / '.join(str(item) for item in new_sources) + '。')
    else:
        lines.append('今日没有出现新的有效公开来源，当前结论仍受来源集中度限制。')
    lines.extend(str(item) for item in analysis.get('keyChangesVsYesterday', []))
    gap_lines = build_gap_summary_lines(analysis)
    lines.extend(gap_lines[:3])
    fail_notes = [n for n in run_notes if 'FAIL' in n]
    if fail_notes:
        lines.append('抓取异常：' + '；'.join(fail_notes))
    return lines


def render_trend_section(analysis: dict[str, Any]) -> str:
    lines = ['| 类别 | 当前趋势 | 覆盖率 |', '|---|---|---:|']
    for category in all_categories():
        trend = analysis.get('trendJudgement', {}).get(category, 'unknown')
        coverage = analysis.get('coverage', {}).get(category, {})
        if isinstance(coverage, dict):
            cov_text = f'{coverage.get("filled", 0)}/{coverage.get("total", 0)}'
        else:
            cov_text = '0/0'
        lines.append(f'| {category} | {trend} | {cov_text} |')
    return '\n'.join(lines)


def render_procurement_section(analysis: dict[str, Any]) -> str:
    lines = []
    for category in all_categories():
        view = analysis.get('procurementView', {}).get(category, {})
        if not isinstance(view, dict):
            continue
        recommendation = view.get('recommendation', 'insufficient_evidence')
        reason = view.get('reason', '暂无说明')
        lines.append(f'- {category}: `{recommendation}` — {reason}')
    return '\n'.join(lines) + ('\n' if lines else '')


def render_gap_section(analysis: dict[str, Any]) -> str:
    gaps = analysis.get('gaps', [])
    if not gaps:
        return '- 当前没有需要额外解释的缺口。\n'
    lines = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        suggested = gap.get('suggestedSources', [])
        source_text = ''
        if isinstance(suggested, list) and suggested:
            source_text = '；建议优先补源：' + ' / '.join(str(item) for item in suggested)
        lines.append(
            f'- {gap.get("category", "未知类别")} / {gap.get("spec", "未知规格")}: '
            f'{gap.get("reasonCode", "unknown")} — {gap.get("note", "")}{source_text}'
        )
    return '\n'.join(lines) + '\n'


def render_validation_section(validation: dict[str, Any]) -> str:
    status = 'passed' if validation.get('passed') else 'failed'
    lines = [f'- validation: {status}']
    checks = validation.get('checks', {})
    if isinstance(checks, dict):
        for key, value in checks.items():
            lines.append(f'- {key}: {value}')
    warnings = validation.get('warnings', [])
    if isinstance(warnings, list):
        for warning in warnings:
            lines.append(f'- warning: {warning}')
    return '\n'.join(lines) + '\n'


def suggested_sources(registry: dict[str, Any], category: str, limit: int = 3) -> list[str]:
    categories = registry.get('categories', {})
    category_data = categories.get(category, {}) if isinstance(categories, dict) else {}
    if not isinstance(category_data, dict):
        return []
    backups = category_data.get('backupSources', [])
    if not isinstance(backups, list):
        return []
    return [str(item) for item in backups[:limit]]


def build_daily_analysis(root: Path, date_str: str, quotes: list[Quote], run_notes: list[str]) -> dict[str, Any]:
    history_summary = load_history_summary(root)
    registry = load_sources_registry(root)
    attempted_sources = parse_attempted_sources(run_notes)
    seen_sources = recent_known_sources(root, exclude_dates={date_str})

    coverage = {category: coverage_for_category(quotes, category) for category in [*MEMORY_TARGETS, *SSD_TARGETS]}
    current_values = {category: median_map(quotes, category) for category in [*MEMORY_TARGETS, *SSD_TARGETS]}
    useful_sources_by_category = {category: useful_sources(quotes, category) for category in [*MEMORY_TARGETS, *SSD_TARGETS]}
    new_sources_tried = [source for source in attempted_sources if source not in seen_sources]
    new_sources_with_useful_data = sorted({source for category_sources in useful_sources_by_category.values() for source in category_sources if source not in seen_sources})

    key_changes: list[str] = []
    trend_judgement: dict[str, str] = {}
    procurement_view: dict[str, dict[str, str]] = {}
    gaps: list[dict[str, Any]] = []

    for category in [*MEMORY_TARGETS, *SSD_TARGETS]:
        trend_judgement[category] = classify_trend(category, current_values[category], history_summary)
        procurement_view[category] = classify_procurement(category, current_values[category], history_summary, useful_sources_by_category[category])
        previous_values = current_history_map(category, history_category(history_summary, category).get('previousValues', {}))
        for spec, current_value in current_values[category].items():
            previous_value = previous_values.get(spec)
            if current_value is not None and isinstance(previous_value, int) and current_value != previous_value:
                direction = '上涨' if current_value > previous_value else '下跌'
                key_changes.append(f'{category} {spec} 相对昨日{direction}至 ¥{current_value}（昨日 ¥{previous_value}）。')
            if current_value is None:
                reason_code, note = classify_gap_reason(category, spec, quotes, history_summary)
                gaps.append({
                    'category': category,
                    'spec': spec,
                    'reasonCode': reason_code,
                    'note': note,
                    'suggestedSources': suggested_sources(registry, category),
                })

    if not key_changes:
        key_changes.append('关键代表列相对昨日未见显著价格变化，当前更大的问题仍是覆盖率与来源集中度。')

    tracking_values = {}
    for category, spec in TRACKING_KEYS:
        tracking_values[f'{category} {spec}'] = current_values.get(category, {}).get(spec)

    return {
        'date': date_str,
        'generatedAt': dt.datetime.now().isoformat(),
        'coverage': coverage,
        'attemptedSources': attempted_sources,
        'newSourcesTried': new_sources_tried,
        'newSourcesWithUsefulData': new_sources_with_useful_data,
        'sourceAttemptSummary': {
            category: {
                'usefulSources': useful_sources_by_category[category],
                'suggestedSources': suggested_sources(registry, category),
            }
            for category in [*MEMORY_TARGETS, *SSD_TARGETS]
        },
        'keyChangesVsYesterday': key_changes,
        'trendJudgement': trend_judgement,
        'procurementView': procurement_view,
        'gaps': gaps,
        'trackingValues': tracking_values,
    }


def build_validation_summary(root: Path, analysis: dict[str, Any], quotes: list[Quote]) -> dict[str, Any]:
    registry = load_sources_registry(root)
    categories = [*MEMORY_TARGETS, *SSD_TARGETS]
    checks = {
        'hasCoverage': all(category in analysis.get('coverage', {}) for category in categories),
        'hasTrendJudgement': all(category in analysis.get('trendJudgement', {}) for category in categories),
        'hasProcurementView': all(category in analysis.get('procurementView', {}) for category in categories),
        'hasAttemptedSources': bool(analysis.get('attemptedSources')),
        'gapReasonCodesValid': all(gap.get('reasonCode') in VALID_GAP_REASON_CODES for gap in analysis.get('gaps', [])),
        'recommendationsValid': all(
            isinstance(view, dict) and view.get('recommendation') in VALID_RECOMMENDATIONS
            for view in analysis.get('procurementView', {}).values()
        ),
    }
    warnings: list[str] = []
    for category, coverage in analysis.get('coverage', {}).items():
        if isinstance(coverage, dict) and coverage.get('filled') == 0:
            warnings.append(f'{category} 当前覆盖率为 0，结论仅可视为缺口报告。')
    unrecognized_sources = []
    registry_categories = registry.get('categories', {}) if isinstance(registry.get('categories', {}), dict) else {}
    for quote in quotes:
        category_data = registry_categories.get(quote.category, {}) if isinstance(registry_categories, dict) else {}
        known = set()
        if isinstance(category_data, dict):
            for key in ('primarySources', 'backupSources', 'validationSources'):
                value = category_data.get(key, [])
                if isinstance(value, list):
                    known.update(str(item) for item in value)
        if known and quote.source not in known:
            unrecognized_sources.append(f'{quote.category}:{quote.source}')
    if unrecognized_sources:
        warnings.append('存在未在 sources-registry.json 注册的来源：' + '，'.join(sorted(set(unrecognized_sources))))
    passed = all(checks.values())
    return {
        'generatedAt': dt.datetime.now().isoformat(),
        'passed': passed,
        'checks': checks,
        'warnings': warnings,
    }


def write_daily_analysis(root: Path, date_str: str, analysis: dict[str, Any]) -> Path:
    analysis_dir = root / 'analysis'
    analysis_dir.mkdir(parents=True, exist_ok=True)
    path = analysis_dir / f'daily-analysis-{date_str}.json'
    path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def write_validation_summary(root: Path, date_str: str, validation: dict[str, Any]) -> Path:
    analysis_dir = root / 'analysis'
    analysis_dir.mkdir(parents=True, exist_ok=True)
    path = analysis_dir / f'daily-analysis-{date_str}.validation.json'
    path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def collect_quotes() -> tuple[list[Quote], list[str]]:
    quotes: list[Quote] = []
    notes: list[str] = []
    jobs: list[tuple[str, callable]] = [
        ('corewave-6400', lambda: parse_corewave_ddr('https://corewavelabs.com/ddr5-6400-ecc-rdimm-server-ram-price/', '6400')),
        ('corewave-5600', lambda: parse_corewave_ddr('https://corewavelabs.com/ddr5-5600-ecc-rdimm-server-ram-price/', '5600')),
        ('provantage-ddr5-rdimm', lambda: parse_provantage_results(PROVANTAGE_QUERY_URLS['provantage-ddr5-rdimm'])),
        ('provantage-pcie5', lambda: parse_provantage_results(PROVANTAGE_QUERY_URLS['provantage-pcie5'])),
        ('provantage-qlc', lambda: parse_provantage_results(PROVANTAGE_QUERY_URLS['provantage-qlc'])),
    ]
    for spec, url in DISCTECH_CAPACITY_URLS.items():
        jobs.append((f'disctech-{spec}', lambda spec=spec, url=url: parse_disctech_jsonld(url, spec)))

    for name, func in jobs:
        try:
            batch = func()
            quotes.extend(batch)
            categories = ', '.join(sorted({q.category for q in batch})) if batch else 'none'
            notes.append(f'{name}: OK ({len(batch)} quotes; categories={categories})')
        except Exception as e:  # noqa: BLE001
            notes.append(f'{name}: FAIL ({e})')
    return dedupe_quotes(quotes), notes


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
            brands = ' / '.join(sorted({q.brand for q in items})[:4])
            srcs = '；'.join(sorted({q.source for q in items}))
            rows.append(f'| {spec} | {m} | {len(items)} | {srcs}；品牌样本：{brands} |')
        else:
            rows.append(f'| {spec} | NA | 0 | 样本不足 |')
    return '\n'.join(rows)


def render_source_details(quotes: list[Quote]) -> str:
    visible = [q for q in quotes if in_scope(q)]
    if not visible:
        return '- 无有效抓取样本\n'
    lines = []
    for q in sorted(visible, key=lambda x: (x.category, x.spec, x.price_cny_tax, x.brand)):
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


def write_raw(root: Path, date_str: str, quotes: list[Quote], run_notes: list[str]) -> Path:
    out_dir = root / 'raw' / date_str
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


def render_report(root: Path, date_str: str, quotes: list[Quote], run_notes: list[str], raw_path: Path, analysis_path: Path, validation_path: Path, analysis: dict[str, Any], validation: dict[str, Any]) -> str:
    timestamp = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + f' {TZ_LABEL}'
    lines = [
        f'# 硬件市场行情日报（{date_str}）',
        '',
        f'> 执行时间：{timestamp}',
        f'> 汇率口径：1 USD = {USD_TO_CNY:.2f} CNY；税率口径：{int(VAT_RATE * 100)}% 增值税。',
        '> 数据源优先级：CoreWaveLabs > 其他企业级现货/B2B 报价页 > 官方规格页辅助。',
        '> 内存渠道校验：相对主流成交价锚点偏离超过 40% 的样本不纳入主统计；偏离 25%~40% 的样本降权观察。',
        '> SSD 渠道校验：DiscTech 仅纳入 JSON-LD 中可结构化解析、且明确标注为 Gen4/Gen5 U.2 NVMe 的企业级条目；默认剔除 Gen3 与 Mixed-Use 盘。',
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
    for s in build_market_summary_lines(quotes, run_notes, analysis):
        lines.append(f'- {s}')
    lines.extend([
        '',
        '## 7) 趋势判断',
        render_trend_section(analysis),
        '',
        '## 8) 采购建议',
        render_procurement_section(analysis),
        '## 9) 缺口与缺失归因',
        render_gap_section(analysis),
        '## 10) 主要来源明细',
        render_source_details(quotes),
        '## 11) 自动化执行记录',
        f'- 原始结构化数据：`{raw_path.relative_to(root)}`',
        f'- 每日分析快照：`{analysis_path.relative_to(root)}`',
        f'- 验证摘要：`{validation_path.relative_to(root)}`',
    ])
    lines.append(render_validation_section(validation).rstrip())
    for note in run_notes:
        lines.append(f'- {note}')
    return '\n'.join(lines).rstrip() + '\n'


def ensure_tracking_table(path: Path) -> None:
    if path.exists():
        return
    path.write_text(
        '# Tracking Table\n\n'
        '> 固定口径长期追踪表。每日新增一行；金额默认使用人民币含税整数；无有效样本填 `NA`。\n\n'
        '| Date | DDR5-6400 32GB | DDR5-6400 64GB | DDR5-6400 128GB | DDR5-5600 32GB | DDR5-5600 64GB | DDR5-5600 128GB | PCIe4 TLC 3.84TB | PCIe4 TLC 7.68TB | PCIe4 TLC 15.36TB | PCIe4 TLC 30.72TB | PCIe5 TLC 3.84TB | PCIe5 TLC 7.68TB | PCIe5 TLC 15.36TB | PCIe5 TLC 30.72TB | PCIe4 QLC 15.36TB | PCIe4 QLC 30.72TB | PCIe4 QLC 61.44TB | PCIe4 QLC 122.88TB | Notes |\n'
        '|------|----------------|----------------|-----------------|----------------|----------------|-----------------|------------------|------------------|-------------------|-------------------|------------------|------------------|-------------------|-------------------|-------------------|-------------------|-------------------|--------------------|-------|\n'
    )


def update_tracking_table(path: Path, date_str: str, analysis: dict[str, Any], run_notes: list[str]) -> None:
    ensure_tracking_table(path)
    content = path.read_text()
    if f'| {date_str} |' in content:
        return
    values = []
    for category, spec in TRACKING_KEYS:
        m = analysis.get('trackingValues', {}).get(f'{category} {spec}')
        values.append(str(m) if m is not None else 'NA')
    coverage = []
    for category in all_categories():
        cov = analysis.get('coverage', {}).get(category, {})
        if isinstance(cov, dict):
            coverage.append(f'{category}:{cov.get("filled", 0)}/{cov.get("total", 0)}')
    trend = analysis.get('trendJudgement', {})
    note = '自动抓取；结构化分析；' + '，'.join(coverage)
    if isinstance(trend, dict):
        note += '；趋势=' + ','.join(f'{key}:{value}' for key, value in trend.items())
    if any('FAIL' in n for n in run_notes):
        note += '；部分源失败'
    line = '| ' + ' | '.join([date_str, *values, note]) + ' |\n'
    path.write_text(content.rstrip() + '\n' + line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=dt.date.today().isoformat())
    parser.add_argument('--repo', default=str(DEFAULT_ROOT))
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    report_path = root / f'daily-{args.date}.md'
    tracking_path = root / 'tracking-table.md'
    if report_path.exists():
        print(f'ERROR: report already exists: {report_path}', file=sys.stderr)
        return 2

    quotes, run_notes = collect_quotes()
    raw_path = write_raw(root, args.date, quotes, run_notes)
    analysis = build_daily_analysis(root, args.date, quotes, run_notes)
    validation = build_validation_summary(root, analysis, quotes)
    analysis_path = write_daily_analysis(root, args.date, analysis)
    validation_path = write_validation_summary(root, args.date, validation)
    if not validation.get('passed'):
        print(f'ERROR: validation failed: {validation_path}', file=sys.stderr)
        return 3
    report_path.write_text(render_report(root, args.date, quotes, run_notes, raw_path, analysis_path, validation_path, analysis, validation), encoding='utf-8')
    update_tracking_table(tracking_path, args.date, analysis, run_notes)
    print(f'created {report_path}')
    print(f'updated {tracking_path}')
    print(f'raw {raw_path}')
    print(f'analysis {analysis_path}')
    print(f'validation {validation_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
