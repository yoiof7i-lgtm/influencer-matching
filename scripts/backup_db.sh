#!/usr/bin/env bash
# PostgreSQL 백업 스크립트 — docker compose 기반
# 사용법: bash scripts/backup_db.sh
set -e
cd "$(dirname "$0")/.."

BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/db_${STAMP}.sql"

echo ">>> PostgreSQL 덤프 시작: $FILE"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-influencer}" "${POSTGRES_DB:-influencer_db}" > "$FILE"
echo ">>> 완료: $FILE ($(du -h "$FILE" | cut -f1))"
# 30일 지난 백업 자동 삭제
find "$BACKUP_DIR" -name "db_*.sql" -mtime +30 -delete
