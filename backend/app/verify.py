"""검증 모듈 — 인스타 활성화 확인 + 사업자등록번호 진위확인
협찬ON 도메인 규칙:
1. 인플루언서 가입 시 인스타 활성화 계정 확인 (비활성/삭제된 계정은 가입 불가)
2. 사장님 가입 시 사업자등록번호 진위확인 (국세청 API)
"""
import re
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import time


# ────────────────────────────────────────────────
# 1. 인스타그램 활성화 확인
# ────────────────────────────────────────────────
def check_instagram(handle: str) -> dict:
    """인스타 handle 확인.

    입력값 자동 정리: URL 붙여넣기(https://instagram.com/xxx), @포함, 공백 처리
    1차: 프로필 페이지 HTML에서 계정 마커(@handle) 검색 — 유명계정/공개계정 일부 성공
    2차: 인스타 로그인 벽으로 자동 판별 불가 시 → '수동확인' 상태 반환
    """
    handle = (handle or "").strip().lstrip("@").strip()
    # URL로 입력한 경우 handle만 추출: instagram.com/HANDLE 또는 instagr.am/HANDLE
    m = re.search(r"(?:instagram\.com|instagr\.am)/([A-Za-z0-9._]+)", handle)
    if m:
        handle = m.group(1)
    handle = handle.replace(" ", "")  # 공백 제거
    if not handle:
        return {"valid": False, "reason": "인스타그램 계정을 입력해주세요"}
    if not re.fullmatch(r"[a-zA-Z0-9._]{1,30}", handle):
        return {"valid": False,
                "reason": f"'{handle}' 은 인스타 계정명이 아닙니다 — 인스타 아이디(영문/숫자/._)를 입력해주세요 (예: sopoongjeju)"}

    url = f"https://www.instagram.com/{handle}/"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko,en;q=0.9",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        body = resp.read(1500000).decode("utf-8", errors="ignore")
        low = body.lower()
        # 팔로워 수 추출 (og:description: "N Followers, M Following, K Posts")
        import re as _re
        m_fol = _re.search(r'([\d,]+)\s*Followers', body)
        followers = int(m_fol.group(1).replace(",", "")) if m_fol else None
        # 계정 존재 마커: @handle / HTML엔티티 &#064;handle / 유니코드 ＠handle
        for marker in (f"@{handle.lower()}", f"&#064;{handle.lower()}",
                       f"＠{handle.lower()}"):
            if marker in low:
                return {"valid": True, "verified": True,
                        "followers": followers,
                        "reason": f"@{handle} 실존 계정 확인"
                                  + (f" (팔로워 {followers:,})" if followers else "")}
        # HTML 분석 실패 = 로그인 벽 → 자동판별 불가, 수동확인으로 통과
        return {"valid": True, "verified": False,
                "reason": "자동확인 불가 — 운영자 확인 후 승인 예정"}
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return {"valid": False, "reason": f"@{handle} 계정을 찾을 수 없습니다 (삭제/비활성)"}
        return {"valid": True, "verified": False,
                "reason": "자동확인 불가 — 운영자 확인 후 승인 예정"}
    except Exception:
        return {"valid": True, "verified": False,
                "reason": "자동확인 실패 — 운영자 확인 후 승인 예정"}


# ────────────────────────────────────────────────
# 2. 사업자등록번호 진위확인 (국세청)
# ────────────────────────────────────────────────
# 환경변수 NTS_API_KEY (국세청 사업자 상태조회 서비스 키) 필요
NTS_API_KEY = os.getenv("NTS_API_KEY", "")
NTS_STATUS_URL = "https://api.odcloud.kr/api/nts-businessman/v1/status"


def _clean_bno(bno: str) -> str:
    return re.sub(r"\D", "", bno or "")


