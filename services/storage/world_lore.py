"""群组世界观设定的数据库操作。"""

from __future__ import annotations

import time

from services.storage.database import get_db


async def add_or_update(group_id: str, source_id: str, entity_name: str, description: str) -> None:
    """插入新设定，若已存在同名实体，则更新描述内容。"""
    now = time.time()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO world_lore (group_id, entity_name, description, source_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id, entity_name) DO UPDATE SET
                description = excluded.description,
                source_id = excluded.source_id,
                updated_at = excluded.updated_at
            """,
            (group_id, entity_name, description, source_id, now, now),
        )


async def get_all(group_id: str) -> list[dict]:
    """获取该群组内所有的世界观设定。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT entity_name, description, source_id, updated_at FROM world_lore "
            "WHERE group_id = ? "
            "ORDER BY updated_at DESC",
            (group_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


def _escape_like(s: str) -> str:
    """转义 SQLite LIKE 中的通配符 (% 和 _) 及转义符 (\\)。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_by_entities(group_id: str, entity_names: list[str]) -> dict[str, list[dict]]:
    """根据 Judge 模型提取的实体列表，获取精确匹配和模糊匹配的设定。"""
    cleaned_names = [e.strip() for e in entity_names if e and isinstance(e, str) and e.strip()]
    if not cleaned_names:
        return {"exact": [], "fuzzy": []}

    exact_matches: list[dict] = []
    fuzzy_matches: list[dict] = []

    async with get_db() as db:
        # 1. 查询精确匹配
        placeholders = ",".join("?" * len(cleaned_names))
        cursor = await db.execute(
            f"SELECT entity_name, description FROM world_lore "
            f"WHERE group_id = ? AND entity_name IN ({placeholders})",
            (group_id, *cleaned_names),
        )
        exact_rows = await cursor.fetchall()

        exact_matches = [dict(r) for r in exact_rows]
        exact_names = {r["entity_name"] for r in exact_matches}

        # 2. 对每个提取出的实体，进行轻量子串模糊查询
        for entity in cleaned_names:
            # 过滤掉只有单个字的极短词，避免 SQL LIKE 导致极高召回率的严重噪音
            if len(entity) <= 1:
                continue

            # 双向 LIKE：实体包含表里的设定名，或者设定名包含提取出的实体（对通配符进行转义保护）
            escaped_entity = _escape_like(entity)
            cursor = await db.execute(
                "SELECT entity_name, description FROM world_lore "
                "WHERE group_id = ? AND (entity_name LIKE ? ESCAPE '\\' OR ? LIKE '%' || entity_name || '%')",
                (group_id, f"%{escaped_entity}%", entity),
            )
            fuzzy_rows = await cursor.fetchall()

            for r in fuzzy_rows:
                if r["entity_name"] not in exact_names:
                    fuzzy_matches.append(dict(r))
                    exact_names.add(r["entity_name"])  # 避免同一词被多个提取实体召回导致重复

    return {"exact": exact_matches, "fuzzy": fuzzy_matches}
