"""데이터 모델 — 회원 2종(인플루언서/사장님), 초대/매칭/평가"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # "influencer" | "owner"
    name = Column(String(100), nullable=False)
    instagram_handle = Column(String(100))          # 인플루언서만
    instagram_active = Column(Boolean, default=False)  # 인스타 활성화 확인
    shop_name = Column(String(100))                 # 사장님만
    business_number = Column(String(20))            # 사장님: 사업자등록번호
    region = Column(String(50))                     # 위치기반 지역
    lat = Column(Float)
    lng = Column(Float)
    influencer_score = Column(Float, default=5.0)   # 10점 만점 (초기 5.0)
    owner_score = Column(Float, default=50.0)       # 100점 만점 (초기 50.0)
    is_active = Column(Boolean, default=True)       # 협찬ON/OFF 토글
    review_pending = Column(Integer, default=0)     # 미제출 후기 링크 수 (3개→OFF)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    """사장님 초대 → 인플 수락 (1인플=1수락, 초대 시 나머지 소멸)"""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    influencer_id = Column(Integer, ForeignKey("users.id"))  # 수락 전 NULL
    status = Column(String(20), default="pending")  # pending|accepted|expired|canceled
    visit_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    """상호 평가: ±0.2/0.1/0/-0.1/-0.2, 2주 모아 일괄·익명 반영"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    score_delta = Column(Float, nullable=False)  # -0.2 ~ +0.2
    photo_link = Column(Text)                    # 후기 링크 (인플 제출)
    applied = Column(Boolean, default=False)     # 2주 일괄 반영 여부
    created_at = Column(DateTime(timezone=True), server_default=func.now())
