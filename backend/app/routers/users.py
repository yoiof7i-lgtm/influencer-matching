"""사용자/매칭 라우터 — 사장님: 근처 ON 인플 조회(6명) 후 초대(최대2), 인플: 수락"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/nearby/{owner_id}")
def nearby_influencers(owner_id: int, db: Session = Depends(get_db)):
    """사장님 기준: 협찬ON 인플루언서 점수·거리순 6명 표시"""
    owner = db.query(models.User).get(owner_id)
    if not owner or owner.role != "owner":
        raise HTTPException(status_code=404, detail="사장님 계정이 아닙니다")

    infs = (
        db.query(models.User)
        .filter(models.User.role == "influencer", models.User.is_active == True)
        .all()
    )
    # TODO: lat/lng 실거리(Haversine) 계산 적용 — 현재 점수순 정렬
    infs.sort(key=lambda u: -u.influencer_score)
    return [
        {
            "id": u.id,
            "name": u.name,
            "instagram_handle": u.instagram_handle,
            "influencer_score": u.influencer_score,
            "region": u.region,
        }
        for u in infs[:6]
    ]


@router.post("/invite")
def invite(owner_id: int, influencer_id: int, db: Session = Depends(get_db)):
    """사장님 → 인플 초대 (사장님 최대 2명)"""
    pending = (
        db.query(models.Match)
        .filter(models.Match.owner_id == owner_id, models.Match.status == "pending")
        .count()
    )
    if pending >= 2:
        raise HTTPException(status_code=400, detail="초대는 최대 2명까지 가능합니다")
    m = models.Match(owner_id=owner_id, influencer_id=influencer_id, status="pending")
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"match_id": m.id, "status": m.status}


@router.post("/accept/{match_id}")
def accept(match_id: int, db: Session = Depends(get_db)):
    """인플 수락 (1곳만) — 수락 시 나머지 초대 소멸 + 협찬OFF 전환"""
    m = db.query(models.Match).get(match_id)
    if not m or m.status != "pending":
        raise HTTPException(status_code=404, detail="유효한 초대가 없습니다")

    m.status = "accepted"
    # 나머지 pending 초대 소멸
    db.query(models.Match).filter(
        models.Match.influencer_id == m.influencer_id,
        models.Match.status == "pending",
        models.Match.id != match_id,
    ).update({"status": "expired"})
    # 협찬 OFF 전환
    db.query(models.User).filter(models.User.id == m.influencer_id).update({"is_active": False})
    db.commit()
    return {"match_id": m.id, "status": "accepted"}
