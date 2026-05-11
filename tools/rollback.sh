#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/root/.openclaw/workspace/tmp/streamlit-finance"
BACKUP_ROOT="/root/.openclaw/workspace/backups/streamlit-finance"
TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
  echo "用法: $0 <backup目录名或绝对路径>" >&2
  echo "可用备份:" >&2
  ls -1 "$BACKUP_ROOT" 2>/dev/null || true
  exit 1
fi

if [[ -d "$TARGET" ]]; then
  SRC="$TARGET"
elif [[ -d "$BACKUP_ROOT/$TARGET" ]]; then
  SRC="$BACKUP_ROOT/$TARGET"
else
  echo "未找到备份: $TARGET" >&2
  exit 2
fi

TMP="${APP_DIR}.rollback.$(date +%Y%m%d-%H%M%S)"
mkdir -p "$TMP"
rsync -a --delete --exclude '.venv' --exclude '__pycache__' "$SRC/" "$TMP/"
rsync -a --delete --exclude '.venv' --exclude '__pycache__' "$TMP/" "$APP_DIR/"
rm -rf "$TMP"
echo "已回退到: $SRC"
