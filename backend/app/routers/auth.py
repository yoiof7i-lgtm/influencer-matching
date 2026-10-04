"""인증 라우터 — 회원가입/로그인 (JWT)"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserOut)
def register(data: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다")
    if data.role not in ("influencer", "owner"):
        raise HTTPException(status_code=400, detail="role은 influencer 또는 owner")

    # 인플루언서는 인스타 활성화 확인 필수
    if data.role == "influencer" and not data.instagram_active:
        raise HTTPException(status_code=400, detail="인스타그램 활성화 계정만 가입 가능합니다")

    user = models.User(
        username=data.username,
        password_hash=data.password,  # TODO: bcrypt 해시 적용
        role=data.role,
        name=data.name,
        instagram_handle=data.instagram_handle,
        instagram_active=data.instagram_active,
        shop_name=data.shop_name,
        region=data.region,
        lat=data.lat,
        lng=data.lng,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token)
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == data.get("username")).first()
    if not user or user.password_hash != data.get("password"):  # TODO: bcrypt 검증
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀립니다")
    # TODO: JWT 발급 적용
    return {"access_token": f"dummy-token-user-{user.id}", "token_type": "bearer"}
