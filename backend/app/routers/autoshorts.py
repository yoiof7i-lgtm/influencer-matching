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

def _tts_dur(path):
    """음성 길이(초) 측정"""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, timeout=30)
        return float(r.stdout.decode().strip())
    except Exception:
        return 0.0

def _tts(text, path):
    """1순위: Gemini TTS (자연스러움, 무료) → 실패 시 gTTS. 반환: 성공여부"""
    key = os.getenv("GEMINI_API_KEY", "")
    # Gemini TTS (PCM 24kHz 출력 → WAV 변환)
    if key:
        try:
            body = json.dumps({
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                                     "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}
            }).encode()
            req = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent",
                data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
            r = urllib.request.urlopen(req, timeout=120)
            j = json.loads(r.read().decode())
            import base64
            pcm_b64 = j["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm_path = path + ".pcm"
            open(pcm_path, "wb").write(base64.b64decode(pcm_b64))
            # PCM(s16le 24kHz mono) → mp3
            subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                            "-i", pcm_path, "-c:a", "libmp3lame", "-b:a", "128k", path],
                           capture_output=True, timeout=60)
            os.remove(pcm_path)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return True
        except Exception:
            pass
    # 폴백: gTTS
    try:
        from gtts import gTTS
        gTTS(text=text, lang="ko").save(path)
        return True
    except Exception:
        return False

def _motion_clip(img_path, out_path, dur=2.5, caption="", idx=0, hook_title=""):
    """사진 1장 → 2.5초 모션 클립 (9:16 1080x1920) — 모션 교차·색보정·자막 개선"""
    D = int(dur * 30)
    # 모션 교차 (지겨움 방지): 줌인 → 줌아웃 → 좌패닝 → 우패닝 순환
    motions = [
        f"zoompan=z='min(1.0+on/{D}*0.12,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={D}:s=1080x1920:fps=30",  # 줌인
        f"zoompan=z='max(1.12-on/{D}*0.12,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={D}:s=1080x1920:fps=30",  # 줌아웃
        f"zoompan=z=1.08:x='iw/2-(iw/zoom/2)+(iw/4)*(on/{D}-0.5)':y='ih/2-(ih/zoom/2)':d={D}:s=1080x1920:fps=30",    # 좌→우 패닝
        f"zoompan=z=1.08:x='iw/2-(iw/zoom/2)-(iw/4)*(on/{D}-0.5)':y='ih/2-(ih/zoom/2)':d={D}:s=1080x1920:fps=30",    # 우→좌 패닝
    ]
    motion = motions[idx % 4]
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"{motion},"
        # 색보정: 채도+약간, 대비 약간, 살짝 선명
        "eq=saturation=1.15:contrast=1.06,"
        "unsharp=5:5:0.5"
    )
    # 폰트
    font = ""
    for cand in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"]:
        if os.path.exists(cand):
            font = cand
            break
    fontarg = f":fontfile={font}" if font else ""
    def esc(t):
        return t.replace(":", "\:").replace("'", "\\\'").replace("%", "\\%")
    # 자막: 하단, 반투명 박스+테두리
    if caption:
        vf += (
            f",drawtext=text='{esc(caption)}'{fontarg}"
            ":fontcolor=white:fontsize=58:box=1:boxcolor=black@0.45:boxborderw=18"
            ":x=(w-tw)/2:y=h-200:borderw=2:bordercolor=black@0.6"
        )
    # 훅 타이틀: 첫 장면(idx=0)에 상단 큰 제목
    if hook_title:
        vf += (
            f",drawtext=text='{esc(hook_title)}'{fontarg}"
            ":fontcolor=white:fontsize=64:box=1:boxcolor=black@0.55:boxborderw=22"
            ":x=(w-tw)/2:y=h*0.12"
        )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-t", str(dur),
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "slow",
         "-crf", "18", "-pix_fmt", "yuv420p", out_path],
        capture_output=True, timeout=180)
    return out_path if os.path.exists(out_path) else None

def _bgm(path, dur):
    """부드러운 배경음악 생성 (사인 코드 진행 — 저음 잔잔한 분위기)"""
    # Am→F→C→G 진행 느낌: 주파수 교차 페이드 (단순 합성)
    import math
    try:
        seg = dur / 4
        fc = "aevalsrc="
        tones = [(220.0, "A"), (174.6, "F"), (261.6, "C"), (196.0, "G")]
        parts = []
        for i, (f, _) in enumerate(tones):
            parts.append(f"sine=frequency={f}:duration={seg+0.5}:sample_rate=44100")
        # 각 부분을 연결 + 페이드
        inputs = []
        filters = []
        for i, src in enumerate(parts):
            inputs += ["-f", "lavfi", "-i", src]
        # concat + 볼륨 낮게 + 페이드
        n = len(parts)
        fcm = f"concat=n={n}:v=0:a=1,volume=0.12,afade=t=in:d=2,afade=t=out:st={dur-2}:d=2"
        subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", fcm, "-t", str(dur), path],
                       capture_output=True, timeout=60)
        return os.path.exists(path)
    except Exception:
        return False

