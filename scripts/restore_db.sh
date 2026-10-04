#!/usr/bin/env bash
# PostgreSQL 복원 스크립트
# 사용법: bash scripts/restore_db.sh backups/db_YYYYMMDD_HHMMSS.sql
set -e
cd "$(dirname "$0")/.."

if [ -z "$1" ]; then
  echo "사용법: bash scripts/restore_db.sh <덤프파일.sql>"
  exit 1
fi
if [ ! -f "$1" ]; then
  echo "파일 없음: $1"
  exit 1
fi

echo ">>> 주의: 현재 DB 내용이 덤프로 대체됩니다 (5초 후 진행)"
sleep 5
docker compose exec -T db psql -U "${POSTGRES_USER:-influencer}" -d "${POSTGRES_DB:-influencer_db}" < "$1"
echo ">>> 복원 완료: $1"
