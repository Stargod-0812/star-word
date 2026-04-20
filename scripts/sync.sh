#!/usr/bin/env bash
# 把仓库根的 source-of-truth 文件同步到 packages/python/ 下的分发副本.
# 在修改 RULES.md / README.md / adapters/*.md 后执行一次.
#
# 用法: scripts/sync.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

DEST_DATA="packages/python/star_word/data"
DEST_PKG_README="packages/python/README.md"

# 1. RULES.md → data/
cp RULES.md "$DEST_DATA/RULES.md"

# 2. adapters/*.md → data/adapters/
mkdir -p "$DEST_DATA/adapters"
cp adapters/claude-code.md adapters/AGENTS.md adapters/codex.md "$DEST_DATA/adapters/"

# 3. README.md → packages/python/README.md（pip long_description 来源）
cp README.md "$DEST_PKG_README"

# 4. 验证一致
for f in RULES.md adapters/claude-code.md adapters/AGENTS.md adapters/codex.md; do
  src="$f"
  dst="$DEST_DATA/$(basename "$f")"
  if [ "$f" != "RULES.md" ]; then
    dst="$DEST_DATA/$f"
  fi
  if ! diff -q "$src" "$dst" >/dev/null 2>&1; then
    echo "✗ 同步失败: $src ≠ $dst" >&2
    exit 1
  fi
done

if ! diff -q README.md "$DEST_PKG_README" >/dev/null 2>&1; then
  echo "✗ 同步失败: README.md ≠ $DEST_PKG_README" >&2
  exit 1
fi

echo "✓ 同步完成: RULES.md / adapters/ / README.md → packages/python/"
