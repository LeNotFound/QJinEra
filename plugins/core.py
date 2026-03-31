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
    # 类级被@排队任务表: {group_id: asyncio.Task}
    _at_tasks: dict[str, asyncio.Task] = {}
    # 类级群组并发锁，防止大模型并发产生重复/错乱回复
    _group_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def _get_group_lock(cls, group_id: str) -> asyncio.Lock:
        if group_id not in cls._group_locks:
            cls._group_locks[group_id] = asyncio.Lock()
        return cls._group_locks[group_id]

    @classmethod
    def _cleanup_stale_locks(cls) -> None:
        """清理无活跃话题的群组锁，防止长期运行导致内存泄漏。"""
        # 移除 lock.locked() 的判断，由于它在一定随机时机触发，我们更相信 active_topics
        # 为了极度安全，改为只清理那些“绝对不可能再继续讲话”的孤儿（连 topics 缓存里都没有它的 key 了）
        stale_groups = [
            gid for gid, lock in cls._group_locks.items() 
            if gid not in topic_manager.active_topics and not lock.locked()
        ]
        for gid in stale_groups:
            cls._group_locks.pop(gid, None)
        if stale_groups:
            logger.debug("已清理 %d 个闲置群组锁: %s", len(stale_groups), stale_groups)

    async def handle(self) -> None:
        event: GroupMessageEvent = self.event

        # 0. 偶尔清理过期锁，防止内存泄漏 (5% 概率)
        if random.random() < 0.05:
            self._cleanup_stale_locks()

        user_id = str(event.user_id)
        group_id = str(event.group_id)

        if not topic_manager.is_group_allowed(group_id):
            return

        content = _preprocess_message(str(event.message))
        nickname = getattr(event.sender, "nickname", "") if hasattr(event, "sender") else ""

        logger.debug("收到消息 [群%s 用户%s]: %s", group_id, user_id, content[:50])
        bot_id = str(event.self_id)
        logger.debug("当前 bot_id 为: %s", bot_id)

        if content.strip() == "/clear":
            topic_manager.switch_topic(group_id)
            await event.reply("已清空当前群聊话题的短期上下文。")
            return

        # 1. 话题管理 & 上下文
        context = topic_manager.handle_message(group_id, user_id, content, nickname, bot_id)

        # 2. @ 检测
        if _is_mentioned(event):
            # 被 @ 时取消该群的防抖，避免双重回复
            self._cancel_debounce(group_id)
            
            # 只有当旧任务尚未拿到锁(即依然在等待状态)时，才取消它
            # 避免正在生成或发消息的任务被打断
            old_at_task = self._at_tasks.get(group_id)
            if old_at_task and not old_at_task.done():
                # 判断旧任务是否还在排队（没拿到锁）。由于 _at_respond 在执行前都在 await lock
                if not self._get_group_lock(group_id).locked():
                     # 锁是放开的说明它可能正在准备拿锁但还没运行实际逻辑，或者根本不存在等待
                     pass 
                else: 
                     # 如果锁已经被占用，说明上一个任务可能还没拿到，或者是别人拿了。但我们要防止它是在里面。
                     pass 
            # 实际上：在 _at_respond 拿到锁后，直接从 _at_tasks 移除了自己！
            # 这样还在 _at_tasks 里的 task，必然是*没拿到锁*的正处于 await 或 pending 的排队者。
            old_at_task = self._at_tasks.pop(group_id, None)
            if old_at_task and not old_at_task.done():
                old_at_task.cancel()
                
            logger.info("被 @ 提及，直接回复 [群%s]", group_id)

            asyncio.create_task(self._extract_user_memories(group_id, user_id))
            
            # 使用锁避免并发回答
            async def _at_respond():
                try:
                    async with self._get_group_lock(group_id):
                        # 一旦进入临界区，本任务就不再是“排队中的候选被打断者”，移出字典
                        if self._at_tasks.get(group_id) == asyncio.current_task():
                             self._at_tasks.pop(group_id, None)

                        latest_ctx = topic_manager.get_latest_context(group_id, bot_id) 
                        if latest_ctx:
                            latest_ctx["is_at_mentioned"] = True
                            await self._respond(latest_ctx, event)
                finally:
                    pass
            
            self._at_tasks[group_id] = asyncio.create_task(_at_respond())
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

        # 防抖结束，此时已经决定要进行模型判定，从打断列表中移除自己
        if self._debounce_tasks.get(group_id) == asyncio.current_task():
            self._debounce_tasks.pop(group_id, None)

        async with self._get_group_lock(group_id):
            bot_id = str(event.self_id)
            context = topic_manager.get_latest_context(group_id, bot_id)
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
                context = topic_manager.get_latest_context(group_id, bot_id)
                if not context:
                    return

            # 记忆提取信号
            if result.get("has_significant_info"):
                user_id = str(event.user_id)
                logger.debug("Judge 发现重要信息，提取记忆 [用户%s]", user_id)
                asyncio.create_task(self._extract_user_memories(group_id, user_id))

            # 插话判定（传入当前的上下文）
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
        active_memories = [m["content"] for m in mem_store.get_active_details(user_id)]
        new_facts = await llm.extract_memories(user_msgs[-10:], active_memories)

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
    """预处理 CQ 码消息，将图片和表情替换为文本标记。"""
    text = re.sub(r'\[CQ:image,[^\]]+\]', ' [图片] ', raw)
    text = re.sub(r'\[CQ:face,[^\]]+\]', ' [表情] ', text)
    text = re.sub(r'\[CQ:at,qq=(\d+|all)\]', r'[@\1] ', text)
    text = re.sub(r'\[CQ:[^\]]+\]', '', text).strip()
    return text or "[表情/图片]"


def _is_mentioned(event: GroupMessageEvent) -> bool:
    """检查 Bot 是否被 @。"""
    self_id = getattr(event, "self_id", None)
    if self_id and f"[CQ:at,qq={self_id}]" in str(event.message):
        return True
    # 取消 fallback to to_me, 因为容易在群里互相 @ 时误判
    return False
