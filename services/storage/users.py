"""用户信息的数据库操作。"""

from __future__ import annotations

from services.storage.database import get_db


def get(group_id: str, user_id: str) -> dict | None:
    """获取用户信息，不存在则返回 None。"""
    with get_db() as db:
        row = db.execute(
            "SELECT user_id, group_id, nickname, description, "
            "interaction_count, last_active_time, intimacy_score, relationship_stage "
            "FROM users WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def upsert(group_id: str, user_id: str, nickname: str, timestamp: float) -> None:
    """创建或更新用户记录（互动计数 +1）。"""
    with get_db() as db:
        row = db.execute(
            "SELECT interaction_count FROM users WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()

        if row:
            db.execute(
                "UPDATE users SET nickname = ?, interaction_count = ?, last_active_time = ? "
                "WHERE group_id = ? AND user_id = ?",
                (nickname, row["interaction_count"] + 1, timestamp, group_id, user_id),
            )
        else:
            db.execute(
                "INSERT INTO users (user_id, group_id, nickname, interaction_count, last_active_time) "
                "VALUES (?, ?, ?, 1, ?)",
                (user_id, group_id, nickname, timestamp),
            )


def update_description(group_id: str, user_id: str, description: str) -> None:
    """更新用户画像。"""
    with get_db() as db:
        db.execute(
            "UPDATE users SET description = ? WHERE group_id = ? AND user_id = ?",
            (description, group_id, user_id),
        )