@router.get("/make")
def make(url: str, count: int = Query(1, ge=1, le=5), city: str = Query(None), script: str = Query(None), photo_urls: str = Query(None), hook: str = Query(None)):
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
                    hook_part = (f'훅은 이 문구를 그대로 사용: 「{hook}」. ' if hook
                                 else '훅은 반드시 아래 4스타일 중 하나([지역]은 실제 지역명): '
                                      '"솔직히 이 방은 ○○ 하나 때문에 또 가고 싶어요" / "[지역] 여행 갈 때 이 가격대 룸 모르면 손해인 이유" / '
                                      '"퇴근하고 당장 누워버리고 싶은 대리만족 호캉스 룸 3초 투어" / "아직도 [지역]에서 숙소 어디 갈지 고민 중이세요?". ')
                    script_raw = _retry(lambda: _gemini_call(
                        f'"{h["name"]}" 호텔(평점{h["score"]}, {h["reviews"]}) 35초 숏폼 대본. '
                        '사진 순서 고정: 침대룸×3→화장실×2→수영장/자쿠지×2→외관→전망×2→조식→로비/편의×3. '
                        '한자·한문 표기 절대 금지(순수 한국어만). 실제 입으로 말하듯 자연스러운 구어체(~해요/~죠, 문어체·명사형 종결 금지). 나레이션 각 10~14자(2.5~3초 분량). '
                        '룸 비트(1~3)는 룸의 확실한 특징만: 통창뷰·가성비·호캉스감 중 사진에서 보이는 것 + 방에서 자쿠지·수영장·바다(해변) 뷰가 보이면 최우선으로 언급. 사진에 없는 촉감·냄새·소리 등은 쓰지 말 것. '
                        + hook_part +
                        '훅+14비트(각2.5초)+CTA. 첫문장 8단어 이내·호텔명 금지·단점1개 솔직히·나레이션은 비트 시간에 맞춰 각 8~11자(2.5초=초당4자). '
                        'JSON만: {"title":"","narrations":["14개, 각 10~14자"],"captions":["14개, 10자 이내"]}',
                        None))
                except Exception:
                    # 사진 첨부 503 → 텍스트 전용 폴백
                    try:
                        script_raw = _gemini_call(
                            f'"{h["name"]}" 호텔(평점{h["score"]}, {h["reviews"]}) 35초 숏폼 대본. '
                            '훅+14비트(각2.5초)+CTA. 수영장·자쿠지·바다(해변)·루프탑·오션뷰 강조. '
                            '첫문장 8단어 이내·제품명 금지·단점1개 솔직히. '
                            'JSON만: {"title":"","narrations":["14개, 각 10~14자"],"captions":["14개"]}',
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

            # 4) 음성 먼저 생성 → 실제 길이 측정 (영상을 음성에 맞춤 — 길이 불일치 근본 해결)
            voice_path = f"{WORK}/h{rank}_voice.mp3"
            has_voice = _tts(" ".join(narrations), voice_path)
            V = _tts_dur(voice_path) if has_voice else 0.0
            if not has_voice or V <= 0:
                V = 14 * 2.5  # 음성 실패 시 기본 35초
            XFADE = 0.4
            # 클립당 길이: 크로스페이드 겹침(13회) 보정해서 최종길이 = 음성길이
            clip_dur = (V + 13 * XFADE) / 14
            clip_dur = max(1.8, min(clip_dur, 4.5))  # 상식 범위 (너무 짧/길면 캡)
            # 최종 예상 길이 = clip_dur*14 - 13*0.4

            # 5) 사진 모션 클립 (동적 길이, 자막+훅)
            clips = []
            for i in range(14):
                cap = (captions[i] if i < len(captions) else "") or (narrations[i] if i < len(narrations) else "")
                c = _motion_clip(dl[i], f"{WORK}/h{rank}_c{i}.mp4", clip_dur, cap, idx=i,
                                 hook_title=hook if i == 0 else "")
                if c: clips.append(c)
            if len(clips) < 14:
                continue

            # 6) 합성: 크로스페이드 (동적 오프셋)
            merged = f"{WORK}/h{rank}_merged.mp4"
            if len(clips) > 1:
                inputs = []
                for c in clips:
                    inputs += ["-i", c]
                fc = ""
                for i in range(len(clips) - 1):
                    off = i * (clip_dur - XFADE)
                    fc += f"[{'0' if i==0 else f'v{i}'}][{i+1}:v]xfade=transition=fade:duration={XFADE}:offset={off:.2f}[v{i+1}];"
                fc += f"[v{len(clips)-1}]format=yuv420p[vout]"
                subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", fc,
                                "-map", "[vout]", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                                merged], capture_output=True, timeout=420)
            else:
                subprocess.run(["ffmpeg", "-y", "-i", clips[0], "-c:v", "libx264", merged],
                               capture_output=True, timeout=120)
            # 최종: 음성 + BGM 믹스 (영상 길이 기준 — shortest로 음성 잘리지 않게 apad)
            final = f"{WORK}/h{rank}_final.mp4"
            bgm = f"{WORK}/h{rank}_bgm.wav"
            has_bgm = _bgm(bgm, V)
            if has_voice and has_bgm:
                subprocess.run(["ffmpeg", "-y", "-i", merged, "-i", voice_path, "-i", bgm,
                                "-filter_complex",
                                "[1:a]apad,loudnorm=I=-16:TP=-1.5[nar];"
                                "[2:a]volume=0.5,apad[bgm];"
                                "[nar][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                                "-map", "0:v", "-map", "[aout]", "-shortest",
                                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final],
                               capture_output=True, timeout=180)
            elif has_voice:
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
            # 대본 + 인스타 게시물 캡션/태그 저장 (복붙으로 바로 포스팅 가능)
            cap_raw = None
            try:
                cap_raw = _gemini_call(
                    f'"{h["name"]}" 호텔 숏폼 릴스 게시물 캡션 작성. 대본: {" ".join(narrations[:5])}. '
                    '규칙: 1인칭 솔직후기 톤(~해요) 3~5문장 + 이모지 3개 + 줄바꿈, '
                    '해시태그 12개(지역·여행·호텔·숙소 조합, #제주여행 스타일). '
                    'JSON만: {"caption":"","tags":["#태그 12개"]}',
                    None)
            except Exception:
                pass
            cap_txt, tags = f"{title}", []
            if cap_raw:
                try:
                    cj = json.loads(re.sub(r'```json|```', '', cap_raw).strip())
                    cap_txt, tags = cj.get("caption", cap_txt), cj.get("tags", [])
                except Exception:
                    pass
            with open(f"{OUTDIR}/{safe_name}_대본.txt", "w", encoding="utf-8") as tf:
                tf.write(f"호텔: {h['name']} (평점 {h['score']}, {h['reviews']})\n제목: {title}\n\n")
                for i, (nn, cc) in enumerate(zip(narrations, captions)):
                    tf.write(f"[{i+1}] {nn}\n    자막: {cc}\n")
                tf.write("\n═══ 인스타 릴스 게시물 (아래 복붙) ═══\n\n")
                tf.write(f"{cap_txt}\n\n")
                tf.write(" ".join(tags))
                tf.write(f"\n\n═══ \n[영상] {out_name} / 35초 1080x1920 / 바로 릴스 업로드 가능\n")

        if not results:
            raise HTTPException(502, "숏폼 생성 실패 (사진/영상 단계 오류)")
        return {"results": results, "download": f"/autoshorts/download/{results[0]['video']}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"자동생성 실패: {e}")

@router.get("/all")
def make_all(hook: str = Query(None), count_per_city: int = Query(1, ge=1, le=2), cities_sel: str = Query(None)):
    """지역 선택 자동 제작 — cities_sel(쉼표 구분 코드) 지정 시 선택 지역만, 없으면 전체"""
    try:
        from ..routers.crawl import CITIES
        cities = [(c["name"], c["code"]) for c in CITIES]
        if cities_sel:
            want = [x.strip() for x in cities_sel.split(",") if x.strip()]
            cities = [(n, c) for n, c in cities if c in want]
        # 코드 중복 제거 (같은 코드 두 번 생성 방지)
        seen_code = set()
        uniq = []
        for n, c in cities:
            if c in seen_code:
                continue
            seen_code.add(c)
            uniq.append((n, c))
        results = []
        errors = []
        for name, code in uniq:
            try:
                import urllib.parse as _up
                q = _up.quote(f"https://kr.trip.com/hotels/list?city={code}&checkin=2026-10-20&checkout=2026-10-21", safe='')
                u = f"http://localhost:8000/autoshorts/make?url={q}&count={count_per_city}"
                if hook:
                    u += "&hook=" + _up.quote(hook)
                req = urllib.request.Request(u, headers={"User-Agent": "internal"})
                r = urllib.request.urlopen(req, timeout=560)
                j = json.loads(r.read().decode())
                for rr in j.get("results", []):
                    results.append({"city": name, **rr})
            except Exception as e:
                errors.append({"city": name, "error": str(e)[:100]})
        return {"total": len(results), "results": results, "errors": errors,
                "files": [r["video"] for r in results]}
    except Exception as e:
        raise HTTPException(502, f"전체 생성 실패: {e}")

@router.get("/all-status")
def all_status():
    """저장된 전체 숏폼 파일 목록 (진행상황 확인용)"""
    import glob
    files = sorted(glob.glob(f"{OUTDIR}/*.mp4"), key=os.path.getmtime, reverse=True)
    return {"count": len(files), "files": [os.path.basename(f) for f in files[:30]]}

@router.get("/download/{name}")
def download(name: str):
    for base in [OUTDIR, WORK]:
        path = f"{base}/{name}"
        if os.path.exists(path):
            return FileResponse(path, media_type="video/mp4", filename=name)
    raise HTTPException(404, "파일 없음")
