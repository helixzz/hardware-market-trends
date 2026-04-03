#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

UA = 'Mozilla/5.0 (OpenClaw source sample fetch)'
URLS = {
    'provantage_ddr5': 'https://www.provantage.com/service/searchsvcs?QUERY=DDR5+RDIMM+ECC+64GB',
    'provantage_pcie5': 'https://www.provantage.com/service/searchsvcs?QUERY=PM1743+U.2',
    'provantage_qlc': 'https://www.provantage.com/service/searchsvcs?QUERY=Solidigm+D5-P5336',
}


def main() -> int:
    root = Path.home() / '.openclaw' / 'workspace' / 'hardware-market-trends' / 'analysis' / 'provantage-samples'
    root.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        proc = subprocess.run(
            ['curl', '-L', '--silent', '--show-error', '--max-time', '25', '-A', UA, url],
            check=True,
            capture_output=True,
            text=True,
        )
        path = root / f'{name}.html'
        path.write_text(proc.stdout, encoding='utf-8')
        print(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
