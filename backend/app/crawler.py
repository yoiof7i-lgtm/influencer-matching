"""trip.com 호텔 크롤러 — 숏폼 스튜디오용"""
import re, json, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

def _payload(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(.*?)(?<!\\)")\]\)', html, re.S)
    return ''.join(json.loads(f'"{c}"') for _, c in chunks)

def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")

def list_hotels(city: str = "623", count: int = 10, checkin="2026-10-20", checkout="2026-10-21"):
    html = _fetch(f"https://kr.trip.com/hotels/list?city={city}&checkin={checkin}&checkout={checkout}")
    payload = _payload(html)
    hotels, seen = [], set()
    for m in re.finditer(r'"hotelId":"(\d+)"', payload):
        hid = m.group(1)
        if hid in seen:
            continue
        seen.add(hid)
        w = payload[m.start():m.start()+6000]
        name = re.search(r'"nameInfo":\{"name":"([^"]+)"', w)
        if not name:
            continue
        price = re.search(r'"price":(\d+),"currency"', w)
        score = re.search(r'"commentScore":"([\d.]+)"', w)
        rev = re.search(r'"commenterNumber":"([^"]+)"', w)
        # 할인율 (discountTags의 "48% 할인" 등)
        dis = re.search(r'"discountTags":\[\{"tagTitle":"(\d+)%\s*할인"', w)
        disc = int(dis.group(1)) if dis else 0
        img = re.search(r'"(https://ak-d\.tripcdn\.com/images/[^"]+?\.jpg)"',
                        payload[max(0, m.start()-2000):m.start()+3000])
        hotels.append({
            "id": hid, "name": name.group(1),
            "discount": disc,
            "price": int(price.group(1)) if price else 0,
            "score": float(score.group(1)) if score else 0.0,
            "reviews": rev.group(1) if rev else "",
            "img": img.group(1) if img else "",
            "detail_url": f"https://kr.trip.com/hotels/detail/?hotelId={hid}&checkIn={checkin}&checkOut={checkout}",
        })
        if len(hotels) >= count * 2:
            break
    # 잘팔리는 순 기준: 리뷰수×평점 (인기 점수)
    import re as _re
    def pop(h):
        n = _re.sub(r"[^\d]", "", h["reviews"]) or "0"
        base = h["score"] * int(n)
        return (h["discount"] * 1_000_000) + base  # 할인율 있으면 압도적 우선
    hotels.sort(key=pop, reverse=True)
    return hotels[:count]

def hotel_photos(hotel_id: str, limit: int = 20):
    """호텔 제공 사진만 (리뷰어 사진·프로필 아이콘 제외 — 주인님 지시)"""
    html = _fetch(f"https://kr.trip.com/hotels/detail/?hotelId={hotel_id}")
    payload = _payload(html)
    # 리뷰 섹션 시작 이전의 이미지만 = 호텔 제공 사진
    cm = re.search(r'isTripComment', payload)
    cut = cm.start() if cm else len(payload)
    imgs = list(dict.fromkeys(
        u for u in re.findall(r'(https://ak-d\.tripcdn\.com/images/[^"\\,\s\[\]]+?\.jpg)', payload)
        if payload.find(u) < cut))
    # 같은 사진이 크기만 다른 URL로 중복됨 (실측: 212 URL = 86 고유) → 이미지ID 기준 고유화
    unique, seen = [], set()
    for u in imgs:
        m = re.search(r'/images/([0-9a-zA-Z]+?)_', u)
        key = m.group(1) if m else u
        if key in seen:
            continue
        seen.add(key)
        # 최고 화질 URL 변환: _Z_1440_2560 (9:16 고해상도 — 실측 4.5배 데이터)
        big = re.sub(r'_[A-Z]_\d+_\d+[^.]*\.jpg', '_Z_1440_2560_R50_Q90.jpg', u)
        unique.append(big if big != u else u)
    return unique[:limit]
