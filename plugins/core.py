"""
核心插件 — 处理群消息事件。

职责：消息预处理 → 话题更新 → 防抖 → Judge 判定 → Writer 回复 → 记忆提取。
"""

from __future__ import annotations

import asyncio
import random
import re

from alicebot import Plugin
from alicebot.adapter.cqhttp.event import GroupMessageEvent

from config import config
from logger import get_logger
from services import llm
from services.storage import decisions, memories as mem_store
from services.topic import topic_manager

logger = get_logger("CorePlugin")

_debounce_seconds: float = config.topic.debounce_seconds
_judge_model_name: str = config.llm.judge_model


class QJinEraPlugin(Plugin):
    # 类级防抖任务表: {group_id: asyncio.Task}
    _debounce_tasks: dict[str, asyncio.Task] = {}

    async def handle(self) -> None:
        event: GroupMessageEvent = self.event

        user_id = str(event.user_id)
        group_id = str(event.group_id)

        if not topic_manager.is_group_allowed(group_id):
            return

        content = _preprocess_message(str(event.message))
        nickname = getattr(event.sender, "nickname", "") if hasattr(event, "sender") else ""

        logger.debug("收到消息 [群%s 用户%s]: %s", group_id, user_id, content[:50])

        # 1. 话题管理 & 上下文
        context = topic_manager.handle_message(group_id, user_id, content, nickname)

        # 2. @ 检测
        if _is_mentioned(event):
            # 被 @ 时取消该群的防抖，避免双重回复
            self._cancel_debounce(group_id)
            context["is_at_mentioned"] = True
            logger.info("被 @ 提及，直接回复 [群%s]", group_id)

            asyncio.create_task(self._extract_user_memories(group_id, user_id))
            await self._respond(context, event)
            return

        # 3. 防抖 → Judge
        self._cancel_debounce(group_id)
        task = asyncio.create_task(self._debounce_then_judge(group_id, event))
        self._debounce_tasks[group_id] = task

    async def rule(self) -> bool:
        return isinstance(self.event, GroupMessageEvent)

    # ------------------------------------------------------------------
    #  内部流程
    # ------------------------------------------------------------------

    async def _debounce_then_judge(self, group_id: str, event: GroupMessageEvent) -> None:
        """防抖等待后，调用 Judge 模型判断是否插话。"""
        try:
            await asyncio.sleep(_debounce_seconds)
        except asyncio.CancelledError:
            return                              # 新消息到达，防抖重置

        context = topic_manager.get_latest_context(group_id)
        if not context:
            return

        logger.debug("防抖结束，咨询 Judge [群%s]", group_id)
        result = await llm.judge_interruption(context)

        # 记录决策日志
        decisions.add(
            group_id, _judge_model_name, result,
            context.get("topic_summary", ""),
        )

        # 话题转变感知
        if result.get("topic_shifted"):
            logger.info("Judge 感知话题转变 [群%s]，归档旧话题并创建新话题", group_id)
            topic_manager.switch_topic(group_id)
            context = topic_manager.get_latest_context(group_id)
            if not context:
                return

        # 记忆提取信号
        if result.get("has_significant_info"):
            user_id = str(event.user_id)
            logger.debug("Judge 发现重要信息，提取记忆 [用户%s]", user_id)
            asyncio.create_task(self._extract_user_memories(group_id, user_id))

        # 插话判定
        if result.get("should_intervene"):
            logger.info("Judge 判定：插话 [群%s] 原因: %s", group_id, result.get("reason", ""))
            await self._respond(context, event)
        else:
            logger.debug("Judge 判定：沉默 [群%s]", group_id)

    async def _respond(self, context: dict, event: GroupMessageEvent) -> None:
        """调用 Writer 模型生成回复并发送。"""
        context["should_return_summary"] = True
        chat_result = await llm.generate_chat(context)

        messages = chat_result.get("messages", [])
        summary = chat_result.get("summary")

        if summary:
            topic_manager.update_summary(str(event.group_id), summary)

        bot_id = str(getattr(event, "self_id", "bot"))

        for msg in messages:
            delay = random.uniform(0.3, 1.2) + len(msg) * 0.05
            await asyncio.sleep(delay)
            await event.reply(msg)
            topic_manager.add_bot_message(str(event.group_id), msg, bot_id, "柒槿年")

    async def _extract_user_memories(self, group_id: str, user_id: str) -> None:
        """从当前话题中提取用户的新事实。"""
        topic = topic_manager.get_current_topic(group_id)
        if not topic:
            return

        user_msgs = [m["content"] for m in topic["messages"] if m["user_id"] == user_id]
        if len(user_msgs) < 2:
            return

        logger.debug("提取用户 %s 的记忆...", user_id)
        new_facts = await llm.extract_memories(user_msgs[-10:])

        for fact in new_facts:
            mem_store.add(user_id, group_id, fact)
            logger.info("+ 记忆: %s [用户%s]", fact, user_id)

    # ------------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------------

    def _cancel_debounce(self, group_id: str) -> None:
        """取消指定群的防抖任务。"""
        task = self._debounce_tasks.pop(group_id, None)
        if task and not task.done():
            task.cancel()


# ---------------------------------------------------------------------------
#  模块级工具函数
# ---------------------------------------------------------------------------

def _preprocess_message(raw: str) -> str:
    """预处理 CQ 码消息，将图片替换为文本标记。"""
    text = re.sub(r'\[CQ:image,[^\]]+\]', ' [图片] ', raw)
    text = re.sub(r'\[CQ:[^\]]+\]', '', text).strip()
    return text or "[表情/图片]"


def _is_mentioned(event: GroupMessageEvent) -> bool:
    """检查 Bot 是否被 @。"""
    if getattr(event, "to_me", False):
        return True
    self_id = getattr(event, "self_id", None)
    if self_id and f"[CQ:at,qq={self_id}]" in str(event.message):
        return True
    return False
