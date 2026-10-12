"""완전자동 숏폼: URL → MP4"""
import os, re, json, base64, subprocess, tempfile, urllib.request
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from ..crawler import UA, list_hotels, hotel_photos, _payload, _fetch

router = APIRouter(prefix="/autoshorts", tags=["autoshorts"])

WORK = "/tmp/autoshorts"

def _dl(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=20).read()
    open(path, "wb").write(data)
    return path

def _gemini_call(prompt, images_b64=None):
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    parts = [{"text": prompt}]
    # 이미지 과다 첨부 시 503 발생 실측 → 4장으로 제한 + 축소 인코딩
    for b in (images_b64 or [])[:4]:
        try:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
        except Exception:
            pass
    body = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
    }).encode()
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
        data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    r = urllib.request.urlopen(req, timeout=150)
    j = json.loads(r.read().decode())
    return ''.join(p.get("text", "") for p in j.get("candidates", [{}])[0].get("content", {}).get("parts", []))

def _retry(fn, n=3, wait=3):
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            if i == n - 1:
                raise
            import time
            time.sleep(wait)

def _tts(text, path):
    """gTTS (구글번역 TTS, 무료, 한국어) — 실패 시 None"""
    try:
        from gtts import gTTS
        gTTS(text=text, lang="ko").save(path)
        return True
    except Exception:
        return False

def _motion_clip(img_path, out_path, dur=3.0, caption=""):
    """사진 1장 → 3초 줌+드리프트 클립 (9:16 1080x1920) + 자막 번인"""
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"zoompan=z='min(zoom+0.0008,1.12)':d={int(dur*30)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
    )
    if caption:
        safe = caption.replace(":", "\:").replace("'", "\\\'")
        font = ""
        for cand in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                     "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
                     "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"]:
            if os.path.exists(cand):
                font = cand
                break
        dt = f"drawtext=text='{safe}':fontcolor=white:fontsize=54:box=1:boxcolor=black@0.5:boxborderw=16:x=(w-tw)/2:y=h-220"
        if font:
            dt += f":fontfile={font}"
        vf += dt
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-t", str(dur),
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "fast", out_path],
        capture_output=True, timeout=120)
    return out_path if os.path.exists(out_path) else None

@router.get("/make")
def make(url: str, count: int = Query(1, ge=1, le=5), city: str = Query(None), script: str = Query(None)):
    """URL 하나 → 인기 1위 호텔 숏폼 MP4 (완전자동)"""
    try:
        import shutil
        shutil.rmtree(WORK, ignore_errors=True)
        os.makedirs(WORK, exist_ok=True)

        # 1) 호텔 수집 (city 파라미터 있으면 URL 대체)
        m = re.search(r'city=(\d+)', url)
        city_code = city or (m.group(1) if m else "623")
        hotels = list_hotels(city_code, count=count)
        if not hotels:
            raise HTTPException(404, "호텔을 찾지 못했습니다")

        results = []
        for rank, h in enumerate(hotels):
            # 2) 사진 7장 수집·다운로드
            photos = hotel_photos(h["id"], limit=25)
            if len(photos) < 7:
                continue
            dl = []
            for i, pu in enumerate(photos[:7]):
                try:
                    dl.append(_dl(pu, f"{WORK}/h{rank}_p{i}.jpg"))
                except Exception:
                    pass
            if len(dl) < 7:
                continue

            # 3) AI 대본 (사진 이해)
            b64s = []
            for pth in dl:
                b64s.append(base64.b64encode(open(pth, "rb").read()).decode())
            script_raw = script if script else None
            if not script_raw:
                try:
                    script_raw = _retry(lambda: _gemini_call(
                        '호텔 사진이다. 21초 숏폼 대본을 만들어라. 구성: 훅+7비트(각3초)+CTA. '
                        '우선규칙: 수영장·자쿠지·루프탑·오션뷰 사진이 있으면 반드시 포함하고 대본에서도 강조(예약하고 싶게). '
                        '규칙: 첫문장 8단어 이내·제품명 금지·단점1개 솔직히·낮은압박CTA. '
                        'JSON만 출력: {"title":"","narrations":["7개, 각 12~20자"],"captions":["7개"]}',
                        b64s))
                except Exception:
                    # 사진 첨부 503 → 텍스트 전용 폴백
                    try:
                        script_raw = _gemini_call(
                            f'"{h["name"]}" 호텔(평점{h["score"]}, {h["reviews"]}) 21초 숏폼 대본. '
                            '훅+7비트(각3초)+CTA. 수영장·자쿠지·루프탑·오션뷰 강조. '
                            '첫문장 8단어 이내·제품명 금지·단점1개 솔직히. '
                            'JSON만: {"title":"","narrations":["7개"],"captions":["7개"]}',
                            None)
                    except Exception:
                        script_raw = None
            narrations = ["최고의 호텔을 소개합니다"] * 7
            captions = [""] * 7
            title = h["name"]
            if script_raw:
                try:
                    sc = json.loads(re.sub(r'```json|```', '', script_raw).strip())
                    narrations = (sc.get("narrations") or narrations)[:7]
                    while len(narrations) < 7: narrations.append("")
                    captions = (sc.get("captions") or [])[:7]
                    while len(captions) < 7: captions.append("")
                    title = sc.get("title") or title
                except Exception:
                    pass

            # 4) 음성 (대본 전체 → TTS)
            voice_path = f"{WORK}/h{rank}_voice.mp3"
            has_voice = _tts(" ".join(narrations), voice_path)

            # 5) 사진 모션 클립 7개 (자막 번인)
            clips = []
            for i in range(7):
                c = _motion_clip(dl[i], f"{WORK}/h{rank}_c{i}.mp4", 3.0, captions[i] if i < len(captions) else "")
                if c: clips.append(c)
            if len(clips) < 7:
                continue

            # 6) 합성
            with open(f"{WORK}/list.txt", "w") as f:
                for c in clips:
                    f.write(f"file '{c}'\n")
            merged = f"{WORK}/h{rank}_merged.mp4"
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{WORK}/list.txt",
                            "-c:v", "libx264", "-preset", "fast", merged], capture_output=True, timeout=300)
            final = f"{WORK}/h{rank}_final.mp4"
            if has_voice:
                subprocess.run(["ffmpeg", "-y", "-i", merged, "-i", voice_path,
                                "-af", "apad", "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final],
                               capture_output=True, timeout=120)
            else:
                import shutil as _sh; _sh.copy(merged, final)

            safe_name = re.sub(r'[^가-힣a-zA-Z0-9]', '_', title)[:20]
            out_name = f"{safe_name}_숏폼.mp4"
            results.append({
                "rank": rank+1, "hotel": h["name"], "title": title,
                "score": h["score"], "reviews": h["reviews"],
                "video": out_name,
                "narrations": narrations,
            })
            # 파일을 마운트된 위치로 (frontend에서 받도록 /static? 대신 API로 다운로드 제공)
            import shutil as _sh2
            _sh2.copy(final, f"{WORK}/{out_name}")

        if not results:
            raise HTTPException(502, "숏폼 생성 실패 (사진/영상 단계 오류)")
        return {"results": results, "download": f"/autoshorts/download/{results[0]['video']}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"자동생성 실패: {e}")

@router.get("/download/{name}")
def download(name: str):
    path = f"{WORK}/{name}"
    if not os.path.exists(path):
        raise HTTPException(404, "파일 없음")
    return FileResponse(path, media_type="video/mp4", filename=name)
