"""Bot 状态的数据库操作。"""

from __future__ import annotations

import json
import time

from services.storage.database import get_db


async def get(bot_id: str) -> dict | None:
    """获取 Bot 状态，若不存在返回 None。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT bot_id, energy, mood, current_state, loneliness, dopamine, "
            "current_activity, focus_user, cur_objective, empathy_mood, active_concerns, last_updated "
            "FROM bot_status WHERE bot_id = ?",
            (bot_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get("energy") is None:
            data["energy"] = 100.0
        if data.get("mood") is None:
            data["mood"] = "平静"
        if data.get("current_state") is None:
            data["current_state"] = "active"
        if data.get("loneliness") is None:
            data["loneliness"] = 0.0
        if data.get("dopamine") is None:
            data["dopamine"] = 50.0
        if data.get("current_activity") is None:
            data["current_activity"] = ""
        if data.get("focus_user") is None:
            data["focus_user"] = ""
        if data.get("cur_objective") is None:
            data["cur_objective"] = ""
        if data.get("empathy_mood") is None:
            data["empathy_mood"] = ""
        if data.get("last_updated") is None:
            data["last_updated"] = time.time()

        concerns = data.get("active_concerns")
        if isinstance(concerns, str):
            try:
                concerns = json.loads(concerns)
            except Exception:
                concerns = []
        if not isinstance(concerns, list):
            concerns = []
        data["active_concerns"] = concerns
        return data


async def upsert(
    bot_id: str,
    energy: float = 100.0,
    mood: str = "平静",
    current_state: str = "active",
    loneliness: float = 0.0,
    dopamine: float = 50.0,
    current_activity: str = "",
    focus_user: str = "",
    cur_objective: str = "",
    empathy_mood: str = "",
    active_concerns: list | str = "[]",
    last_updated: float | None = None,
) -> None:
    """创建或覆盖更新 Bot 状态。"""
    now = last_updated if last_updated is not None else time.time()
    concerns_str = (
        json.dumps(active_concerns, ensure_ascii=False)
        if isinstance(active_concerns, (list, dict))
        else str(active_concerns)
    )
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO bot_status (
                bot_id, energy, mood, current_state, loneliness, dopamine,
                current_activity, focus_user, cur_objective, empathy_mood,
                active_concerns, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bot_id) DO UPDATE SET
                energy = excluded.energy,
                mood = excluded.mood,
                current_state = excluded.current_state,
                loneliness = excluded.loneliness,
                dopamine = excluded.dopamine,
                current_activity = excluded.current_activity,
                focus_user = excluded.focus_user,
                cur_objective = excluded.cur_objective,
                empathy_mood = excluded.empathy_mood,
                active_concerns = excluded.active_concerns,
                last_updated = excluded.last_updated
            """,
            (
                bot_id, energy, mood, current_state, loneliness, dopamine,
                current_activity, focus_user, cur_objective, empathy_mood,
                concerns_str, now
            ),
        )


async def update_state(bot_id: str, **kwargs) -> None:
    """按需更新 Bot 的部分状态字段。"""
    if not kwargs:
        return
    if "last_updated" not in kwargs:
        kwargs["last_updated"] = time.time()
    if "active_concerns" in kwargs and isinstance(kwargs["active_concerns"], (list, dict)):
        kwargs["active_concerns"] = json.dumps(kwargs["active_concerns"], ensure_ascii=False)

    existing = await get(bot_id)
    if not existing:
        await upsert(bot_id, **kwargs)
        return

    cols = []
    params = []
    for k, v in kwargs.items():
        cols.append(f"{k} = ?")
        params.append(v)
    params.append(bot_id)

    async with get_db() as db:
        await db.execute(
            f"UPDATE bot_status SET {', '.join(cols)} WHERE bot_id = ?",
            params,
        )
