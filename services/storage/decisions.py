"""决策日志的数据库操作。"""

from __future__ import annotations

import time

from services.storage.database import get_db


def add(group_id: str, judge_model: str, result: dict, context_summary: str = "") -> None:
    """记录一次 Judge 模型的决策。"""
    with get_db() as db:
        db.execute(
            "INSERT INTO decision_logs "
            "(group_id, timestamp, judge_model, should_intervene, trigger_level, reason, context_summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                group_id,
                time.time(),
                judge_model,
                result.get("should_intervene", False),
                result.get("trigger_level", "none"),
                result.get("reason", ""),
                context_summary,
            ),
        )
