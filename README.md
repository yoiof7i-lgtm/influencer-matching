# influencer-matching (협찬ON)

인플루언서와 맛집/카페 사장님을 중계하는 협찬 매칭 플랫폼.

## 기술 스택
- Backend: FastAPI (Python 3.11)
- DB: PostgreSQL 16
- Frontend: HTML + Tailwind CSS
- Infra: Docker + Docker Compose (Hostinger VPS 배포 대비)

## 폴더 구조
```
influencer-matching/
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI 앱 진입점
│   │   ├── models.py      # SQLAlchemy 모델 (User/Match/Review)
│   │   ├── schemas.py     # Pydantic 스키마
│   │   ├── database.py    # DB 연결
│   │   └── routers/       # auth / users / reviews
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/index.html    # 랜딩 페이지 (Tailwind)
├── docs/                  # 기획서
├── scripts/               # 운영 스크립트
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## 실행 방법
```bash
cp .env.example .env        # 비밀번호 수정 후
docker compose up -d --build
```
- API: http://localhost:8000 (Swagger: /docs)
- DB: localhost:5432

## 주요 도메인 규칙
- 회원 2종: 인플루언서 / 사장님
- 인플 가입 시 인스타 활성화 계정 확인
- 협찬ON/OFF 위치기반 토글 (OFF=어두움 / ON=밝음)
- 사장님: 근처 ON 인플 점수·거리순 6명 조회 → 초대 최대 2명
- 인플: 수락 1곳만 (수락 시 나머지 초대 소멸 + OFF 전환)
- 방문 후 상호 평가: ±0.2/±0.1/0, 2주 모아 일괄·익명 반영 (인플 10점, 업소 100점)
- 후기 링크 미제출 3개 → OFF / 2개 이하 → ON 복귀
- 같은 지역 2~3시간 텀, 최대 2곳 / 3주 재방문 금지
