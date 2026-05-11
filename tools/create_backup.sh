#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/root/.openclaw/workspace/tmp/streamlit-finance"
BACKUP_ROOT="/root/.openclaw/workspace/backups/streamlit-finance"
TS="$(date +%Y%m%d-%H%M%S)"
DST="$BACKUP_ROOT/backup-$TS"
mkdir -p "$BACKUP_ROOT"
rsync -a --exclude '.venv' --exclude '__pycache__' "$APP_DIR/" "$DST/"
echo "$DST"
