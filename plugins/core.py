"""
核心插件 — 处理群消息事件。

职责：
- AliceBot 事件过滤 (rule)
- 并发锁管理与防抖调度
- 预处理协调、命令拦截与主流程编排
- Judge 判定、Writer 生成与记忆提取
- 心智接力与危机断路器 (Circuit Breaker)
"""

from __future__ import annotations

import asyncio
import datetime
import random

from alicebot import Plugin
from alicebot.adapter.cqhttp.event import GroupMessageEvent

from config import config
from logger import get_logger
from models.message import MessageContent
from services import life_engine, llm
from services.commands import handle_command
from services.identity import (
    build_identity_map,
    is_bot_self,
    is_bot_self_memory,
    resolve_subject_id,
    sanitize_memory_content,
)
from services.message_preprocessor import is_mentioned, preprocess_message
from services.storage import (
    bot_status as bot_status_store,
    decisions,
    memories as mem_store,
    users as user_store,
    world_lore,
)
from services.topic import topic_manager
from utils import spawn_task

logger = get_logger("CorePlugin")

_judge_model_name: str = config.llm.judge_model
_debounce_seconds: float = config.topic.debounce_seconds


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

        content, memory_images = await preprocess_message(str(event.message))
        nickname = getattr(getattr(event, "sender", None), "nickname", "") or ""
        bot_id = str(event.self_id)

        logger.debug("收到消息 [群%s 用户%s]: %s", group_id, user_id, content.text[:50])
        logger.debug("当前 bot_id 为: %s", bot_id)

        # 指令路由拦截（解耦的命令处理器）
        if await handle_command(event, content):
            self._cancel_debounce(group_id)
            old_at_task = self._at_tasks.pop(group_id, None)
            if old_at_task and not old_at_task.done():
                old_at_task.cancel()
            return

        # 1. 话题管理 & 上下文
        await topic_manager.handle_message(group_id, user_id, content, nickname, bot_id, memory_images)

        # 2. @ 检测
        if is_mentioned(event):
            # 被 @ 时取消该群的防抖，避免双重回复
            self._cancel_debounce(group_id)

            # 若已有排队等待处理的 @ 任务，直接取消（只保留最新的）
            old_at_task = self._at_tasks.pop(group_id, None)
            if old_at_task and not old_at_task.done():
                old_at_task.cancel()

            logger.info("被 @ 提及，直接回复 [群%s]", group_id)

            spawn_task(self._extract_user_memories(group_id, user_id, bot_id))

            # 使用锁避免并发回答
            async def _at_respond():
                async with self._get_group_lock(group_id):
                    # 一旦进入临界区，本任务就不再是“排队中的候选被打断者”，移出字典
                    if self._at_tasks.get(group_id) == asyncio.current_task():
                        self._at_tasks.pop(group_id, None)

                    latest_ctx = await topic_manager.get_latest_context(group_id, bot_id)
                    if latest_ctx:
                        latest_ctx["is_at_mentioned"] = True
                        await self._respond(latest_ctx, event)

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
            return  # 新消息到达，防抖重置

        # 防抖结束，此时已经决定要进行模型判定，从打断列表中移除自己
        if self._debounce_tasks.get(group_id) == asyncio.current_task():
            self._debounce_tasks.pop(group_id, None)

        async with self._get_group_lock(group_id):
            bot_id = str(event.self_id)
            context = await topic_manager.get_latest_context(group_id, bot_id)
            if not context:
                return

            # 注入当前 bot_status 以便 Judge 感知生理状态与省电模式（自动补全静默漂移）
            bot_st = await life_engine.ensure_tick(bot_id)
            context["bot_status"] = bot_st

            logger.debug("防抖结束，咨询 Judge [群%s]", group_id)
            result = await llm.judge_interruption(context)

            if result is None:
                logger.warning("Judge 判定失败 (API 调用异常)，跳过本次回复 [群%s]", group_id)
                return

            trigger_level = result.get("trigger_level", "none")
            reason = result.get("reason", "")
            state_updates = result.get("state_updates") or {}

            # 记录决策日志
            await decisions.add(
                group_id, _judge_model_name, result,
                context.get("topic_summary", ""),
            )

            # 交互驱动：计算思考消耗与多巴胺流转
            energy_cost = state_updates.get("energy_cost") if "energy_cost" in state_updates else result.get("energy_cost")
            dopamine_delta = state_updates.get("dopamine_delta") if "dopamine_delta" in state_updates else result.get("dopamine_delta")
            if energy_cost is not None or dopamine_delta is not None:
                await life_engine.apply_interaction_cost(
                    bot_id,
                    energy_cost=energy_cost,
                    dopamine_delta=dopamine_delta,
                )

            # 心智接力：更新 bot_status 高维状态（排除由 life_engine 状态机维护的字段）
            bot_updates = {}
            for field in [
                "empathy_mood",
                "cur_objective",
                "focus_user",
                "active_concerns",
            ]:
                if field in state_updates and state_updates[field] is not None:
                    bot_updates[field] = state_updates[field]
            if bot_updates:
                await bot_status_store.update_state(bot_id, **bot_updates)

            # 更新 users 表当前发言用户画像
            user_id = str(event.user_id)
            u_dynamic = state_updates.get("user_dynamic_status")
            u_mood = state_updates.get("user_mood")
            if u_dynamic or u_mood:
                await user_store.update_status_and_mood(
                    group_id, user_id, dynamic_status=u_dynamic, current_mood=u_mood
                )

            # 同步更新当前上下文中的用户画像快照，确保 Writer 实时感知到最新的心理状态和动态体征
            if not isinstance(context.get("user_profile_raw"), dict):
                context["user_profile_raw"] = {}
            if u_dynamic:
                context["user_profile_raw"]["dynamic_status"] = u_dynamic
            if u_mood:
                context["user_profile_raw"]["current_mood"] = u_mood

            # 将潜意识研判、共情情绪、当前目标与锁定对象存入上下文向下游传递
            context["intervention_reason"] = reason
            context["trigger_level"] = trigger_level
            if state_updates.get("empathy_mood"):
                context["empathy_mood"] = state_updates["empathy_mood"]
            if state_updates.get("cur_objective"):
                context["cur_objective"] = state_updates["cur_objective"]
            if state_updates.get("focus_user"):
                context["focus_user"] = state_updates["focus_user"]

            # 危机断路器 (Circuit Breaker)
            if trigger_level == "crisis":
                logger.warning("🚨 触发危机断路器 (Circuit Breaker) [群%s 用户%s]！", group_id, user_id)
                context["circuit_breaker_directive"] = (
                    "[系统指令：用户极度脆弱，回复绝不超30字，纯粹托底，不要建议，禁止道德绑架，禁止说教]"
                )

            # 记录 world_lore (Phase 3)
            entities = result.get("mentioned_entities", [])
            if entities:
                context["mentioned_entities"] = entities  # 让下文能拿到

            # 话题转变感知
            if result.get("topic_shifted"):
                logger.info("Judge 感知话题转变 [群%s]，归档旧话题并创建新话题", group_id)
                await topic_manager.switch_topic(group_id)
                new_ctx = await topic_manager.get_latest_context(group_id, bot_id)
                if not new_ctx:
                    return
                # 迁移心智及上下文数据
                for k in [
                    "intervention_reason",
                    "trigger_level",
                    "empathy_mood",
                    "cur_objective",
                    "focus_user",
                    "circuit_breaker_directive",
                    "mentioned_entities",
                    "user_profile_raw",
                ]:
                    if k in context:
                        new_ctx[k] = context[k]
                context = new_ctx

            # 记忆提取信号
            if result.get("has_significant_info"):
                logger.debug("Judge 发现重要信息，提取记忆/世界设定 [群:%s 用户:%s]", group_id, user_id)
                spawn_task(self._extract_user_memories(group_id, user_id, bot_id))

            # 插话判定（传入当前的上下文）
            if result.get("should_intervene") or trigger_level == "crisis":
                logger.info("Judge 判定：插话 [群%s] 级别: %s 原因: %s", group_id, trigger_level, reason)
                await self._respond(context, event)
            else:
                logger.debug("Judge 判定：沉默 [群%s]", group_id)

    async def _respond(self, context: dict, event: GroupMessageEvent) -> None:
        """调用 Writer 模型生成回复并发送。"""
        context["should_return_summary"] = True
        bot_id = str(event.self_id)

        # 注入 bot_status 高维心智（自动补全静默漂移）
        bot_st = await life_engine.ensure_tick(bot_id)
        # 如果 context 中有 Judge 实时更新的情绪/目标/专注用户，同步体现
        if context.get("empathy_mood"):
            bot_st["empathy_mood"] = context["empathy_mood"]
        if context.get("cur_objective"):
            bot_st["cur_objective"] = context["cur_objective"]
        if context.get("focus_user"):
            bot_st["focus_user"] = context["focus_user"]
        context["bot_status"] = bot_st

        is_power_saving = life_engine.is_low_energy(bot_st)
        is_sleeping = bot_st.get("current_state") == life_engine.STATE_SLEEPING
        if is_power_saving:
            logger.info("🔋 [LifeEngine] Bot %s 处于低电量省电模式 (精力: %s)，开启慵懒极简回复", bot_id, bot_st.get("energy"))
        elif is_sleeping:
            logger.info("🌙 [LifeEngine] Bot %s 处于夜间休眠中，开启深夜被唤醒极简回复", bot_id)

        # [Phase 3] 从 context 提取实体，并去 world_lore 表查数据给 Chat Writer
        entities = context.get("mentioned_entities")
        if entities:
            lores = await world_lore.get_by_entities(str(event.group_id), entities)
            context["world_lore"] = lores

        chat_result = await llm.generate_chat(context)

        if chat_result is None:
            logger.warning("Writer 生成失败 (API 调用异常)，跳过发送 [群%s]", event.group_id)
            return

        messages = chat_result.get("messages", [])
        summary = chat_result.get("summary")

        # 交互驱动：计算写手模型输出的思维消耗与多巴胺流动
        writer_energy_cost = chat_result.get("energy_cost")
        writer_dopamine_delta = chat_result.get("dopamine_delta")
        if messages and writer_energy_cost is None:
            # 发言默认消耗微量脑力（2.0），并略微提升多巴胺
            writer_energy_cost = 2.0
            if writer_dopamine_delta is None:
                writer_dopamine_delta = 1.0

        if writer_energy_cost is not None or writer_dopamine_delta is not None:
            await life_engine.apply_interaction_cost(
                bot_id,
                energy_cost=writer_energy_cost,
                dopamine_delta=writer_dopamine_delta,
            )

        if summary:
            await topic_manager.update_summary(str(event.group_id), summary)

        # 危机模式、低电量省电模式与夜间休眠防护：严格限制回复条数为 1，防止长篇轰炸，保持松弛与专注
        is_crisis = context.get("trigger_level") == "crisis"
        if (is_crisis or is_power_saving or is_sleeping) and messages:
            messages = messages[:1]

        for msg in messages:
            delay = 0.2 if is_crisis else (random.uniform(0.3, 1.2) + len(msg) * 0.05)
            await asyncio.sleep(delay)
            await event.reply(msg)
            await topic_manager.add_bot_message(str(event.group_id), msg, bot_id, config.bot.name)

    async def _extract_user_memories(self, group_id: str, user_id: str, bot_id: str = "") -> None:
        """从当前话题中提取用户的新事实和群世界观（World Lore）。"""
        topic = await topic_manager.get_current_topic(group_id)
        if not topic:
            return

        msgs = topic["messages"]
        if len(msgs) < 2:
            return

        logger.debug("提取围绕用户 %s 展开的记忆与设定...", user_id)

        # 传递最近 10 条带身份和格式的消息，好让 LLM 能提取出 source_id 和 subject_id
        recent = []
        user_pairs = []
        for m in msgs[-10:]:
            msg_content = MessageContent.from_raw(m["content"])
            text_content = msg_content.text
            nick = m.get('nickname') or m['user_id']
            recent.append(
                f"[{datetime.datetime.fromtimestamp(m['timestamp']).strftime('%H:%M:%S')}] "
                f"{nick}({m['user_id']}): {text_content}"
            )
            if m.get("user_id") and m.get("nickname"):
                user_pairs.append((str(m["user_id"]), str(m["nickname"])))

        if not bot_id:
            bot_id = str(getattr(self.event, "self_id", config.bot.admin_qq))

        identity_map = build_identity_map(user_pairs)
        active_memories = await mem_store.get_for_context(user_id, group_id=group_id, limit=20)
        extraction_result = await llm.extract_memories(
            recent, active_memories, identity_map=identity_map, bot_id=bot_id
        )

        if not extraction_result:
            logger.warning("记忆提取失败 (API 调用异常)，跳过 [用户%s]", user_id)
            return

        facts = extraction_result.get("facts", [])
        lores = extraction_result.get("world_lore", [])

        for fact_dict in facts:
            raw_subj = str(fact_dict.get("subject_id") or user_id).strip()
            raw_src = str(fact_dict.get("source_id") or user_id).strip()
            content = str(fact_dict.get("content") or "").strip()

            # 反向解析主客体 QQ 号，杜绝名称残留导致孤儿记忆
            subj = resolve_subject_id(raw_subj, identity_map, fallback_id=user_id)
            src = resolve_subject_id(raw_src, identity_map, fallback_id=user_id)

            # 守卫：拦截机器人自指与外部化记忆
            if is_bot_self(subj, bot_id) or is_bot_self(raw_subj, bot_id) or is_bot_self_memory(content, bot_id):
                logger.info("守卫拦截机器人自指或虚构记忆入库: [subject:%s] %s", subj, content)
                continue

            # 具名化净化（消除"该用户"等机械公文腔）
            subj_name = identity_map.get(subj, "")
            clean_content = sanitize_memory_content(content, subj_name)

            fact_dict["subject_id"] = subj
            fact_dict["source_id"] = src
            fact_dict["content"] = clean_content

            await mem_store.add(user_id, group_id, fact_dict, bot_id=bot_id)
            logger.info(
                "+ 事实: %s [涉及对象:%s, 来源:%s]",
                clean_content,
                subj,
                src,
            )

        for lore in lores:
            name = lore.get("entity_name")
            desc = lore.get("description")
            if name and desc:
                cleaned_name = str(name).strip()
                if is_bot_self(cleaned_name, bot_id):
                    logger.info("守卫拦截机器人自指设定入库 World Lore: [%s] %s", cleaned_name, desc)
                    continue
                clean_desc = sanitize_memory_content(str(desc).strip())
                await world_lore.add_or_update(group_id, user_id, cleaned_name, clean_desc, bot_id=bot_id)
                logger.info("+ 世界观: [%s] %s [提供者%s]", cleaned_name, clean_desc, user_id)

    # ------------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------------

    def _cancel_debounce(self, group_id: str) -> None:
        """取消指定群的防抖任务。"""
        task = self._debounce_tasks.pop(group_id, None)
        if task and not task.done():
            task.cancel()
