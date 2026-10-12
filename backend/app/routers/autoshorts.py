"""완전자동 숏폼: URL → MP4"""
import os, re, json, base64, subprocess, tempfile, urllib.request
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from ..crawler import UA, list_hotels, hotel_photos, _payload, _fetch

router = APIRouter(prefix="/autoshorts", tags=["autoshorts"])

WORK = "/tmp/autoshorts"
OUTDIR = "/code/uploads/shorts"  # 주인님 윈도우 폴더: C:\Users\jaq\influencer-matching\backend\uploads\shorts

def _dl(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=20).read()
    open(path, "wb").write(data)
    return path

def _gemini_call(prompt, images_b64=None):
    """Gemini(사진첨부 불안정 실측) — 실패 시 OpenRouter 비전 모델 폴백"""
    key = os.getenv("GEMINI_API_KEY", "")
    if key:
        try:
            return _gemini_core(key, prompt, images_b64)
        except Exception:
            pass
    return _openrouter_call(prompt, images_b64)

def _openrouter_call(prompt, images_b64=None):
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return None
    content = [{"type": "text", "text": prompt}]
    for b in (images_b64 or [])[:4]:
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}})
    body = json.dumps({"model": "google/gemini-3.8-flash",
                       "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "Authorization": "Bearer " + key})
    r = urllib.request.urlopen(req, timeout=150)
    j = json.loads(r.read().decode())
    return j.get("choices", [{}])[0].get("message", {}).get("content")

def _gemini_core(key, prompt, images_b64=None):
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

def _motion_clip(img_path, out_path, dur=2.5, caption=""):
    """사진 1장 → 2.5초 줌+드리프트 클립 (9:16 1080x1920) + 자막 번인"""
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
def make(url: str, count: int = Query(1, ge=1, le=5), city: str = Query(None), script: str = Query(None), photo_urls: str = Query(None)):
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
            # 2) 사진 14장 수집·다운로드 (프론트 AI 선별 순서 우선: 1전경 2객실 3욕실 4조식 5수영장 6기타 7뷰)
            if photo_urls:
                photos = [u for u in photo_urls.split("|") if u.startswith("http")][:14]
            else:
                photos = hotel_photos(h["id"], limit=25)
            if len(photos) < 7:
                continue
            dl = []
            for i, pu in enumerate(photos):
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
                    # 서버→Gemini 사진첨부는 반복 타임아웃 실측 → 텍스트 전용만 사용
                    script_raw = _retry(lambda: _gemini_call(
                        f'"{h["name"]}" 호텔(평점{h["score"]}, {h["reviews"]}) 35초 숏폼 대본. '
                        '사진 순서는 고정: 침대룸→침대룸(다른각도)→화장실→수영장/자쿠지→건물외관→전망→조식. 대본도 이 순서에 맞게. '
                        '훅+14비트(각2.5초)+CTA. 첫문장 8단어 이내·호텔명 금지·단점1개 솔직히. '
                        'JSON만: {"title":"","narrations":["7개, 각 12~20자"],"captions":["7개, 10자 이내"]}',
                        None))
                except Exception:
                    # 사진 첨부 503 → 텍스트 전용 폴백
                    try:
                        script_raw = _gemini_call(
                            f'"{h["name"]}" 호텔(평점{h["score"]}, {h["reviews"]}) 35초 숏폼 대본. '
                            '훅+14비트(각2.5초)+CTA. 수영장·자쿠지·루프탑·오션뷰 강조. '
                            '첫문장 8단어 이내·제품명 금지·단점1개 솔직히. '
                            'JSON만: {"title":"","narrations":["14개"],"captions":["14개"]}',
                            None)
                    except Exception:
                        script_raw = None
            NPH = 14
            narrations = ["최고의 호텔을 소개합니다"] * 14
            captions = [""] * 14
            title = h["name"]
            if script_raw:
                try:
                    sc = json.loads(re.sub(r'```json|```', '', script_raw).strip())
                    narrations = [n for n in (sc.get("narrations") or []) if n][:14]
                    captions = [c for c in (sc.get("captions") or []) if c][:14]
                    title = sc.get("title") or title
                except Exception:
                    pass
            # AI가 14개보다 적게 내면 나머지 자동 보충 (중복 문구 방지)
            FILL_N = ["편안하게 쉬어갈 수 있는 공간이에요", "호텔만의 디테일이 돋보여요",
                      "머무는 동안 불편함이 없어요", "체크인부터 체크아웃까지 만족스러워요",
                      "가격 대비 만족도가 높은 곳이에요", "다음 여행에서 다시 오고 싶은 곳"]
            FILL_C = ["추천 숙소", "만족스러운 선택", "디테일 좋아요", "편안한 머무름", "가성비 좋아요", "재방문 의사"]
            fi = 0
            while len(narrations) < 14 and fi < len(FILL_N):
                narrations.append(FILL_N[fi]); captions.append(FILL_C[fi] if fi < len(FILL_C) else ""); fi += 1
            while len(narrations) < 14:
                narrations.append("여행에 딱 맞는 숙소예요"); captions.append("여행 추천")

            # 4) 음성 (대본 전체 → TTS)
            voice_path = f"{WORK}/h{rank}_voice.mp3"
            has_voice = _tts(" ".join(narrations), voice_path)

            # 5) 사진 모션 클립 7개 (자막 번인 — captions 없으면 narration 사용, 자막 항상 표시)
            clips = []
            for i in range(14):
                cap = (captions[i] if i < len(captions) else "") or (narrations[i] if i < len(narrations) else "")
                c = _motion_clip(dl[i], f"{WORK}/h{rank}_c{i}.mp4", 3.0, cap)
                if c: clips.append(c)
            if len(clips) < 14:
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
                                "-af", "apad,loudnorm=I=-16:TP=-1.5", "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final],
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
            # 윈도우에서 바로 볼 수 있는 폴더에 저장
            import shutil as _sh2
            os.makedirs(OUTDIR, exist_ok=True)
            _sh2.copy(final, f"{OUTDIR}/{out_name}")
            # 대본 텍스트도 저장
            with open(f"{OUTDIR}/{safe_name}_대본.txt", "w", encoding="utf-8") as tf:
                tf.write(f"호텔: {h['name']} (평점 {h['score']}, {h['reviews']})\n제목: {title}\n\n")
                for i, (nn, cc) in enumerate(zip(narrations, captions)):
                    tf.write(f"[{i+1}] {nn}\n    자막: {cc}\n")
                tf.write(f"\n[다운로드] /autoshorts/download/{out_name}\n")

        if not results:
            raise HTTPException(502, "숏폼 생성 실패 (사진/영상 단계 오류)")
        return {"results": results, "download": f"/autoshorts/download/{results[0]['video']}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"자동생성 실패: {e}")

@router.get("/download/{name}")
def download(name: str):
    for base in [OUTDIR, WORK]:
        path = f"{base}/{name}"
        if os.path.exists(path):
            return FileResponse(path, media_type="video/mp4", filename=name)
    raise HTTPException(404, "파일 없음")
