"""话题与消息的数据库操作。"""

from __future__ import annotations

import json

from models.message import MessageContent
from services.storage.database import get_db


async def create(group_id: str, start_time: float) -> int:
    """创建新话题，返回 topic_id。"""
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO topics (group_id, start_time) VALUES (?, ?)",
            (group_id, start_time),
        )
        return cur.lastrowid


async def update_summary(topic_id: int, summary: str, end_time: float | None = None) -> None:
    """更新话题摘要，可选设置结束时间。"""
    async with get_db() as db:
        if end_time is not None:
            await db.execute(
                "UPDATE topics SET summary = ?, end_time = ? WHERE id = ?",
                (summary, end_time, topic_id),
            )
        else:
            await db.execute(
                "UPDATE topics SET summary = ? WHERE id = ?",
                (summary, topic_id),
            )


async def add_message(
    topic_id: int,
    user_id: str,
    content: MessageContent | dict | str | None,
    timestamp: float,
    nickname: str = "",
) -> None:
    """记录一条消息。"""
    if isinstance(content, MessageContent):
        content_str = content.to_json()
    elif isinstance(content, dict):
        content_str = json.dumps(content, ensure_ascii=False)
    elif content is None:
        content_str = ""
    else:
        content_str = str(content)

    async with get_db() as db:
        await db.execute(
            "INSERT INTO messages (topic_id, user_id, nickname, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (topic_id, user_id, nickname, content_str, timestamp),
        )


async def get_recent(group_id: str, limit: int = 5) -> list[dict]:
    """获取最近有摘要的话题列表。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, summary, start_time, end_time FROM topics "
            "WHERE group_id = ? AND summary IS NOT NULL "
            "ORDER BY start_time DESC LIMIT ?",
            (group_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_latest_active(group_id: str) -> dict | None:
    """获取最新的话题（含消息列表）。调用方判断是否过期。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, start_time, end_time, summary FROM topics "
            "WHERE group_id = ? ORDER BY start_time DESC LIMIT 1",
            (group_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        topic_id = row["id"]
        cursor_msgs = await db.execute(
            "SELECT user_id, nickname, content, timestamp FROM messages "
            "WHERE topic_id = ? ORDER BY timestamp ASC",
            (topic_id,),
        )
        messages = await cursor_msgs.fetchall()

        msg_list = []
        for m in messages:
            m_dict = dict(m)
            raw_content = m_dict["content"]
            m_dict["content"] = MessageContent.from_json(raw_content)
            msg_list.append(m_dict)

        return {
            "topic_id": topic_id,
            "start_time": row["start_time"],
            "last_msg_time": msg_list[-1]["timestamp"] if msg_list else row["start_time"],
            "messages": msg_list,
            "summary": row["summary"],
        }


async def get_all_known_groups() -> list[str]:
    """获取数据库中所有已知的群组 ID。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT DISTINCT group_id FROM topics "
            "UNION SELECT DISTINCT group_id FROM users",
        )
        rows = await cursor.fetchall()
        return [r["group_id"] for r in rows if r["group_id"]]


async def close_stale(group_id: str, threshold: float) -> int:
    """关闭所有过期的活跃话题，返回关闭数量。"""
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE topics
            SET end_time = (
                SELECT COALESCE(MAX(timestamp), topics.start_time)
                FROM messages WHERE messages.topic_id = topics.id
            )
            WHERE group_id = ?
              AND end_time IS NULL
              AND (
                  SELECT COALESCE(MAX(timestamp), topics.start_time)
                  FROM messages WHERE messages.topic_id = topics.id
              ) < ?
            """,
            (group_id, threshold),
        )
        return cur.rowcount
