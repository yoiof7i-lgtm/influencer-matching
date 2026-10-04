"""평가 라우터 — 상호 점수(±0.2/0.1/0/-0.1/-0.2), 2주 일괄·익명 반영"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/reviews", tags=["reviews"])

ALLOWED_DELTAS = (-0.2, -0.1, 0.0, 0.1, 0.2)


@router.post("/", response_model=schemas.ReviewOut)
def create_review(data: schemas.ReviewCreate, db: Session = Depends(get_db)):
    if data.score_delta not in ALLOWED_DELTAS:
        raise HTTPException(status_code=400, detail="평가는 ±0.2/±0.1/0 중 하나여야 합니다")
    m = db.query(models.Match).get(data.match_id)
    if not m or m.status != "accepted":
        raise HTTPException(status_code=404, detail="유효한 매칭이 없습니다")
    r = models.Review(
        match_id=data.match_id,
        reviewer_id=m.owner_id if data.reviewee_id == m.influencer_id else m.influencer_id,
        reviewee_id=data.reviewee_id,
        score_delta=data.score_delta,
        photo_link=data.photo_link,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r
    # TODO: 2주 모아 일괄·익명 반영 배치, 후기링크 미제출 3개→OFF 처리


@router.post("/visit-done/{match_id}")
def visit_done(match_id: int, db: Session = Depends(get_db)):
    """인플: '촬영이 끝났습니다' → 사장님: '수고하셨습니다~후기 잘부탁합니다~'"""
    m = db.query(models.Match).get(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="매칭 없음")
    m.status = "visit_done"
    db.commit()
    return {"match_id": m.id, "status": "visit_done"}
