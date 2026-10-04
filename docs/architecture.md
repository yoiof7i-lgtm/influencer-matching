# 아키텍처

## 전체 시스템 구조

```
[사용자 브라우저]
      │ HTTP
      ▼
[frontend/index.html]  ← Tailwind (CDN) 정적 페이지
      │ fetch API
      ▼
[backend: FastAPI] :8000
      │ SQLAlchemy ORM
      ▼
[db: PostgreSQL 16] :5432
      ▲
docker-compose로 두 컨테이너 묶음 (내부 네트워크)
```

## 기술 스택

| 계층 | 기술 | 비고 |
|---|---|---|
| Backend | FastAPI 0.115 | Python 3.11-slim, uvicorn |
| ORM | SQLAlchemy 2.0 | psycopg2-binary |
| DB | PostgreSQL 16-alpine | pgdata 볼륨 영속화 |
| Frontend | HTML + Tailwind CSS | CDN 방식, 정적 파일 |
| Infra | Docker + Docker Compose | Hostinger VPS 배포 대비 |

## 주요 테이블

### users
| 컬럼 | 설명 |
|---|---|
| role | "influencer" / "owner" 2종 |
| instagram_handle / instagram_active | 인플 가입 시 인스타 활성화 확인 |
| shop_name | 사장님만 |
| region / lat / lng | 위치기반 |
| influencer_score | 10점 만점, 초기 5.0 |
| owner_score | 100점 만점, 초기 50.0 |
| is_active | 협찬ON/OFF 토글 (OFF=어두움, ON=밝음) |
| review_pending | 후기 링크 미제출 수 (3개 → OFF) |

### matches
| 컬럼 | 설명 |
|---|---|
| owner_id / influencer_id | 초대 관계 (수락 전 influencer_id 유지) |
| status | pending → accepted / expired / canceled |
| visit_date | 방문 예정일 (2~3시간 텀, 지역당 최대 2곳) |

규칙: 사장님 초대 최대 2명 / 인플 수락 1곳(수락 시 나머지 소멸 + OFF 전환) / 3주 재방문 금지

### reviews
| 컬럼 | 설명 |
|---|---|
| match_id | 매칭 참조 |
| reviewer_id / reviewee_id | 상호 평가 |
| score_delta | ±0.2 / ±0.1 / 0 중 하나 |
| photo_link | 인플 후기 링크 (미제출 3개 → OFF) |
| applied | 2주 모아 일괄·익명 반영 완료 여부 |

## Hostinger VPS 이전 고려사항

1. **도메인 + HTTPS**: Caddy 또는 Nginx + Let's Encrypt (docker-compose에 reverse-proxy 서비스 추가)
2. **비밀정보**: `.env` 파일만으로 관리 (git 제외) — DB 비밀번호를 강한 값으로 변경
3. **포트**: 80/443만 외부 노출, 5432(POSTGRES)는 외부 노출 금지 (compose에서 ports 제거)
4. **볼륨**: pgdata는 VPS 로컬 볼륨 + scripts/backup_db.sh로 주기 백업
5. **재시작**: `restart: unless-stopped` 이미 적용 — VPS 재부팅 시 자동 기동
6. **리소스**: 초기엔 1 vCPU / 2GB RAM이면 충분
7. **업데이트 절차**: git pull → docker compose up -d --build
