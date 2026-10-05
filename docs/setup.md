# 실행 가이드 (로컬 Docker)

## 1. 사전 준비
- Docker Desktop (Windows) 또는 docker engine 설치
- 저장소 클론 후 프로젝트 루트로 이동

## 2. 환경변수 설정
```bash
cp .env.example .env
```
`.env`를 열어 값 수정:
```
POSTGRES_USER=influencer
POSTGRES_PASSWORD=<강한 비밀번호로 변경>
POSTGRES_DB=influencer_db
DATABASE_URL=postgresql://influencer:<같은 비밀번호>@db:5432/influencer_db
```
⚠ `.env`는 git에 커밋되지 않습니다 (.gitignore 적용 확인 완료)

## 3. 실행
```bash
docker compose up -d --build
```
- API: http://localhost:8000
- Swagger 문서: http://localhost:8000/docs
- Health: http://localhost:8000/health

## 4. 종료 / 재시작
```bash
docker compose down          # 컨테이너만 종료 (데이터 유지)
docker compose down -v       # 데이터까지 삭제 (초기화)
docker compose up -d --build # 코드 수정 후 재빌드
```

## 주요 API 엔드포인트

### 인증 (prefix: /auth)
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | /auth/register | 회원가입 (인플은 인스타 활성화 필수) |
| POST | /auth/login | 로그인 (토큰 반환) |

### 사용자/매칭 (prefix: /users)
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | /users/nearby/{owner_id} | 근처 협찬ON 인플 6명 (점수순) |
| POST | /users/invite?owner_id=&influencer_id= | 사장님 초대 (최대 2명) |
| POST | /users/accept/{match_id} | 인플 수락 (나머지 소멸 + OFF 전환) |

### 평가 (prefix: /reviews)
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | /reviews/ | 평가 생성 (±0.2/±0.1/0) |
| POST | /reviews/visit-done/{match_id} | 방문 완료 처리 |

### 기타
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | / | 서비스 상태 |
| GET | /health | 헬스체크 |

## TODO (다음 단계)
- 비밀번호 bcrypt 해시 / JWT 실제 발급
- 거리순 정렬 (Haversine)
- 후기 3개 미제출 → OFF 자동 배치
- 2주 일괄 평가 반영 배치

## ⚠️ 프론트 수정 시 필수 점검 (김비서 실수 방지)

index.html의 `<script>`는 단일 블록. 함수를 수정/삭제할 때 아래 확인 필수:

1. HTML `onclick`에서 호출하는 모든 함수가 JS에 `function`으로 정의돼 있는지:
   - 현재 목록: show, setRole, doRegister, doLogin, logout, toggleActive, paintToggle,
     loadNearby, invite, loadMyInvites, loadInvites, acceptInvite, doVerify,
     loadPending, approve, reject, resetPw, showPhoto, closePhoto, submitInvite,
     closeInviteModal, goLoginAfterVerify, v, err
2. 문법 검사: 스크립트 블록 추출 → `node --check`
3. 과거 실수: 이전 수정 중 v/err/paintToggle/toggleActive 유실 → 버튼 전면 먹통 (2026-10-05)
