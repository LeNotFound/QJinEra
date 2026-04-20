"""群组世界观设定的数据库操作。"""

from __future__ import annotations

import time

from services.storage.database import get_db

def add_or_update(group_id: str, source_id: str, entity_name: str, description: str) -> None:
    """插入新设定，若已存在同名实体，则更新描述内容。"""
    with get_db() as db:
        now = time.time()
        db.execute(
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


def get_all(group_id: str) -> list[dict]:
    """获取该群组内所有的世界观设定。"""
    with get_db() as db:
        rows = db.execute(
            "SELECT entity_name, description, source_id, updated_at FROM world_lore "
            "WHERE group_id = ? "
            "ORDER BY updated_at DESC",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_by_entities(group_id: str, entity_names: list[str]) -> list[dict]:
    """根据 Judge 模型提取的实体列表，精确获取设定的描述。"""
    if not entity_names:
        return []
    
    with get_db() as db:
        placeholders = ",".join("?" * len(entity_names))
        rows = db.execute(
            f"SELECT entity_name, description FROM world_lore "
            f"WHERE group_id = ? AND entity_name IN ({placeholders})",
            (group_id, *entity_names),
        ).fetchall()
        return [dict(r) for r in rows]
