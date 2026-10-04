"""인증 라우터 — 회원가입/로그인 (JWT)"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.verify import check_instagram, check_business_number, verify_profile_code

import hashlib
import hmac
import base64
import json as _json
import time as _time
import os

router = APIRouter(prefix="/auth", tags=["auth"])

# ── 간단한 HS256 JWT (표준 형식) ──
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
ALG = "HS256"
TOKEN_TTL = 3600  # 1시간


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: int) -> str:
    header = _b64url(_json.dumps({"alg": ALG, "typ": "JWT"}).encode())
    payload = _b64url(_json.dumps({
        "sub": str(user_id),
        "iat": int(_time.time()),
        "exp": int(_time.time()) + TOKEN_TTL,
    }).encode())
    sig = _b64url(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_token(token: str) -> int:
    try:
        header, payload, sig = token.split(".")
        expected = _b64url(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError
        claims = _json.loads(_b64url_decode(payload))
        if claims["exp"] < _time.time():
            raise ValueError("만료된 토큰")
        return int(claims["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 토큰입니다")


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 해시 (bcrypt 대체, 표준 라이브러리만 사용)"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except ValueError:
        return False


_oauth2 = HTTPBearer(auto_error=False)


def get_current_user(token=Depends(_oauth2), db: Session = Depends(get_db)):
    if token is None:
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다")
    user_id = verify_token(token.credentials)
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다")
    return user


@router.post("/register", response_model=schemas.UserOut)
def register(data: schemas.UserCreate, db: Session = Depends(get_db)):
    import logging
    logging.info(f"[register] role={data.role} username={data.username!r} "
                 f"name={data.name!r} ig={data.instagram_handle!r} "
                 f"ig_active={data.instagram_active} shop={data.shop_name!r} "
                 f"biz={'있음' if data.business_number else '없음'} region={data.region!r}")
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다")
    if data.role not in ("influencer", "owner", "admin"):
        raise HTTPException(status_code=400, detail="role은 influencer 또는 owner")
    # 사장님 사업자번호 중복 등록 방지 (한 사업자 = 한 계정)
    business_no = None
    if data.role == "owner":
        business_no = (data.business_number or "").strip()
        if not business_no:
            raise HTTPException(status_code=400, detail="사업자등록번호를 입력해주세요")
        dup = db.query(models.User).filter(
            models.User.business_number == business_no).first()
        if dup:
            raise HTTPException(status_code=400,
                detail="이미 등록된 사업자번호입니다 (다른 계정으로 가입 불가)")

    # 인플루언서: 인스타 활성화 확인 (자동검증 → 실패 시 수동승인 큐)
    if data.role == "influencer":
        if not data.instagram_active:
            raise HTTPException(status_code=400, detail="인스타그램 활성화 계정만 가입 가능합니다")
        ig = check_instagram(data.instagram_handle or "")
        if not ig["valid"]:
            raise HTTPException(status_code=400, detail=ig["reason"])

    # 사장님: 사업자등록번호 진위확인 (체크섬/국세청) — 위에서 중복 확인 완료
    if data.role == "owner":
        biz = check_business_number(business_no)
        if not biz["valid"]:
            raise HTTPException(status_code=400, detail=biz["reason"])

    # 인플: 프로필 코드 인증용 코드 발급 (본인 계정 확인용)
    ig_code = None
    if data.role == "influencer":
        import secrets
        ig_code = "HYC-" + secrets.token_hex(2).upper()  # 예: HYC-3F7K

    user = models.User(
        username=data.username,
        password_hash=hash_password(data.password),  # PBKDF2-SHA256 해시 저장
        role=data.role,
        name=data.name,
        instagram_handle=data.instagram_handle,
        instagram_active=data.instagram_active,
        shop_name=data.shop_name,
        business_number=business_no,
        ig_verify_code=ig_code,
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
    import logging
    uname = (data or {}).get("username", "")
    user = db.query(models.User).filter(models.User.username == uname).first()
    if not user:
        logging.warning(f"[login] 계정 없음: {uname!r}")
    elif not verify_password((data or {}).get("password", ""), user.password_hash):
        logging.warning(f"[login] 비밀번호 불일치: {uname!r}")
    user = db.query(models.User).filter(models.User.username == data.get("username")).first()
    if not user or not verify_password(data.get("password", ""), user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀립니다")
    return {"access_token": create_token(user.id), "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserOut)
def me(current: models.User = Depends(get_current_user)):
    """보호된 엔드포인트 — JWT 필요. 내 정보 조회."""
    return current


@router.post("/verify-instagram")
def verify_instagram(current: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """인플: 프로필에 넣은 인증 코드 확인 (본인 계정 인증)"""
    if current.role != "influencer":
        raise HTTPException(status_code=400, detail="인플루언서만 인증 대상입니다")
    if not current.instagram_handle:
        raise HTTPException(status_code=400, detail="인스타 계정이 없습니다")
    if current.ig_verified:
        return {"verified": True, "reason": "이미 인증 완료"}

    r = verify_profile_code(current.instagram_handle, current.ig_verify_code or "")
    if r.get("verified"):
        current.ig_verified = True
        db.add(current)
        db.commit()
        return {"verified": True, "reason": r["reason"]}
    return r
