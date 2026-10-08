"""평가 라우터 — 10항목 체크리스트 상호 평가 (v2)
점수 체계: 항목당 +0.2/+0.1/0/-0.1/-0.2, 10항목 합산 (-2.0~+2.0)
표시: 인플 10점 만점 / 업소 100점 만점 (시작점 5.0/50.0)
포스팅 조건: 충족+0.2 / 지연+0.1 / 미제출 0 / 위반-0.1
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
import json

router = APIRouter(prefix="/reviews", tags=["reviews"])

# 항목당 허용 점수 (5단계)
ALLOWED = (-0.2, -0.1, 0.0, 0.1, 0.2)
# 인플→사장 10항목 / 사장→인플 10항목 (docs/score-system.md)
ITEMS_INFL_TO_OWNER = ["맛", "친절", "인테리어", "청결", "접근성", "가성비",
                       "사진스팟", "협찬조건준수", "대기속도", "재방문의사"]
ITEMS_OWNER_TO_INFL = ["예약준수", "촬영태도", "사진퀄리티", "글정성", "조건이행",
                       "태그정확성", "팔로워반응", "소통태도", "노출성과", "재협찬의사"]
POSTING_BONUS = {"충족": 0.2, "지연": 0.1, "미제출": 0.0, "위반": -0.1}

START_INFL = 5.0   # 인플 시작점 (10점 만점)
START_OWNER = 50.0 # 업소 시작점 (100점 만점)


def _apply_to_user(db, user_id, is_influencer, total_delta, posting_bonus=0.0):
    """평가 총합을 대상 사용자 점수에 반영 (10점/100점 체계 유지)"""
    u = db.query(models.User).get(user_id)
    if not u:
        return
    if is_influencer:
        # 10점 만점: 총합(±2.0)을 그대로 더하되 0~10 클램프
        u.influencer_score = max(0.0, min(10.0, (u.influencer_score or START_INFL) + total_delta + posting_bonus))
    else:
        # 100점 만점: ±2.0 → ×10 하지 않고 항목당 ±2.0이 업소에선 ±20.0에 해당 → ×10
        u.owner_score = max(0.0, min(100.0, (u.owner_score or START_OWNER) + (total_delta * 10) + (posting_bonus * 10)))


@router.post("/")
def create_review(payload: dict = None, db: Session = Depends(get_db)):
    """10항목 체크리스트 평가 제출
    body: {match_id, reviewer_role(“influencer”|"owner"), items:{"1":0.2,...}, posting?:"충족", photo_link?}
    """
    d = payload or {}
    m = db.query(models.Match).get(int(d.get("match_id", 0)))
    if not m or m.status not in ("accepted", "visit_done"):
        raise HTTPException(status_code=404, detail="유효한 매칭이 없습니다")
    role = d.get("reviewer_role")
    items = d.get("items", {})
    valid_items = ITEMS_INFL_TO_OWNER if role == "influencer" else ITEMS_OWNER_TO_INFL

    # 검증: 10항목, 값 5단계
    if len(items) != 10:
        raise HTTPException(status_code=400, detail="10개 항목을 모두 평가해주세요")
    total = 0.0
    clean = {}
    for i, key in enumerate(valid_items, start=1):
        v = float(items.get(str(i), 0))
        if v not in ALLOWED:
            raise HTTPException(status_code=400, detail=f"{i}번 항목 점수가 올바르지 않습니다")
        clean[str(i)] = v
        total += v

    # 포스팅 조건 점수 (인플 → 사장 방향에서만 의미: 사장이 채점)
    pb = 0.0
    if d.get("posting") in POSTING_BONUS:
        pb = POSTING_BONUS[d["posting"]]

    # reviewer/reviewee 결정
    if role == "influencer":
        reviewer_id, reviewee_id = m.influencer_id, m.owner_id
    else:
        reviewer_id, reviewee_id = m.owner_id, m.influencer_id

    r = models.Review(
        match_id=m.id, reviewer_id=reviewer_id, reviewee_id=reviewee_id,
        score_delta=round(total, 2),
        item_scores=json.dumps(clean, ensure_ascii=False),
        posting_bonus=pb,
        photo_link=d.get("photo_link"),
    )
    db.add(r)
    # 즉시 반영 (MVP — 원래 2주 일괄이나 MVP는 실시간 반영이 사용자 체감 좋음)
    # reviewee 기준으로 점수 체계 선택 (reviewer가 influencer면 reviewee는 owner)
    _apply_to_user(db, reviewee_id, role != "influencer", total, pb)
    db.commit()
    db.refresh(r)

    # 표시 점수 계산
    reviewee = db.query(models.User).get(reviewee_id)
    # reviewee가 인플이면 10점 체계, 사장이면 100점 체계
    if reviewee.role == "influencer":
        shown, scale = reviewee.influencer_score, "10점 만점"
    else:
        shown, scale = reviewee.owner_score, "100점 만점"
    return {
        "review_id": r.id,
        "total_delta": round(total, 2),
        "posting_bonus": pb,
        "applied_score": round(shown, 1),
        "scale": scale,
    }


@router.post("/visit-done/{match_id}")
def visit_done(match_id: int, db: Session = Depends(get_db)):
    """인플: '촬영이 끝났습니다'"""
    m = db.query(models.Match).get(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="매칭 없음")
    m.status = "visit_done"
    db.commit()
    return {"match_id": m.id, "status": "visit_done"}
