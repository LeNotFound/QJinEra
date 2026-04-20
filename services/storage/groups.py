"""群组信息的数据库操作。"""

from __future__ import annotations

import time

from services.storage.database import get_db


def get(group_id: str) -> dict | None:
    """获取群组信息，不存在则返回 None。"""
    with get_db() as db:
        row = db.execute(
            "SELECT group_id, group_name, intimacy_level, "
            "behavior_overlay, group_vibe, created_at, updated_at "
            "FROM groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        return dict(row) if row else None


def upsert(group_id: str, group_name: str = "") -> None:
    """创建或更新群组记录（仅更新 group_name 和 updated_at）。"""
    now = time.time()
    with get_db() as db:
        row = db.execute(
            "SELECT group_id FROM groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()

        if row:
            if group_name:
                db.execute(
                    "UPDATE groups SET group_name = ?, updated_at = ? "
                    "WHERE group_id = ?",
                    (group_name, now, group_id),
                )
        else:
            db.execute(
                "INSERT INTO groups (group_id, group_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (group_id, group_name, now, now),
            )


def update_vibe(group_id: str, group_vibe: str) -> None:
    """更新群组的自动画像（由 Cyber Echo 调用）。"""
    with get_db() as db:
        db.execute(
            "UPDATE groups SET group_vibe = ?, updated_at = ? WHERE group_id = ?",
            (group_vibe, time.time(), group_id),
        )


def update_overlay(
    group_id: str, behavior_overlay: str, intimacy_level: str | None = None,
) -> None:
    """更新群组的手动行为覆层（管理员操作）。"""
    now = time.time()
    with get_db() as db:
        if intimacy_level is not None:
            db.execute(
                "UPDATE groups SET behavior_overlay = ?, intimacy_level = ?, updated_at = ? "
                "WHERE group_id = ?",
                (behavior_overlay, intimacy_level, now, group_id),
            )
        else:
            db.execute(
                "UPDATE groups SET behavior_overlay = ?, updated_at = ? "
                "WHERE group_id = ?",
                (behavior_overlay, now, group_id),
            )
