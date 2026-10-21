"""记忆系统的数据库操作（active / short_term / archived 状态流转）。"""

from __future__ import annotations

import time

from logger import get_logger
from services.identity import is_bot_self, is_bot_self_memory, resolve_subject_id, sanitize_memory_content
from services.storage.database import get_db

logger = get_logger("MemoriesStorage")


async def add(user_id: str, group_id: str, fact: dict[str, str], bot_id: str = "") -> bool:
    """添加一条新记忆（status='active'）。重复内容自动忽略。拦截机器人自指。"""
    raw_subj = str(fact.get("subject_id", user_id)).strip()
    raw_src = str(fact.get("source_id", user_id)).strip()
    content = str(fact.get("content", "")).strip()

    if not content:
        return False

    # 规范化与反向解析实体
    subject_id = resolve_subject_id(raw_subj, fallback_id=user_id)
    source_id = resolve_subject_id(raw_src, fallback_id=user_id)

    # 守卫：拦截机器人自指与外部化记忆
    if is_bot_self(subject_id, bot_id) or is_bot_self(raw_subj, bot_id) or is_bot_self_memory(content, bot_id):
        logger.warning("拦截机器人自指记忆入库: [subject:%s] %s", subject_id, content)
        return False

    # 净化内容（替换非人化代词与数字 QQ）
    clean_content = sanitize_memory_content(content)

    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO memories (subject_id, source_id, group_id, content, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (subject_id, source_id, group_id, clean_content, time.time()),
        )
    return True


async def get_for_context(user_id: str, group_id: str | None = None, limit: int = 20) -> list[str]:
    """获取用于聊天上下文的记忆（active + short_term）。
    支持群组作用域隐私隔离：若指定 group_id，则私密/专属群（如 soulmate/private）产生的记忆
    仅在其所属群内召回，防止私密小群专属羁绊在普通群/公开群中被检索泄露。
    """
    async with get_db() as db:
        if group_id:
            query = """
                SELECT m.content FROM memories m
                LEFT JOIN groups g ON m.group_id = g.group_id
                WHERE m.subject_id = ? AND m.status IN ('active', 'short_term')
                  AND (
                      m.group_id = ?
                      OR (g.intimacy_level IS NULL OR g.intimacy_level NOT IN ('soulmate', 'private'))
                  )
                ORDER BY m.created_at DESC LIMIT ?
            """
            cursor = await db.execute(query, (user_id, group_id, limit))
        else:
            cursor = await db.execute(
                "SELECT content FROM memories "
                "WHERE subject_id = ? AND status IN ('active', 'short_term') "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        rows = await cursor.fetchall()
        return [r["content"] for r in rows]


async def get_active_details(user_id: str, group_id: str) -> list[dict]:
    """获取所有 active 记忆的完整信息（用于 Cyber Echo 巩固）。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT memory_id as id, content, created_at as timestamp FROM memories "
            "WHERE subject_id = ? AND group_id = ? AND status = 'active' "
            "ORDER BY created_at ASC",
            (user_id, group_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_status(memory_ids: list[int], new_status: str) -> None:
    """批量更新记忆状态。"""
    if not memory_ids:
        return
    async with get_db() as db:
        placeholders = ",".join("?" * len(memory_ids))
        await db.execute(
            f"UPDATE memories SET status = ? WHERE memory_id IN ({placeholders})",
            (new_status, *memory_ids),
        )


async def prune_expired(retention_hours: int = 24) -> int:
    """清理过期的 short_term 记忆（→ archived），返回清理数量。"""
    expiry = time.time() - retention_hours * 3600
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE memories SET status = 'archived' "
            "WHERE status = 'short_term' AND created_at < ?",
            (expiry,),
        )
        return cursor.rowcount


async def forget_by_keyword(group_id: str | None, keyword: str) -> int:
    """根据关键词将活跃记忆标记为已归档（遗忘）。返回处理条数。"""
    clean_kw = keyword.strip()
    if not clean_kw:
        return 0
    escaped = clean_kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    async with get_db() as db:
        if group_id:
            cursor = await db.execute(
                "UPDATE memories SET status = 'archived' "
                "WHERE status IN ('active', 'short_term') "
                "  AND (group_id = ? OR group_id = '') "
                "  AND content LIKE ? ESCAPE '\\'",
                (group_id, f"%{escaped}%"),
            )
        else:
            cursor = await db.execute(
                "UPDATE memories SET status = 'archived' "
                "WHERE status IN ('active', 'short_term') "
                "  AND content LIKE ? ESCAPE '\\'",
                (f"%{escaped}%",),
            )
        return cursor.rowcount


async def delete_by_keyword(group_id: str | None, keyword: str) -> int:
    """根据关键词硬删除记忆。返回删除条数。"""
    clean_kw = keyword.strip()
    if not clean_kw:
        return 0
    escaped = clean_kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    async with get_db() as db:
        if group_id:
            cursor = await db.execute(
                "DELETE FROM memories WHERE (group_id = ? OR group_id = '') AND content LIKE ? ESCAPE '\\'",
                (group_id, f"%{escaped}%"),
            )
        else:
            cursor = await db.execute(
                "DELETE FROM memories WHERE content LIKE ? ESCAPE '\\'",
                (f"%{escaped}%",),
            )
        return cursor.rowcount


async def get_by_keyword(group_id: str | None, keyword: str, limit: int = 20) -> list[dict]:
    """查询包含关键词的记忆（用于 /forget list 预览）。"""
    clean_kw = keyword.strip()
    if not clean_kw:
        return []
    escaped = clean_kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    async with get_db() as db:
        if group_id:
            cursor = await db.execute(
                "SELECT memory_id, subject_id, group_id, content, status, created_at FROM memories "
                "WHERE (group_id = ? OR group_id = '') AND content LIKE ? ESCAPE '\\' "
                "ORDER BY created_at DESC LIMIT ?",
                (group_id, f"%{escaped}%", limit),
            )
        else:
            cursor = await db.execute(
                "SELECT memory_id, subject_id, group_id, content, status, created_at FROM memories "
                "WHERE content LIKE ? ESCAPE '\\' "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{escaped}%", limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
