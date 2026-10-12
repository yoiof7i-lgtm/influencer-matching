"""숏폼 스튜디오 크롤링 API"""
import urllib.request
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from ..crawler import list_hotels, hotel_photos

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

router = APIRouter(prefix="/crawl", tags=["crawl"])

@router.get("/trip")
def crawl_trip(city: str = Query("623"), count: int = Query(10, ge=1, le=20),
               checkin: str = "2026-10-20", checkout: str = "2026-10-21"):
    try:
        return {"hotels": list_hotels(city, count, checkin, checkout)}
    except Exception as e:
        raise HTTPException(502, f"trip.com 수집 실패: {e}")

@router.get("/photos")
def crawl_photos(hotel_id: str, limit: int = Query(20, ge=1, le=40)):
    try:
        return {"photos": hotel_photos(hotel_id, limit)}
    except Exception as e:
        raise HTTPException(502, f"사진 수집 실패: {e}")

@router.get("/proxy-img")
def proxy_img(url: str):
    """tripcdn 이미지 CORS 우회 프록시"""
    if not url.startswith("https://ak-d.tripcdn.com/") and not url.startswith("https://pages.trip.com/"):
        raise HTTPException(400, "허용되지 않은 도메인")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        data = urllib.request.urlopen(req, timeout=15).read()
        return Response(content=data, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(502, f"이미지 로드 실패: {e}")
