"""
话题管理器 — 维护群组的活跃话题、上下文构建、话题归档。

每个群组同时只有一个活跃话题 (active_topic)。
话题过期后触发归档 → Cyber Echo 记忆巩固。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from config import config
from logger import get_logger
from services.storage import memories, topics, users

logger = get_logger("TopicManager")

# ---------------------------------------------------------------------------
#  从配置中一次性读取
# ---------------------------------------------------------------------------

_topic_gap: float = config.topic.topic_gap_minutes * 60
_allowed_groups: set[int] = set(config.bot.allowed_groups)


# ---------------------------------------------------------------------------
#  TopicManager
# ---------------------------------------------------------------------------

class TopicManager:
    def __init__(self) -> None:
        # {group_id: {"topic_id", "last_msg_time", "messages", "summary"}}
        self.active_topics: dict[str, dict] = {}
        # {group_id: last_activity_timestamp}
        self.group_last_activity: dict[str, float] = {}

        self._restore_active_topics()

    # ------------------------------------------------------------------
    #  群组白名单
    # ------------------------------------------------------------------

    @staticmethod
    def is_group_allowed(group_id: str) -> bool:
        if not _allowed_groups:
            return True
        return int(group_id) in _allowed_groups

    # ------------------------------------------------------------------
    #  启动恢复
    # ------------------------------------------------------------------

    def _restore_active_topics(self) -> None:
        """从数据库恢复活跃话题，清理过期话题。"""
        now = time.time()
        threshold = now - _topic_gap

        for gid in topics.get_all_known_groups():
            if not self.is_group_allowed(gid):
                continue

            # 关闭所有过期话题
            closed = topics.close_stale(gid, threshold)
            if closed:
                logger.info("启动清理：关闭群 %s 的 %d 个过期话题", gid, closed)

            # 尝试恢复最新的活跃话题
            topic = topics.get_latest_active(gid)
            if not topic:
                continue

            last_time = topic["last_msg_time"]
            self.group_last_activity[gid] = last_time

            if now - last_time <= _topic_gap:
                self.active_topics[gid] = topic
                logger.info("恢复群 %s 的活跃话题 (ID=%d)", gid, topic["topic_id"])

    # ------------------------------------------------------------------
    #  话题过期检查（由 scheduler 定期调用）
    # ------------------------------------------------------------------

    def check_expired_topics(self) -> list[tuple[str, set[str]]]:
        """检查并归档过期话题。

        Returns:
            待执行 Cyber Echo 的 [(group_id, {user_ids}), ...] 列表，
            由调用方在 async 上下文中触发巩固任务。
        """
        now = time.time()
        pending_consolidations: list[tuple[str, set[str]]] = []

        expired = [
            gid for gid, t in self.active_topics.items()
            if now - t["last_msg_time"] > _topic_gap
        ]

        for gid in expired:
            topic = self.active_topics[gid]
            participants = {msg["user_id"] for msg in topic["messages"]}
            logger.info("归档群 %s 的过期话题 (ID=%d)", gid, topic["topic_id"])

            topics.update_summary(
                topic["topic_id"],
                topic.get("summary"),
                topic["last_msg_time"],
            )
            del self.active_topics[gid]

            if participants:
                pending_consolidations.append((gid, participants))

        return pending_consolidations

    # ------------------------------------------------------------------
    #  消息处理
    # ------------------------------------------------------------------

    def handle_message(
        self, group_id: str, user_id: str, content: str, nickname: str = "",
    ) -> dict[str, Any] | None:
        """处理新消息：更新话题、构建上下文。"""
        if not self.is_group_allowed(group_id):
            return None

        now = time.time()
        users.upsert(group_id, user_id, nickname, now)

        self._ensure_topic_loaded(group_id)
        current = self.active_topics.get(group_id)

        # 判断是否需要新话题
        need_new = current is None or (now - current["last_msg_time"] > _topic_gap)

        if need_new:
            if current is not None:
                self._archive_topic_sync(group_id)
            topic_id = topics.create(group_id, now)
            current = {
                "topic_id": topic_id,
                "last_msg_time": now,
                "messages": [],
                "summary": None,
            }
            self.active_topics[group_id] = current

        # 追加消息
        current["last_msg_time"] = now
        current["messages"].append({
            "user_id": user_id,
            "nickname": nickname,
            "content": content,
            "timestamp": now,
        })
        topics.add_message(current["topic_id"], user_id, content, now, nickname)
        self.group_last_activity[group_id] = now

        return self._build_context(group_id, user_id, content, now)

    def add_bot_message(
        self, group_id: str, content: str, bot_id: str, nickname: str = "QJinEra",
    ) -> None:
        """记录 Bot 自己发送的消息。"""
        now = time.time()

        self._ensure_topic_loaded(group_id)
        current = self.active_topics.get(group_id)

        if current is None:
            topic_id = topics.create(group_id, now)
            current = {
                "topic_id": topic_id,
                "last_msg_time": now,
                "messages": [],
                "summary": None,
            }
            self.active_topics[group_id] = current

        current["last_msg_time"] = now
        current["messages"].append({
            "user_id": bot_id,
            "nickname": nickname,
            "content": content,
            "timestamp": now,
        })
        topics.add_message(current["topic_id"], bot_id, content, now, nickname)
        self.group_last_activity[group_id] = now

    # ------------------------------------------------------------------
    #  上下文 & 摘要
    # ------------------------------------------------------------------

    def get_latest_context(self, group_id: str) -> dict[str, Any] | None:
        """获取群组的最新上下文（debounce 后重新取）。"""
        if not self.is_group_allowed(group_id):
            return None

        self._ensure_topic_loaded(group_id)
        topic = self.active_topics.get(group_id)
        if not topic or not topic["messages"]:
            return None

        last_msg = topic["messages"][-1]
        return self._build_context(
            group_id, last_msg["user_id"], last_msg["content"], last_msg["timestamp"],
        )

    def get_current_topic(self, group_id: str) -> dict | None:
        if not self.is_group_allowed(group_id):
            return None
        self._ensure_topic_loaded(group_id)
        return self.active_topics.get(group_id)

    def update_summary(self, group_id: str, summary: str) -> None:
        topic = self.active_topics.get(group_id)
        if topic:
            topic["summary"] = summary
            topics.update_summary(topic["topic_id"], summary)

    # ------------------------------------------------------------------
    #  私有方法
    # ------------------------------------------------------------------

    def _ensure_topic_loaded(self, group_id: str) -> None:
        """如果内存中没有该群的话题，尝试从数据库恢复。"""
        if group_id in self.active_topics:
            return
        topic = topics.get_latest_active(group_id)
        if topic and time.time() - topic["last_msg_time"] <= _topic_gap:
            self.active_topics[group_id] = topic
            self.group_last_activity[group_id] = topic["last_msg_time"]

    def _archive_topic_sync(self, group_id: str) -> None:
        """同步归档话题（不触发 Cyber Echo，仅持久化）。"""
        topic = self.active_topics.get(group_id)
        if topic:
            topics.update_summary(
                topic["topic_id"], topic.get("summary"), topic["last_msg_time"],
            )
            del self.active_topics[group_id]

    def _build_context(
        self, group_id: str, user_id: str, content: str, now: float,
    ) -> dict[str, Any]:
        """构建传递给 LLM 的上下文字典。"""
        topic = self.active_topics[group_id]
        msgs = topic["messages"]

        # 时间间隔计算
        time_since_group = 0.0
        time_since_user = 9999.0

        if len(msgs) > 1:
            time_since_group = now - msgs[-2]["timestamp"]
            for msg in reversed(msgs[:-1]):
                if msg["user_id"] == user_id:
                    time_since_user = now - msg["timestamp"]
                    break

        # 最近 10 条消息
        recent = [
            f"{m.get('nickname') or m['user_id']}: {m['content']}"
            for m in msgs[-10:]
        ]

        # 历史话题摘要
        past = topics.get_recent(group_id, limit=5)
        past_summary = "\n".join(f"- {t['summary']}" for t in past if t["summary"])

        # 用户画像
        user_profile = users.get(group_id, user_id)
        user_desc = ""
        if user_profile and user_profile.get("description"):
            user_desc = f"Current Speaker ({user_profile['nickname']}): {user_profile['description']}"

        # 用户记忆
        user_memories = memories.get_for_context(user_id, limit=20)
        memory_section = ""
        if user_memories:
            memory_section = "User Memories:\n" + "\n".join(f"- {m}" for m in user_memories)

        return {
            "persona": config.prompts.persona,
            "recent_messages": recent,
            "topic_summary": topic.get("summary"),
            "past_topics": past_summary,
            "user_profile": user_desc,
            "user_memories": memory_section,
            "latest_message": content,
            "time_since_last_group_message": time_since_group,
            "time_since_last_user_message": time_since_user,
            "is_at_mentioned": False,           # 由 plugin 覆盖
        }


# 全局实例
topic_manager = TopicManager()
