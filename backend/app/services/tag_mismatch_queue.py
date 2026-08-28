"""题库错标（岗位/场景）审核队列：LLM 过滤剔除 → 持久化 → 运维定期处理。

默认：SQLite 表 + JSONL 落盘（无需外部中间件）。
可选：配置 ROCKETMQ_* 时同步投递到 RocketMQ Topic（需 pip install rocketmq-client-python）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.tag_mismatch import TagMismatchReview

logger = logging.getLogger("app.tag_mismatch_queue")

_DEDUP_HOURS = 24


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _question_norm(q: str) -> str:
    import re

    return re.sub(r"\W+", "", (q or "").lower())


def _append_jsonl(payload: dict) -> None:
    from pathlib import Path

    log_dir = Path(__file__).resolve().parents[2] / "logs" / "tag_mismatch_queue"
    log_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with open(log_dir / f"{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(line)


def _try_publish_rocketmq(payload: dict) -> str:
    """可选 RocketMQ 投递；未配置或依赖缺失时静默跳过。"""
    namesrv = (settings.rocketmq_namesrv or "").strip()
    topic = (settings.rocketmq_tag_mismatch_topic or "").strip()
    if not namesrv or not topic:
        return ""
    try:
        from rocketmq.client import Message, Producer  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("rocketmq-client-python 未安装，跳过 MQ 投递")
        return ""
    producer = Producer(settings.rocketmq_producer_group or "face-agent-tag-mismatch")
    producer.set_name_server_address(namesrv)
    producer.start()
    try:
        msg = Message(topic)
        msg.set_body(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        msg.set_keys(str(payload.get("question_norm") or "")[:128])
        ret = producer.send_sync(msg)
        return str(getattr(ret, "msg_id", "") or getattr(ret, "offset", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("RocketMQ 投递失败: %s", exc)
        return ""
    finally:
        producer.shutdown()


def enqueue_llm_filtered_hits(
    removed_hits: list[dict],
    *,
    roles: list[str],
    lane: str,
    session_id: int | None = None,
) -> int:
    """将 LLM 岗位/场景过滤剔除的题写入审核队列，返回新入队条数。"""
    if not removed_hits:
        return 0
    since = datetime.now(timezone.utc) - timedelta(hours=_DEDUP_HOURS)
    enqueued = 0
    db: Session = SessionLocal()
    try:
        for h in removed_hits:
            question = str(h.get("question") or "").strip()
            if not question:
                continue
            q_norm = _question_norm(question)
            if not q_norm:
                continue
            dup = db.scalars(
                select(TagMismatchReview)
                .where(
                    TagMismatchReview.question_norm == q_norm,
                    TagMismatchReview.lane == lane,
                    TagMismatchReview.created_at >= since,
                )
                .limit(1)
            ).first()
            if dup:
                continue
            payload = {
                "lane": lane,
                "target_roles": list(roles or []),
                "question": question[:500],
                "question_norm": q_norm,
                "tagged_roles": list(h.get("roles") or []),
                "tagged_scenes": list(
                    (h.get("business_scene") or []) + (h.get("tech_scene") or [])
                ),
                "company": h.get("company"),
                "category": h.get("category"),
                "filter_reason": "llm_rejected",
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            mq_id = _try_publish_rocketmq(payload)
            row = TagMismatchReview(
                status="pending",
                lane=lane,
                target_roles=_json_dumps(payload["target_roles"]),
                question=question[:500],
                question_norm=q_norm,
                tagged_roles=_json_dumps(payload["tagged_roles"]),
                tagged_scenes=_json_dumps(payload["tagged_scenes"]),
                company=str(h.get("company") or "")[:64],
                category=str(h.get("category") or "")[:32],
                filter_reason="llm_rejected",
                session_id=session_id,
                mq_message_id=mq_id,
            )
            db.add(row)
            db.flush()
            payload["id"] = row.id
            payload["mq_message_id"] = mq_id
            _append_jsonl(payload)
            enqueued += 1
        db.commit()
        if enqueued:
            logger.info(
                "tag_mismatch enqueued=%s lane=%s session_id=%s",
                enqueued,
                lane,
                session_id,
            )
            try:
                from app.services.feishu_notify import maybe_notify_tag_mismatch_batch

                maybe_notify_tag_mismatch_batch(db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tag_mismatch feishu alert skipped: %s", exc)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return enqueued


def pending_count(db: Session) -> int:
    from sqlalchemy import func

    return int(
        db.scalar(
            select(func.count())
            .select_from(TagMismatchReview)
            .where(TagMismatchReview.status == "pending")
        )
        or 0
    )
