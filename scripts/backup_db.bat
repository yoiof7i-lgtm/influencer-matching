@echo off
REM PostgreSQL 백업 (Windows Docker Desktop)
REM 사용법: scripts\backup_db.bat
cd /d "%~dp0.."

if not exist backups mkdir backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set STAMP=%%i
set FILE=backups\db_%STAMP%.sql

echo ^>^>^> PostgreSQL 덤프 시작: %FILE%
docker compose exec -T db pg_dump -U influencer influencer_db > %FILE%
if %errorlevel% neq 0 (
  echo ^>^>^> 실패! Docker가 실행 중인지 확인하세요.
  pause
  exit /b 1
)
echo ^>^>^> 완료: %FILE%
pause
