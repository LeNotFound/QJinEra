"""用户信息的数据库操作。"""

from __future__ import annotations

import time

from services.storage.database import get_db


async def get(group_id: str, user_id: str) -> dict | None:
    """获取用户信息，不存在则返回 None。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id, group_id, nickname, description, "
            "interaction_count, last_active_time, intimacy_score, relationship_stage, "
            "dynamic_status, current_mood "
            "FROM users WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert(group_id: str, user_id: str, nickname: str, timestamp: float) -> None:
    """创建或更新用户记录（互动计数 +1）。"""
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users (user_id, group_id, nickname, interaction_count, last_active_time)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_id, group_id) DO UPDATE SET
                nickname = excluded.nickname,
                interaction_count = users.interaction_count + 1,
                last_active_time = excluded.last_active_time
            """,
            (user_id, group_id, nickname, timestamp),
        )


async def update_description(group_id: str, user_id: str, description: str) -> None:
    """更新用户画像。"""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET description = ? WHERE group_id = ? AND user_id = ?",
            (description, group_id, user_id),
        )


async def update_status_and_mood(
    group_id: str,
    user_id: str,
    dynamic_status: str | None = None,
    current_mood: str | None = None,
) -> None:
    """更新用户的动态体征和心理状态。若记录尚不存在则自动插入。"""
    updates = []
    params = []
    if dynamic_status is not None:
        updates.append("dynamic_status = ?")
        params.append(dynamic_status)
    if current_mood is not None:
        updates.append("current_mood = ?")
        params.append(current_mood)
    if not updates:
        return
    params.extend([group_id, user_id])
    async with get_db() as db:
        cursor = await db.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE group_id = ? AND user_id = ?",
            params,
        )
        if cursor.rowcount == 0:
            now = time.time()
            await db.execute(
                """
                INSERT INTO users (group_id, user_id, dynamic_status, current_mood, last_active_time)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    dynamic_status = CASE WHEN excluded.dynamic_status != '' THEN excluded.dynamic_status ELSE users.dynamic_status END,
                    current_mood = CASE WHEN excluded.current_mood != '' THEN excluded.current_mood ELSE users.current_mood END
                """,
                (group_id, user_id, dynamic_status or "", current_mood or "", now),
            )
