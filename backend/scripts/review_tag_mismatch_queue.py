"""运维：查看错标审核队列待办（可挂 cron 每日巡检）。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import SessionLocal
from app.models.tag_mismatch import TagMismatchReview
from app.services.tag_mismatch_queue import pending_count
from app.services.system_log import write_log


def main() -> int:
    parser = argparse.ArgumentParser(description="错标审核队列巡检")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--alert-threshold", type=int, default=10)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        pending = pending_count(db)
        rows = db.scalars(
            select(TagMismatchReview)
            .where(TagMismatchReview.status == "pending")
            .order_by(TagMismatchReview.id.desc())
            .limit(args.limit)
        ).all()
        print(f"pending={pending}")
        for r in rows:
            print(
                f"#{r.id} [{r.lane}] roles={r.target_roles[:80]} | {r.question[:72]}"
            )
        if pending >= args.alert_threshold:
            write_log(
                level="warn",
                source="tag_mismatch_queue",
                path="scripts/review_tag_mismatch_queue.py",
                message=f"错标审核待办 {pending} 条，请运维处理",
                detail=json.dumps(
                    [{"id": r.id, "lane": r.lane, "question": r.question[:120]} for r in rows[:5]],
                    ensure_ascii=False,
                ),
            )
            print(f"→ 已写入 system_logs（pending>={args.alert_threshold}）")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
