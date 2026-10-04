"""API 스키마 (Pydantic)"""
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    username: str
    password: str
    role: str  # "influencer" | "owner"
    name: str
    instagram_handle: Optional[str] = None
    instagram_active: Optional[bool] = False
    shop_name: Optional[str] = None
    business_number: Optional[str] = None  # 사장님: 사업자등록번호 (진위확인)
    region: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    name: str
    influencer_score: Optional[float] = None
    owner_score: Optional[float] = None
    is_active: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ReviewCreate(BaseModel):
    match_id: int
    reviewee_id: int
    score_delta: float  # -0.2 ~ +0.2
    photo_link: Optional[str] = None


class ReviewOut(BaseModel):
    id: int
    match_id: int
    reviewer_id: int
    reviewee_id: int
    score_delta: float
    applied: bool
    created_at: datetime

    class Config:
        from_attributes = True
