# Hostinger VPS 이전 가이드

## 사전 준비 (VPS 측)
```bash
# 1. Docker 설치 (Ubuntu)
curl -fsSL https://get.docker.com | sh
# 2. Git 설치 및 프로젝트 클론
sudo apt install -y git
git clone <저장소 URL> influencer-matching
cd influencer-matching
# 3. 환경변수 생성 (로컬 .env 내용 복사, 비밀번호는 새로 발급 권장)
cp .env.example .env && nano .env
```

## 이전 절차
### 1) 로컬에서 DB 덤프 (기존 데이터가 있는 경우)
```bash
bash scripts/backup_db.sh
# → backups/db_YYYYMMDD_HHMMSS.sql 생성
```
Windows 로컬이면: `scripts\backup_db.bat`

### 2) 덤프 파일을 VPS로 전송
```bash
scp backups/db_*.sql root@<VPS IP>:~/influencer-matching/
```

### 3) VPS에서 서비스 기동
```bash
docker compose up -d --build
```

### 4) 덤프 복원
```bash
bash scripts/restore_db.sh db_YYYYMMDD_HHMMSS.sql
```

## DB 덤프/복원 원리
- 덤프: `pg_dump` — 컨테이너 내 postgres 사용자로 전체 DB를 SQL 텍스트로 출력
- 복원: `psql` — SQL 파일을 그대로 실행 (테이블+데이터 재생성)
- 볼륨(pgdata)은 컨테이너 삭제와 무관하게 유지되므로,
  이전 시에는 "새 VPS에서 빈 DB 기동 → 덤프 복원"이 가장 안전

## 주의사항
1. **POSTGRES 포트 외부 노출 금지**: VPS의 docker-compose.yml에서 db의 `ports: 5432` 항목 제거
   (현재 로컬용 설정은 편의상 열려 있음)
2. **방화벽**: ufw로 22/80/443만 허용
3. **HTTPS**: 도메인 연결 후 Caddy(자동 인증서) 권장
4. **백업 주기**: crontab에 backup_db.sh 매일 새벽 등록 권장
   ```
   0 4 * * * cd ~/influencer-matching && bash scripts/backup_db.sh
   ```
5. **.env 관리**: VPS의 .env는 절대 저장소에 커밋 금지, 서버에서만 관리
6. **롤백**: 문제 발생 시 `docker compose down -v` 후 덤프 재복원
