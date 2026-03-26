#!/bin/bash
set -euo pipefail

# 脚本所在目录的上级目录即为仓库根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$REPO/daily-news"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SCRIPT="$SCRIPT_DIR/generate_market_news_digest.py"
DATE=$(date +%F)
NEWS_FILE="$OUTPUT_DIR/daily-news-digest-$DATE.md"
MAX_RETRIES=3

# 可选：通过 MARKET_NEWS_REWRITER_CMD 接入外部中文重写器。
# 约定：命令从 stdin 读取 JSON，向 stdout 输出等长 JSON 数组。
# 若失败，Python 侧会自动回退到本地规则压缩。
mkdir -p "$OUTPUT_DIR"

# 如果早报已存在，跳过生成，只处理 git
if [ -f "$NEWS_FILE" ]; then
  echo "News digest already exists: $NEWS_FILE"
  echo "Skipping digest generation, checking git status..."
else
  "$PYTHON_BIN" "$SCRIPT" "$OUTPUT_DIR"
fi

# 自动提交并推送到远端（带重试）
cd "$REPO"

push_to_remote() {
  if [ -n "$(git status --porcelain)" ]; then
    git add .
    git commit -m "Update market news digest for $DATE"
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
