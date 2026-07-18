"""
记忆服务 — Cyber Echo 记忆巩固 + 群画像更新。

当话题归档且有 ≥3 条 active 记忆时，调用 LLM 将碎片化事实
融合进用户的长期画像 (description)。
同时更新群组的整体氛围印象 (group_vibe)。
"""

from __future__ import annotations

from logger import get_logger
from services import llm
from services.storage import groups as group_store, memories, topics, users

logger = get_logger("MemoryService")


async def consolidate_if_needed(user_id: str, group_id: str) -> None:
    """检查是否满足巩固条件，满足则执行 Cyber Echo。"""
    active_mem = memories.get_active_details(user_id, group_id)

    if len(active_mem) < 3:
        return

    logger.info("触发 Cyber Echo：用户 %s，%d 条事实", user_id, len(active_mem))

    # 获取当前用户画像
    user = users.get(group_id, user_id)
    current_desc = (user["description"] if user and user.get("description") else "New user.")

    # 调用 LLM 巩固
    result = await llm.consolidate_memory(current_desc, active_mem)
    if not result:
        logger.warning("Cyber Echo：LLM 返回空结果，跳过")
        return

    # 更新用户画像
    new_desc = result.get("new_description")
    if new_desc:
        users.update_description(group_id, user_id, new_desc)
        logger.info("✅ 更新用户 %s 的画像", user_id)

    # 归档已巩固的记忆
    consolidated_ids = _safe_int_list(result.get("consolidated_ids", []))
    if consolidated_ids:
        memories.update_status(consolidated_ids, "archived")
        logger.info("🗄️ 归档 %d 条巩固事实", len(consolidated_ids))

    # 琐碎记忆 → short_term
    discarded_ids = _safe_int_list(result.get("discarded_ids", []))
    if discarded_ids:
        memories.update_status(discarded_ids, "short_term")
        logger.info("🕰️ %d 条事实移至短期存储", len(discarded_ids))

    # keep_active_ids 无需处理，状态保持 active


async def consolidate_group_vibe_task(group_id: str) -> None:
    """Cyber Echo 群画像更新：从最近话题摘要沉淀群氛围印象。"""
    group_info = group_store.get(group_id)
    if not group_info:
        logger.debug("群 %s 不在 groups 表中，跳过群画像更新", group_id)
        return

    # 获取最近有摘要的话题（最多 10 条）
    recent = topics.get_recent(group_id, limit=10)
    summaries = [t["summary"] for t in recent if t.get("summary")]

    if not summaries:
        logger.debug("群 %s 无可用话题摘要，跳过群画像更新", group_id)
        return

    current_vibe = group_info.get("group_vibe", "")
    behavior_overlay = group_info.get("behavior_overlay", "")

    try:
        result = await llm.consolidate_group_vibe(
            current_vibe=current_vibe,
            behavior_overlay=behavior_overlay,
            recent_summaries=summaries,
        )
        new_vibe = result.get("group_vibe", "")
        if new_vibe:
            group_store.update_vibe(group_id, new_vibe)
            logger.info("✅ 更新群 %s 的氛围画像: %s", group_id, new_vibe[:50])
    except Exception:
        logger.error("群画像更新失败 [群%s]", group_id, exc_info=True)


def _safe_int_list(raw: list) -> list[int]:
    """将 LLM 返回的 ID 列表安全转为 int。"""
    result = []
    for item in raw:
        try:
            result.append(int(item))
        except (ValueError, TypeError):
            pass
    return result
