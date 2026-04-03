#!/usr/bin/env python3
from pathlib import Path


path = Path.home() / '.openclaw' / 'workspace' / 'hardware-market-trends' / 'scripts' / 'daily-hardware-market-check.sh'
text = path.read_text(encoding='utf-8')
lines = text.splitlines()

injected_block = [
    '# 先准备历史趋势上下文，供研究任务或生成器参考',
    'if [ -x "$REPO/scripts/prepare-market-context.sh" ]; then',
    '  "$REPO/scripts/prepare-market-context.sh"',
    '  echo',
    'fi',
]

if injected_block[0] in text:
    print('already patched')
else:
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line == 'cd "$REPO"':
            out.append('')
            out.extend(injected_block)
            inserted = True
    if not inserted:
        raise SystemExit('insertion point not found')
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(path)
