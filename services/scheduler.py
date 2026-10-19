"""
调度器插件 — 后台定时任务。

职责：巡检过期话题 → 触发 Cyber Echo / 主动发起聊天（冷场时）。
"""

from __future__ import annotations

import asyncio
import time

from alicebot import Bot

from config import config
from logger import get_logger
from services import llm
from services.memory_service import consolidate_if_needed, consolidate_group_vibe_task
from services.storage import groups as group_store, memories
from services.topic import topic_manager
from utils import spawn_task

logger = get_logger("Scheduler")

_proactive_interval: float = config.topic.proactive_chat_interval_minutes * 60
_bot_self_id: str = str(config.bot.admin_qq)
_groups_initialized: bool = False


def _get_ready_adapter(bot: Bot):
    """获取第一个处于活动连接状态的适配器（需确保 WebSocket 已建立）。"""
    if not bot.adapters:
        return None
    adapter = bot.adapters[0]
    ws = getattr(adapter, "websocket", None)
    if ws is None or getattr(ws, "closed", False):
        return None
    return adapter


async def start_scheduler_loop(bot: Bot) -> None:
    logger.info("调度器启动，等待适配器连接就绪...")
    # 轮询等待 WebSocket 连接真正建立（最多等待 60 秒）
    for _ in range(60):
        if _get_ready_adapter(bot):
            break
        await asyncio.sleep(1)
    else:
        logger.warning("未检测到活动的 WebSocket 连接（NapCat 可能尚未启动），群列表将在连接建立后自动加载")

    await _init_groups(bot)
    spawn_task(_loop(bot))


# ------------------------------------------------------------------
#  初始化
# ------------------------------------------------------------------

async def _init_groups(bot: Bot) -> bool:
    """从 adapter 获取群列表，初始化活动时间。"""
    global _groups_initialized
    if _groups_initialized:
        return True

    adapter = _get_ready_adapter(bot)
    if not adapter:
        return False

    try:
        groups = await adapter.call_api("get_group_list")
        now = time.time()
        for g in groups:
            gid = str(g["group_id"])
            group_name = g.get("group_name", "")
            if not topic_manager.is_group_allowed(gid):
                continue
            # 初始化群组到 groups 表（新群自动以 public 初始化）
            group_store.upsert(gid, group_name)
            if gid not in topic_manager.group_last_activity:
                topic_manager.group_last_activity[gid] = now
                logger.info("发现群 %s (%s)，初始化计时器", gid, group_name)
        _groups_initialized = True
        return True
    except (AssertionError, Exception) as e:
        logger.warning("获取群列表失败 (网络或适配器未就绪: %s)", e)
        return False

# ------------------------------------------------------------------
#  主循环
# ------------------------------------------------------------------

async def _loop(bot: Bot) -> None:
    """每分钟执行一次巡检。"""
    while True:
        await asyncio.sleep(60)

        # 0. 若启动时 WebSocket 未就绪，连接建立后自动重试初始化群列表
        if not _groups_initialized:
            await _init_groups(bot)

        # 1. 检查过期话题 → 触发 Cyber Echo 及其垃圾回收
        try:
            pending = topic_manager.check_expired_topics()
            for group_id, participants in pending:
                for user_id in participants:
                    spawn_task(consolidate_if_needed(user_id, group_id))
                # 群氛围更新（与用户记忆巩固并行）
                spawn_task(consolidate_group_vibe_task(group_id))
            
            # 当本轮有话题过期引发 Cyber Echo 时，顺便进行垃圾回收
            if pending:
                pruned = memories.prune_expired(retention_hours=24)
                if pruned:
                    logger.debug("清理了 %d 条过期短期记忆", pruned)
        except Exception:
            logger.error("巡检过期话题失败", exc_info=True)

        # 2. 主动发起聊天（冷场检测）
        now = time.time()
        for group_id, last_time in list(topic_manager.group_last_activity.items()):
            if not topic_manager.is_group_allowed(group_id):
                continue
            if now - last_time <= _proactive_interval:
                continue

            current_topic = topic_manager.get_current_topic(group_id)
            if current_topic and current_topic.get("messages"):
                if str(current_topic["messages"][-1]["user_id"]) == _bot_self_id:
                    continue

            try:
                logger.info("群 %s 冷场超过 %d 分钟，主动发起话题",
                            group_id, config.topic.proactive_chat_interval_minutes)

                result = await llm.generate_proactive_topic()
                if result is None:
                    logger.warning("主动话题生成失败 (API 调用异常)，跳过 [群%s]", group_id)
                    continue

                messages = result.get("messages", [])

                if not messages:
                    continue

                # 先更新时间，避免重复触发
                topic_manager.group_last_activity[group_id] = now

                adapter = _get_ready_adapter(bot)
                if not adapter:
                    logger.warning("发送主动消息失败：适配器未处于连接就绪状态")
                    continue

                for msg in messages:
                    await adapter.call_api(
                        "send_group_msg", group_id=int(group_id), message=msg,
                    )
                    topic_manager.add_bot_message(group_id, msg, _bot_self_id, config.bot.name)
                    await asyncio.sleep(2)

                logger.info("主动消息已发送 [群%s]: %s", group_id, messages)

            except Exception:
                logger.error("主动聊天失败 [群%s]", group_id, exc_info=True)


# ------------------------------------------------------------------
#  工具方法
# ------------------------------------------------------------------

def _get_adapter(bot: Bot):
    """获取第一个处于活动连接状态的适配器。"""
    return _get_ready_adapter(bot)
