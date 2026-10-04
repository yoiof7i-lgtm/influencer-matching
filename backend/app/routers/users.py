"""사용자/매칭 라우터 — 사장님: 근처 ON 인플 조회(6명) 후 초대(최대2), 인플: 수락"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/users", tags=["users"])

from fastapi.security import HTTPBearer as _HB
_admin_bearer = _HB(auto_error=False)


def _current_user(credentials=Depends(_admin_bearer), db: Session = Depends(get_db)):
    """JWT에서 현재 사용자 조회"""
    from app.routers.auth import verify_token
    if credentials is None:
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다")
    user_id = verify_token(credentials.credentials)
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="사용자 없음")
    return user


def _admin_user(credentials=Depends(_admin_bearer), db: Session = Depends(get_db)):
    """JWT에서 현재 사용자 조회 + 관리자 검증"""
    from app.routers.auth import verify_token
    if credentials is None:
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다")
    user_id = verify_token(credentials.credentials)
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="사용자 없음")
    require_admin(user)
    return user


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


@router.get("/my-invites")
def my_invites(current=Depends(_current_user), db: Session = Depends(get_db)):
    """사장님: 내가 보낸 초대 목록"""
    if current.role != "owner":
        raise HTTPException(status_code=400, detail="사장님만 조회 가능합니다")
    invites = (
        db.query(models.Match)
        .filter(models.Match.owner_id == current.id)
        .all()
    )
    out = []
    for m in invites:
        inf = db.query(models.User).get(m.influencer_id) if m.influencer_id else None
        out.append({
            "match_id": m.id,
            "influencer_name": inf.name if inf else "?",
            "status": m.status,
        })
    return out


@router.get("/invitations")
def my_invitations(current=Depends(_current_user), db: Session = Depends(get_db)):
    """인플: 내가 받은 pending 초대 목록 (사장님 정보 포함)"""
    if current.role != "influencer":
        raise HTTPException(status_code=400, detail="인플루언서만 조회 가능합니다")
    invites = (
        db.query(models.Match)
        .filter(models.Match.influencer_id == current.id,
                models.Match.status == "pending")
        .all()
    )
    out = []
    for m in invites:
        owner = db.query(models.User).get(m.owner_id)
        out.append({
            "match_id": m.id,
            "owner_name": owner.name if owner else "?",
            "shop_name": owner.shop_name if owner else "",
            "region": owner.region if owner else "",
            "owner_score": owner.owner_score if owner else None,
            "created_at": str(m.created_at),
        })
    return out


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


# ───────── 관리자 기능 ─────────
def require_admin(user):
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다")
    return user


@router.get("/admin/pending")
def pending_verification(current=Depends(_admin_user), db: Session = Depends(get_db)):
    """인스타 인증 대기 인플 목록 (수동 확인용)"""
    infs = (
        db.query(models.User)
        .filter(models.User.role == "influencer", models.User.ig_verified == False)  # noqa: E712
        .all()
    )
    return [
        {
            "id": u.id,
            "name": u.name,
            "username": u.username,
            "instagram_handle": u.instagram_handle,
            "ig_verify_code": u.ig_verify_code,
        }
        for u in infs
    ]


@router.post("/admin/approve/{user_id}")
def approve_instagram(user_id: int, current=Depends(_admin_user), db: Session = Depends(get_db)):
    """관리자: 인스타 인증 승인 (프로필에 코드 넣었는지 직접 확인 후)"""
    u = db.query(models.User).get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="사용자 없음")
    u.ig_verified = True
    db.commit()
    return {"id": u.id, "username": u.username, "ig_verified": True}


@router.post("/admin/reject/{user_id}")
def reject_instagram(user_id: int, current=Depends(_admin_user), db: Session = Depends(get_db)):
    """관리자: 인증 거부 — 새 코드 발급(재인증 요구)"""
    import secrets
    u = db.query(models.User).get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="사용자 없음")
    u.ig_verify_code = "HYC-" + secrets.token_hex(2).upper()
    u.ig_verified = False
    db.commit()
    return {"id": u.id, "username": u.username, "new_code": u.ig_verify_code}
