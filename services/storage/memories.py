"""记忆系统的数据库操作（active / short_term / archived 状态流转）。"""

from __future__ import annotations

import time

from services.storage.database import get_db


def add(user_id: str, group_id: str, fact: dict[str, str]) -> None:
    """添加一条新记忆（status='active'）。重复内容自动忽略。"""
    subject_id = str(fact.get("subject_id", user_id))
    source_id = str(fact.get("source_id", user_id))
    content = fact.get("content", "")
    if not isinstance(content, str):
        content = str(content)

    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO memories (subject_id, source_id, group_id, content, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (subject_id, source_id, group_id, content, time.time()),
        )


def get_for_context(user_id: str, limit: int = 20) -> list[str]:
    """获取用于聊天上下文的记忆（active + short_term）。
    V4.0: 只要是关于 user_id(subject_id) 的信息就都能看到，不仅是自己说的。
    """
    with get_db() as db:
        rows = db.execute(
            "SELECT content FROM memories "
            "WHERE subject_id = ? AND status IN ('active', 'short_term') "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [r["content"] for r in rows]


def get_active_details(user_id: str) -> list[dict]:
    """获取所有 active 记忆的完整信息（用于 Cyber Echo 巩固）。"""
    with get_db() as db:
        rows = db.execute(
            "SELECT memory_id as id, content, created_at as timestamp FROM memories "
            "WHERE subject_id = ? AND status = 'active' "
            "ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_status(memory_ids: list[int], new_status: str) -> None:
    """批量更新记忆状态。"""
    if not memory_ids:
        return
    with get_db() as db:
        placeholders = ",".join("?" * len(memory_ids))
        db.execute(
            f"UPDATE memories SET status = ? WHERE memory_id IN ({placeholders})",
            (new_status, *memory_ids),
        )


def prune_expired(retention_hours: int = 24) -> int:
    """清理过期的 short_term 记忆（→ archived），返回清理数量。"""
    expiry = time.time() - retention_hours * 3600
    with get_db() as db:
        cur = db.execute(
            "UPDATE memories SET status = 'archived' "
            "WHERE status = 'short_term' AND created_at < ?",
            (expiry,),
        )
        return cur.rowcount
