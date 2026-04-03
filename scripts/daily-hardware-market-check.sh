#!/bin/bash
set -euo pipefail

# 脚本所在目录的上级目录即为仓库根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
DATE="${1:-$(date +%F)}"
REPORT_FILE="$REPO/daily-$DATE.md"
MAX_RETRIES=3

cd "$REPO"

# 先准备历史趋势上下文，供研究任务或生成器参考
if [ -x "$REPO/scripts/prepare-market-context.sh" ]; then
  "$REPO/scripts/prepare-market-context.sh"
  echo
fi

# 如果日报已存在，跳过生成，只处理 git
if [ -f "$REPORT_FILE" ]; then
  echo "Report already exists: $REPORT_FILE"
  echo "Skipping report generation, checking git status..."
else
  # 生成日报
  python3 bin/generate_hardware_report.py --date "$DATE"
  echo
  printf 'Done: %s\n' "$REPORT_FILE"
  printf 'Tracking: %s\n' "$REPO/tracking-table.md"
fi

# 自动提交并推送到远端（带重试）
push_to_remote() {
  if [ -n "$(git status --porcelain)" ]; then
    git add .
    git commit -m "Update hardware market report for $DATE"
    git push origin main
    echo "Pushed to origin/main"
  else
    echo "No changes to commit"
    return 0
  fi
}

retry_count=0
while [ $retry_count -lt $MAX_RETRIES ]; do
  if push_to_remote; then
    break
  else
    retry_count=$((retry_count + 1))
    if [ $retry_count -lt $MAX_RETRIES ]; then
      echo "Push failed, retrying ($retry_count/$MAX_RETRIES)..."
      sleep 5
    else
      echo "Push failed after $MAX_RETRIES attempts"
      exit 1
    fi
  fi
done
