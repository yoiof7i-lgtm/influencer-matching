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

def _is_avatar_img(path):
    """trip.com 기본 아바타(흰 배경+단색 보라/파랑 실루엣 사람) 픽셀 검사 — URL 키워드 필터 우회분 차단"""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((100, 100))
        px = list(im.getdata())
        n = len(px)
        white = sum(1 for p in px if min(p) > 225)
        # 실루엣 색: 흰 배경 외 나머지 픽셀의 색상(hue)이 한 부류에 집중되면 아바타
        # (보라·파랑·노랑·회색 등 어떤 실루엣 색이든 잡음)
        from colorsys import rgb_to_hsv
        fg = [p for p in px if min(p) <= 225]  # 흰 배경 아닌 픽셀 = 실루엣 후보
        if white > 0.25 and 0.10 < len(fg) / n < 0.65:
            hues = {}
            for r, g, b in fg:
                mx, mn = max(r, g, b), min(r, g, b)
                if mx - mn < 25:  # 무채색 → 아바타 판정 대상 아님 (밤 풍경 사진 보호)
                    continue
                h, s, v = rgb_to_hsv(r / 255, g / 255, b / 255)
                hues[int(h * 12)] = hues.get(int(h * 12), 0) + 1  # 30도 단위 부류
            colored = sum(hues.values())
            if colored > len(fg) * 0.5:  # 채색 실루엣이 실루엣의 절반 이상
                dominant = max(hues.values()) / colored if colored else 0
                if dominant > 0.75:  # 채색의 75% 이상이 같은 색 부류 = 단색 실루엣
                    return True
        # 극단: 전체가 거의 한 가지 색 (완전 단색 이미지)
        colors = len(set((r // 24, g // 24, b // 24) for r, g, b in px))
        if colors < 6:
            return True
        return False
    except Exception:
        return False

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
        t = t.replace("%", "%%")   # drawtext의 % 확장 방지
        t = t.replace(":", "\\:")  # drawtext 옵션 구분자 이스케이프
        return t.replace("'", "\\'")
    # 하단 자막 제거 (주인님 지시 — 훅+CTA만 표시)
    # 훅 타이틀: 첫 장면(idx=0)에 상단 큰 제목
    if hook_title:
        vf += (
            f",drawtext=text='{esc(hook_title)}'{fontarg}"
            ":fontcolor=white:fontsize=64:box=1:boxcolor=black@0.55:boxborderw=22"
            ":x=(w-tw)/2:y=h*0.12"
        )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-t", str(dur),
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "fast",
         "-crf", "16", "-profile:v", "high", "-pix_fmt", "yuv420p", out_path],
        capture_output=True, timeout=180)
    return out_path if os.path.exists(out_path) else None

def _user_bgm(dur):
    """주인님 자작 음악 우선: /code/bgm/에 mp3 있으면 앞 dur초 잘라 반환"""
    import glob as _g
    files = _g.glob("/code/bgm/*.mp3") + _g.glob("/code/bgm/*.wav") + _g.glob("/code/bgm/*.m4a")
    return files[0] if files else None

def _bgm(path, dur):
    """1순위: 주인님 자작 음악 (bgm 폴더) → 없으면 사인 코드 생성"""
    # Am→F→C→G 진행 느낌: 주파수 교차 페이드 (단순 합성)
    try:
        # 자작 음악이 있으면 그걸로 (앞부분 35초 컷 + 페이드)
        src = _user_bgm(dur)
        if src:
            subprocess.run(["ffmpeg", "-y", "-i", src, "-t", str(dur),
                            "-af", f"volume=0.5,afade=t=in:d=1.5,afade=t=out:st={dur-2.5}:d=2.5",
                            "-c:a", "pcm_s16le", path],
                           capture_output=True, timeout=60)
            if os.path.exists(path) and os.path.getsize(path) > 10000:
                return True
    except Exception:
        pass
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

def _overlay_cta(video_path, out_path, region, total_dur, discount=0):
    """훅(처음부터) + 50%부터 할인CTA + 깜빡임"""
    t0 = 0.0
    last5 = total_dur * 0.5
    font = ""
    for cand in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"]:
        if os.path.exists(cand):
            font = cand
            break
    fa = f":fontfile={font}" if font else ""
    def esc(t):
        t = t.replace("%", "%%")   # drawtext % 확장 방지
        t = t.replace(":", "\\:")   # 옵션 구분자 이스케이프
        return t.replace("'", "\\'")
    hook = f"{region} 호캉스 이 정도까지 가능?"
    vf = (
        # 80%부터 끝까지: 큰 훅문구 (상단 15%)
        f"drawtext=text='{esc(hook)}'{fa}"
        f":fontcolor=white:fontsize=76"
        f":borderw=5:bordercolor=black"
        f":x=(w-tw)/2:y=h*0.14"
        f":enable='gte(t,{t0:.2f})'"
    )
    # 50%부터: 할인 + CTA (깜빡임: 0.6초 주기 점멸)
    if last5 > 0:
        if discount and discount > 1:
            disc_line = f"오늘 특별 {discount}％ 할인"   # % 숫자 있는 실할인 (전각％ — drawtext 이슈 회피)
        else:
            disc_line = "오늘 특별 할인 진행 중"          # disc=1 플래그(특별할인 태그) 또는 할인 미상
        vf += (
            f",drawtext=text='{esc(disc_line)}'{fa}"
            f":fontcolor=yellow:fontsize=54"
            f":borderw=4:bordercolor=black"
            f":x=(w-tw)/2:y=h*0.22"
            f":enable='gte(t,{t0:.2f})'"
            f",drawtext=text='위치 궁금하신 분들은'{fa}"
            f":fontcolor=white:fontsize=44"
            f":borderw=3:bordercolor=black"
            f":x=(w-tw)/2:y=h*0.29"
            f":enable='gte(t,{last5:.2f})'"
            f",drawtext=text='「{region} 호캉스」 라고'{fa}"
            f":fontcolor=yellow:fontsize=54"
            f":borderw=4:bordercolor=black"
            f":x=(w-tw)/2:y=h*0.36"
            f":alpha='if(lt(mod(t,0.6),0.35),1,0)'"
            f":enable='gte(t,{last5:.2f})'"
            f",drawtext=text='댓글로 남겨주세요. 할인링크 보내드려요.'{fa}"
            f":fontcolor=white:fontsize=40"
            f":borderw=3:bordercolor=black"
            f":x=(w-tw)/2:y=h*0.43"
            f":enable='gte(t,{last5:.2f})'"
        )
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-profile:v", "high",
                    "-c:a", "copy", out_path], capture_output=True, timeout=300)
    return out_path if os.path.exists(out_path) else None

