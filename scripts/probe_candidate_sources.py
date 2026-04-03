#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess

UA = 'Mozilla/5.0 (OpenClaw source probe)'

URLS = {
    'provantage_ddr5': 'https://www.provantage.com/service/searchsvcs?QUERY=DDR5+RDIMM+ECC+64GB',
    'provantage_pcie5': 'https://www.provantage.com/service/searchsvcs?QUERY=PM1743+U.2',
    'provantage_qlc': 'https://www.provantage.com/service/searchsvcs?QUERY=Solidigm+D5-P5336',
    'exxact_ddr5': 'https://www.exxactcorp.com/search?search=DDR5+RDIMM+64GB',
    'wiredzone_pm1743': 'https://www.wiredzone.com/search?type=product&q=PM1743',
    'saitech_ddr5': 'https://www.saitechinc.com/search.php?search_query=DDR5+RDIMM',
    'solidigm_p5336': 'https://www.solidigm.com/products/data-center/d5/p5336.html',
    'micron_9550': 'https://www.micron.com/products/storage/ssd/data-center-ssd/9550-nvme-ssd',
    'samsung_pm1743': 'https://semiconductor.samsung.com/ssd/enterprise-ssd/pm1743/',
    'kioxia_cm7': 'https://americas.kioxia.com/en-us/business/ssd/enterprise-ssd/cm7-series.html',
}


def fetch(url: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ['curl', '-L', '--silent', '--show-error', '--max-time', '25', '-A', UA, url],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, proc.stdout if proc.returncode == 0 else proc.stderr


def summarize(html: str) -> dict[str, object]:
    title_match = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    title = re.sub(r'\s+', ' ', title_match.group(1)).strip() if title_match else ''
    lowered = html.lower()
    blocked = any(marker in lowered for marker in [
        'cloudflare',
        'just a moment',
        'enable javascript and cookies to continue',
        'attention required',
        'sorry, you have been blocked',
    ])
    has_jsonld = 'application/ld+json' in lowered
    has_price = any(token in lowered for token in ['price', '$', 'usd'])
    snippets = []
    for pattern in [r'.{0,80}price.{0,120}', r'.{0,80}rdimm.{0,120}', r'.{0,80}pm1743.{0,120}', r'.{0,80}9550.{0,120}', r'.{0,80}p5336.{0,120}']:
        for match in re.finditer(pattern, html, re.I | re.S):
            snippet = re.sub(r'\s+', ' ', match.group(0)).strip()
            if snippet not in snippets:
                snippets.append(snippet[:220])
            if len(snippets) >= 5:
                break
        if len(snippets) >= 5:
            break
    return {
        'title': title,
        'blocked': blocked,
        'has_jsonld': has_jsonld,
        'has_price_tokens': has_price,
        'snippets': snippets,
    }


def main() -> int:
    results = {}
    for name, url in URLS.items():
        ok, output = fetch(url)
        if not ok:
            results[name] = {'url': url, 'ok': False, 'error': output[:400]}
            continue
        results[name] = {'url': url, 'ok': True, **summarize(output)}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
