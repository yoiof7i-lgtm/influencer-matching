@echo off
REM PostgreSQL 복원 (Windows Docker Desktop)
REM 사용법: scripts\restore_db.bat backups\db_YYYYMMDD_HHMMSS.sql
cd /d "%~dp0.."

if "%~1"=="" (
  echo 사용법: scripts\restore_db.bat ^<덤프파일.sql^>
  pause
  exit /b 1
)
if not exist "%~1" (
  echo 파일 없음: %~1
  pause
  exit /b 1
)

echo ^>^>^> 주의: 현재 DB 내용이 덤프로 대체됩니다.
pause
docker compose exec -T db psql -U influencer -d influencer_db < "%~1"
if %errorlevel% neq 0 (
  echo ^>^>^> 복원 실패!
  pause
  exit /b 1
)
echo ^>^>^> 복원 완료: %~1
pause