def _linkprice_deeplink(detail_url: str) -> str:
    """trip.com 호텔 상세 URL → 링크프라이스 제휴 딥링크 (정식 click.php 방식)
    실측 확정 (2026-10-17): click.linkprice.com/click.php에 tu=호텔URL만 넣으면
    LP 서버가 p_id를 동적으로 자동 발급해 lpinfo로 리다이렉트시킨다.
    파트너 계정(a=A100632782) 고정 — 수익 귀속 확정."""
    if not detail_url:
        return ""
    import urllib.parse as _up
    # 호텔 상세 URL 표준화 (체크인/통화/locale 기본값 보강)
    if "checkIn=" not in detail_url:
        detail_url += ("&" if "?" in detail_url else "?") + "checkIn=2026-10-20&checkOut=2026-10-21"
    if "locale=" not in detail_url:
        detail_url += "&curr=KRW&barcurr=KRW&locale=ko-KR"
    return (f"https://click.linkprice.com/click.php?m=ctrip&a=A100632782&l=9999"
            f"&l_cd1=3&l_cd2=q&tu={_up.quote(detail_url, safe='')}")

def _lp_shortlink(deeplink: str) -> str:
    """딥링크 → 숏링크. 실측: TinyURL·is.gd는 linkprice 도메인을 스팸필터로 거부(400/db error).
    spoo.me는 허용 + 리다이렉트 검증 완료 (click.php → lpinfo 정상 도달)."""
    if not deeplink:
        return ""
    try:
        import urllib.parse as _up
        data = _up.urlencode({"url": deeplink}).encode()
        req = urllib.request.Request("https://spoo.me/", data=data,
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        r = urllib.request.urlopen(req, timeout=15)
        j = json.loads(r.read().decode())
        short = j.get("short_url", "")
        if short.startswith("http"):
            return short
    except Exception:
        pass
    # 폴백: TinyURL (linkprice 아닌 URL용)
    try:
        import urllib.parse as _up
        api = "https://tinyurl.com/api-create.php?url=" + _up.quote(deeplink, safe='')
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        short = urllib.request.urlopen(req, timeout=15).read().decode().strip()
        if short.startswith("http"):
            return short
    except Exception:
        pass
    return ""

def _make_impl(url, count, city, script, photo_urls, hook, region):
    """make 본체 (기존 로직) — 결과 dict 반환"""
    import shutil
    try:
        return _make_body(url, count, city, script, photo_urls, hook, region)
    except HTTPException as e:
        return {"error": e.detail}
    except Exception as e:
        return {"error": f"자동생성 실패: {e}"}

@router.get("/make")
def make(url: str, count: int = Query(1, ge=1, le=5), city: str = Query(None), script: str = Query(None), photo_urls: str = Query(None), hook: str = Query(None), region: str = Query(None), bg: int = Query(0)):
    if bg:
        import threading
        t = threading.Thread(target=_make_impl, args=(url, count, city, script, photo_urls, hook, region), daemon=True)
        t.start()
        return {"started": True, "poll": "/autoshorts/all-status"}
    return _make_impl(url, count, city, script, photo_urls, hook, region)

def _make_body(url: str, count: int, city: str, script: str, photo_urls: str, hook: str, region: str):
    try:
        import shutil
        shutil.rmtree(WORK, ignore_errors=True)
        os.makedirs(WORK, exist_ok=True)

        # 1) 호텔 수집 (URL 디코드 — %3A 등 인코딩 상태로 전달됨)
        import urllib.parse as _up
        url_dec = _up.unquote(url)
        m = re.search(r'city=(\d+)', url_dec)
        city_code = city or (m.group(1) if m else "623")
        hotels = list_hotels(city_code, count=count)
        print(f"[make] city_code={city_code}, hotels={[(x['name'][:12], x.get('discount')) for x in hotels]}", flush=True)
        if not hotels:
            print(f"[make] city_code={city_code}: hotels=0 (trip.com 응답 없음)", flush=True)
            return {"error": "호텔을 찾지 못했습니다"}

        results = []
        for rank, h in enumerate(hotels):
            # 할인 있는 호텔 우선 — 할인 0도 포함 (지역 선택 시 결과 0개 방지)
            # 2) 사진 14장 수집·다운로드 (프론트 AI 선별 순서 우선)
            if photo_urls:
                photos = [u for u in photo_urls.split("|") if u.startswith("http")][:14]
            else:
                photos = hotel_photos(h["id"], limit=25)
            if len(photos) < 7:
                print(f"[make] {h.get('name','?')[:12]}: photos={len(photos)} < 7 skip", flush=True)
                continue
            dl = []
            skipped_avatar = 0
            for i, pu in enumerate(photos):
                try:
                    # 1i5 접두사 = 리뷰어 아바타 (주인님 실측 확정) — 하드 차단
                    m5 = re.search(r'/images/(1i5)', pu)
                    if m5:
                        skipped_avatar += 1
                        continue
                    p = _dl(pu, f"{WORK}/h{rank}_p{i}.jpg")
                    if _is_avatar_img(p):  # 아바타/플레이스홀더 픽셀 검사 (보조)
                        skipped_avatar += 1
                        os.remove(p)
                        continue
                    dl.append(p)
                except Exception:
                    pass
            print(f"[make] {h['name'][:12]}: photos={len(photos)} dl={len(dl)} avatar_skip={skipped_avatar}", flush=True)
            if len(dl) < 7:
                print(f"[make] {h.get('name','?')[:12]}: dl={len(dl)} < 7 skip", flush=True)
                continue
            NCLIP = len(dl)

            # 3) AI 대본 (사진 이해)
            b64s = []
            for pth in dl:
                b64s.append(base64.b64encode(open(pth, "rb").read()).decode())
            script_raw = script if script else None
            if not script_raw:
                # 서버 AI 호출 제거 (크래시 회피 + 토큰 절감) — 규칙 기반 자연 문구
                dn = h.get("discount", 0)
                disc_txt = f"{dn}% 할인" if (dn and dn > 1) else "특별 할인"  # 1=플래그 → %표기 금지
                hook2 = hook or f"{region} 호캉스 이 정도까지 가능?"
                narrations = [
                    f"{region} 호캉스 이 정도까지 가능?",
                    f"오늘 특별 {disc_txt} 중이에요",
                    "침대에서 바로 보이는 뷰가 끝판왕",
                    "욕실까지 깔끔하게 관리되어 있어요",
                    "수영장과 자쿠지까지 다 갖췄어요",
                    "건물도 새것이라 쾌적해요",
                    "전망은 말 안 해도 알겠죠?",
                    "조식까지 챙겨주니 뭐가 더 필요해요",
                    "위치도 나쁘지 않아요",
                    "가족 여행에 딱이에요",
                    "커플 여행에도 최고예요",
                    "예약 전 꼼꼼히 확인해보세요",
                    f"{region}에서 이 가격이면 지는 거예요",
                    "궁금하시면 저장하고 가세요",
                ]
                captions = [
                    "훅", "할인", "룸 뷰", "욕실", "수영장", "건물", "전망",
                    "조식", "위치", "가족", "커플", "체크포인트", "가성비", "저장"
                ]
                title = f"{region} 호캉스 {disc_txt} 숙소"
                narrations = narrations[:NCLIP]
                captions = captions[:NCLIP]
                script_raw = None
            else:
                script_raw = None
            NPH = NCLIP
            narrations = ["최고의 호텔을 소개합니다"] * NCLIP
            captions = [""] * NCLIP
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
            while len(narrations) < NCLIP and fi < len(FILL_N):
                narrations.append(FILL_N[fi]); captions.append(FILL_C[fi] if fi < len(FILL_C) else ""); fi += 1
            while len(narrations) < NCLIP:
                narrations.append("여행에 딱 맞는 숙소예요"); captions.append("여행 추천")

            # 4) 음성 제거 (주인님 지시) — 영상 길이는 고정 14×2.5+전환 보정
            has_voice = False
            V = 35.0  # 음성 제거 — 고정 35초 기준 (클립당 2.87초)
            XFADE = 0.4
            # 클립당 길이: 크로스페이드 겹침(13회) 보정해서 최종길이 = 음성길이
            clip_dur = (V + 13 * XFADE) / 14
            clip_dur = max(1.8, min(clip_dur, 4.5))  # 상식 범위 (너무 짧/길면 캡)
            # 최종 예상 길이 = clip_dur*14 - 13*0.4

            # 5) 사진 모션 클립 (동적 길이, 자막+훅)
            clips = []
            for i in range(NCLIP):
                cap = (captions[i] if i < len(captions) else "") or (narrations[i] if i < len(narrations) else "")
                c = _motion_clip(dl[i], f"{WORK}/h{rank}_c{i}.mp4", clip_dur, cap, idx=i,
                                 hook_title=hook if i == 0 else "")
                if c: clips.append(c)
            print(f"[make] {h.get('name','?')[:12]}: clips 생성={len(clips)}/{NCLIP}", flush=True)
            if len(clips) < 7:
                print(f"[make] {h.get('name','?')[:12]}: clips={len(clips)} < 7 skip", flush=True)
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
                                "-map", "[vout]", "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high",
                                merged], capture_output=True, timeout=420)
            else:
                subprocess.run(["ffmpeg", "-y", "-i", clips[0], "-c:v", "libx264", merged],
                               capture_output=True, timeout=120)
            # 7) BGM만 + CTA 오버레이 (음성 없음 — 주인님 지시)
            final = f"{WORK}/h{rank}_final.mp4"
            bgm = f"{WORK}/h{rank}_bgm.wav"
            has_bgm = _bgm(bgm, V if V > 0 else 30)
            if has_bgm:
                r = subprocess.run(["ffmpeg", "-y", "-i", merged, "-i", bgm,
                                "-map", "0:v", "-map", "1:a", "-shortest",
                                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", final],
                               capture_output=True, timeout=180)
                if r.returncode != 0 or not os.path.exists(final):
                    import shutil as _sh; _sh.copy(merged, final)
            else:
                import shutil as _sh; _sh.copy(merged, final)
            # 8) CTA 오버레이 (80% 위치 훅 + 마지막 5초 깜빡임 CTA)
            total_dur = clip_dur * 14 - 13 * 0.4
            region = region or h.get("region") or ""
            final2 = _overlay_cta(final, f"{WORK}/h{rank}_cta.mp4", region, total_dur, discount=h.get("discount", 0))
            if final2:
                import shutil as _sh2; _sh2.copy(final2, final)

            # 링크프라이스 딥링크 → 숏링크 변환 (주인님 지시)
            lp_deeplink = _linkprice_deeplink(h.get("detail_url", ""))
            lp_shortlink = _lp_shortlink(lp_deeplink) if lp_deeplink else ""

            safe_name = re.sub(r'[^가-힣a-zA-Z0-9]', '_', title)[:20]
            out_name = f"{safe_name}_숏폼.mp4"
            results.append({
                "rank": rank+1, "hotel": h["name"], "title": title,
                "score": h["score"], "reviews": h["reviews"], "discount": h.get("discount", 0),
                "video": out_name,
                "narrations": narrations,
            })
            # 윈도우에서 바로 볼 수 있는 폴더에 저장
            import shutil as _sh2
            os.makedirs(OUTDIR, exist_ok=True)
            _sh2.copy(final, f"{OUTDIR}/{out_name}")
            # 캡션: 별도 AI 호출 제거 (토큰 절감) — 대본에서 자동 조합
            cap_txt = f"{region or ''} 호캉스 이 정도까지 가능? {narrations[0] if narrations else ''} {narrations[1] if len(narrations)>1 else ''} 지금 저장하고 가세요!"
            tags = [f"#{region or '제주'}여행", f"#{region or '제주'}호캉스", "#호텔추천", "#숙소추천",
                    "#가성비호텔", "#여행스타그램", "#국내여행", "#호캉스", "#오션뷰", "#리조트",
                    f"#{region or '제주'}숙소", "#여행꿀팁"]
            with open(f"{OUTDIR}/{safe_name}_대본.txt", "w", encoding="utf-8") as tf:
                tf.write(f"호텔: {h['name']} (평점 {h['score']}, {h['reviews']})\n제목: {title}\n\n")
                for i, (nn, cc) in enumerate(zip(narrations, captions)):
                    tf.write(f"[{i+1}] {nn}\n    자막: {cc}\n")
                tf.write("\n═══ 인스타 릴스 게시물 (아래 복붙) ═══\n\n")
                tf.write(f"{cap_txt}\n\n")
                tf.write(" ".join(tags))
                tf.write(f"\n═══ 예약 링크 (링크프라이스 제휴 — 댓글/프로필용) ═══\n\n")
                if lp_shortlink:
                    tf.write(f"[숏링크] {lp_shortlink}\n")
                if lp_deeplink:
                    tf.write(f"[LP딥링크] {lp_deeplink}\n")
                # 원본 상세 URL은 항상 저장 (LP 사이트에서 수동 딥링크 변환용)
                tf.write(f"[호텔URL] https://kr.trip.com/hotels/detail/?hotelId={h['id']}\n")
                if not lp_shortlink and not lp_deeplink:
                    tf.write("※ 위 호텔URL을 링크프라이스 딥링크 변환기에 넣으면 제휴 링크 생성\n")
                tf.write(f"\n═══ \n[영상] {out_name} / 35초 1080x1920 / 바로 릴스 업로드 가능\n")

        if not results:
            raise HTTPException(502, "할인 중인 호텔이 없어 생성 못함 (나중에 다시)")
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
        import urllib.parse as _up

        results = []
        errors = []
        for n, c in uniq:
            q = _up.quote(f"https://kr.trip.com/hotels/list?city={c}&checkin=2026-10-20&checkout=2026-10-21", safe='')
            u = f"http://localhost:8000/autoshorts/make?url={q}&count={count_per_city}&region={_up.quote(n)}"
            if hook:
                u += "&hook=" + _up.quote(hook)
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "internal"})
                r = urllib.request.urlopen(req, timeout=560)
                j = json.loads(r.read().decode())
                for rr in j.get("results", []):
                    results.append({"city": n, **rr})
                print(f"[all] {n}: {len(j.get('results', []))}개 생성", flush=True)
            except Exception as e:
                errors.append({"city": n, "error": str(e)[:100]})
                print(f"[all] {n}: 실패 - {e}", flush=True)
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