def check_business_number(bno: str) -> dict:
    """사업자번호 확인.

    1차: 형식 검증 (숫자 10자리) — 체크섬은 참고만 (오탐으로 진짜 번호를 막으면 안 됨)
    2차: 국세청 실제 조회 (NTS_API_KEY 설정 시) — 폐업/휴업/미등록 차단
    """
    bno = _clean_bno(bno)
    if len(bno) != 10:
        return {"valid": False, "reason": "사업자등록번호는 숫자 10자리입니다"}
    if not bno.isdigit():
        return {"valid": False, "reason": "사업자등록번호는 숫자만 입력해주세요"}

    # 2차: 국세청 실제 조회 (키 있을 때만)
    if not NTS_API_KEY:
        return {"valid": True, "manual": True,
                "reason": "번호 형식 검증 완료 — 실제 상태는 국세청 확인 필요"}

    body = json.dumps({"b_no": [bno]}).encode()
    req = urllib.request.Request(
        NTS_STATUS_URL + f"?serviceKey={urllib.parse.quote(NTS_API_KEY)}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    for _ in range(3):  # 레이트리밋 대비 재시도
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            row = (data.get("data") or [{}])[0]
            state = row.get("tax_type", "")
            if state in ("01", "국세청에 등록되지 않은 사업자등록번호입니다."):
                return {"valid": False, "reason": "국세청에 등록되지 않은 사업자번호입니다"}
            if state == "02":
                return {"valid": False, "reason": "폐업된 사업자번호입니다"}
            if state == "03":
                return {"valid": False, "reason": "휴업 중인 사업자번호입니다"}
            # 정상영업
            return {"valid": True, "reason": "사업자 상태 정상 (국세청 확인)"}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502):
                time.sleep(1.5)
                continue
            return {"valid": False, "reason": f"국세청 조회 실패 (코드 {e.code})"}
        except Exception:
            return {"valid": False, "reason": "국세청 조회 실패 — 네트워크 오류"}
    return {"valid": False, "reason": "국세청 조회 초과 — 잠시 후 다시 시도"}


def _checksum_valid(bno: str) -> bool:
    """사업자등록번호 체크섬 (표준 검증식)"""
    if not bno.isdigit() or len(bno) != 10:
        return False
    weights = [1, 3, 7, 1, 9, 7, 1, 7, 3]
    total = sum(int(d) * w for d, w in zip(bno[:9], weights))
    total += (int(bno[8]) * 5) // 10
    check = (10 - (total % 10)) % 10
    return check == int(bno[9])
def verify_profile_code(handle: str, code: str) -> dict:
    """프로필(소개글/이름)에 인증 코드가 들어갔는지 확인"""
    handle = (handle or "").strip().lstrip("@").strip()
    m = re.search(r"(?:instagram\.com|instagr\.am)/([A-Za-z0-9._]+)", handle)
    if m:
        handle = m.group(1)  # URL 전체로 저장된 경우 handle만 추출
    handle = handle.replace(" ", "")
    code = (code or "").strip()
    if not handle or not code:
        return {"verified": False, "reason": "계정명과 코드가 필요합니다"}
    url = f"https://www.instagram.com/{handle}/"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko,en;q=0.9",
    })
    try:
        body = urllib.request.urlopen(req, timeout=15).read(1500000).decode("utf-8", errors="ignore")
        low = body.lower()
        if code.lower() in low:
            return {"verified": True, "reason": "프로필에서 인증 코드 확인 — 본인 인증 완료"}
        return {"verified": False, "pending_manual": True,
                "reason": "자동 확인 실패 — 운영자가 수동 확인합니다 (수 시간 내 처리)"}
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return {"verified": False, "reason": "계정을 찾을 수 없습니다"}
        # 로그인 벽 → 자동 확인 불가 → 수동 승인 대기로
        return {"verified": False, "wall": True,
                "reason": "인스타 확인 불가(벽) — 운영자가 수동 확인합니다"}
    except Exception:
        return {"verified": False, "wall": True,
                "reason": "확인 실패 — 운영자가 수동 확인합니다"}
