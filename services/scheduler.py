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
from services.memory_service import consolidate_if_needed
from services.topic import topic_manager

logger = get_logger("Scheduler")

_proactive_interval: float = config.topic.proactive_chat_interval_minutes * 60


async def start_scheduler_loop(bot: Bot) -> None:
    logger.info("调度器启动，等待适配器就绪...")
    await asyncio.sleep(5)
    await _init_groups(bot)
    asyncio.create_task(_loop(bot))

# ------------------------------------------------------------------
#  初始化
# ------------------------------------------------------------------

async def _init_groups(bot: Bot) -> None:
    """从 adapter 获取群列表，初始化活动时间。"""
    adapter = _get_adapter(bot)
    if not adapter:
        logger.warning("未找到适配器，跳过群组初始化")
        return

    try:
        groups = await adapter.call_api("get_group_list")
        now = time.time()
        for g in groups:
            gid = str(g["group_id"])
            if not topic_manager.is_group_allowed(gid):
                continue
            if gid not in topic_manager.group_last_activity:
                topic_manager.group_last_activity[gid] = now
                logger.info("发现群 %s，初始化计时器", gid)
    except Exception:
        logger.error("获取群列表失败", exc_info=True)

# ------------------------------------------------------------------
#  主循环
# ------------------------------------------------------------------

async def _loop(bot: Bot) -> None:
    """每分钟执行一次巡检。"""
    while True:
        await asyncio.sleep(60)

        # 1. 检查过期话题 → 触发 Cyber Echo
        try:
            pending = topic_manager.check_expired_topics()
            for group_id, participants in pending:
                for user_id in participants:
                    asyncio.create_task(consolidate_if_needed(user_id, group_id))
        except Exception:
            logger.error("巡检过期话题失败", exc_info=True)

        # 2. 主动发起聊天（冷场检测）
        now = time.time()
        for group_id, last_time in list(topic_manager.group_last_activity.items()):
            if not topic_manager.is_group_allowed(group_id):
                continue
            if now - last_time <= _proactive_interval:
                continue

            try:
                logger.info("群 %s 冷场超过 %d 分钟，主动发起话题",
                            group_id, config.topic.proactive_chat_interval_minutes)

                result = await llm.generate_proactive_topic()
                messages = result.get("messages", [])

                if not messages:
                    continue

                # 先更新时间，避免重复触发
                topic_manager.group_last_activity[group_id] = now

                adapter = _get_adapter(bot)
                if not adapter:
                    logger.warning("发送主动消息失败：未找到适配器")
                    continue

                for msg in messages:
                    await adapter.call_api(
                        "send_group_msg", group_id=int(group_id), message=msg,
                    )
                    topic_manager.add_bot_message(group_id, msg, "bot", "柒槿年")
                    await asyncio.sleep(2)

                logger.info("主动消息已发送 [群%s]: %s", group_id, messages)

            except Exception:
                logger.error("主动聊天失败 [群%s]", group_id, exc_info=True)

# ------------------------------------------------------------------
#  工具方法
# ------------------------------------------------------------------

def _get_adapter(bot: Bot):
    """获取第一个可用的适配器。"""
    return bot.adapters[0] if bot.adapters else None
