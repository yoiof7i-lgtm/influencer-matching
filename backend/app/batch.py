"""배치 작업 — 후기 링크 미제출 → 협찬OFF 자동 처리
실행: python -m app.batch  (또는 docker compose exec backend python -m app.batch)

규칙 (협찬ON 기획서):
- 방문 완료(visit_done)된 매칭에서 인플루언서의 후기 링크 미제출
- 미제출 3개 → 협찬OFF (is_active=False)
- 미제출 2개 이하 → ON 복귀 가능
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Match, Review
from app.database import DATABASE_URL

KST = timezone(timedelta(hours=9))
PENDING_LIMIT = 3  # 미제출 3개 → OFF


def run():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    influencers = db.query(User).filter(User.role == "influencer").all()
    turned_off, turned_on = [], []

    for inf in influencers:
        # 방문 완료됐는데 후기 링크 없는 매칭 수
        done = (
            db.query(Match)
            .filter(Match.influencer_id == inf.id, Match.status == "visit_done")
            .all()
        )
        missing = 0
        for m in done:
            has_review = (
                db.query(Review)
                .filter(Review.match_id == m.id, Review.reviewer_id == inf.id)
                .first()
            )
            if not has_review:
                missing += 1

        if missing >= PENDING_LIMIT and inf.is_active:
            inf.is_active = False
            inf.review_pending = missing
            turned_off.append((inf.name, missing))
        elif missing < PENDING_LIMIT and not inf.is_active and inf.review_pending:
            # 후기 제출로 미제출이 2개 이하가 되면 ON 복귀
            inf.is_active = True
            inf.review_pending = missing
            turned_on.append((inf.name, missing))

    db.commit()
    db.close()

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] 후기 미제출 배치 완료")
    for name, n in turned_off:
        print(f"  🚫 OFF 전환: {name} (미제출 {n}개 ≥ {PENDING_LIMIT})")
    for name, n in turned_on:
        print(f"  ✅ ON 복귀: {name} (미제출 {n}개 < {PENDING_LIMIT})")
    if not turned_off and not turned_on:
        print("  변경 없음")


if __name__ == "__main__":
    run()