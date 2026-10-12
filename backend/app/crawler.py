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
        img = re.search(r'"(https://ak-d\.tripcdn\.com/images/[^"]+?\.jpg)"',
                        payload[max(0, m.start()-2000):m.start()+3000])
        hotels.append({
            "id": hid, "name": name.group(1),
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
        return h["score"] * int(n)
    hotels.sort(key=pop, reverse=True)
    return hotels[:count]

def hotel_photos(hotel_id: str, limit: int = 20):
    html = _fetch(f"https://kr.trip.com/hotels/detail/?hotelId={hotel_id}")
    payload = _payload(html)
    imgs = list(dict.fromkeys(
        re.findall(r'(https://ak-d\.tripcdn\.com/images/[^"\\,\s\[\]]+?\.jpg)', payload)))
    return imgs[:limit]
