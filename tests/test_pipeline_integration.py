"""
Integration tests for storage, topic_manager, and core plugin pipeline.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alicebot.adapter.cqhttp.event import GroupMessageEvent

from models.message import MessageContent
from plugins.core import QJinEraPlugin
from services.scheduler import _get_ready_adapter, _init_groups
from services.storage import database, topics
from services.topic import TopicManager


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_qjinera.db"
    monkeypatch.setattr(database, "_DB_PATH", str(test_db))
    # Initialize DB schema
    await database.init_db()
    yield test_db


@pytest.mark.asyncio
async def test_storage_topics_message_content():
    now = time.time()
    t_id = await topics.create("1001", now)
    assert t_id > 0

    mc = MessageContent(text="Hello from storage test", images=["img1.jpg"])
    await topics.add_message(t_id, "user_123", mc, now, "TestUser")

    active_topic = await topics.get_latest_active("1001")
    assert active_topic is not None
    assert active_topic["topic_id"] == t_id
    assert len(active_topic["messages"]) == 1

    msg = active_topic["messages"][0]
    assert msg["user_id"] == "user_123"
    assert msg["nickname"] == "TestUser"
    assert isinstance(msg["content"], MessageContent)
    assert msg["content"].text == "Hello from storage test"
    assert msg["content"].images == ["img1.jpg"]


@pytest.mark.asyncio
async def test_topic_manager_pipeline():
    with patch("services.topic.TopicManager.is_group_allowed", return_value=True):
        tm = TopicManager()
        group_id = "2002"
        user_id = "user_456"
        bot_id = "bot_999"

        mc = MessageContent(text="Topic manager pipeline test")
        ctx = await tm.handle_message(group_id, user_id, mc, "Alice", bot_id)
        assert ctx is not None
        assert ctx["latest_message"] == "Topic manager pipeline test"
        assert len(ctx["recent_messages"]) == 1
        assert "Alice: Topic manager pipeline test" in ctx["recent_messages"][0]

        # Add bot message
        await tm.add_bot_message(group_id, "Bot response text", bot_id, "QJinEra")
        current = await tm.get_current_topic(group_id)
        assert current is not None
        assert len(current["messages"]) == 2
        assert isinstance(current["messages"][-1]["content"], MessageContent)
        assert current["messages"][-1]["content"].text == "Bot response text"

        # Switch topic
        await tm.switch_topic(group_id)
        new_topic = await tm.get_current_topic(group_id)
        assert new_topic is not None
        assert new_topic["topic_id"] != current["topic_id"]
        # The last message is migrated to the new topic
        assert len(new_topic["messages"]) == 1
        assert new_topic["messages"][0]["content"].text == "Bot response text"


@pytest.mark.asyncio
async def test_core_plugin_command_interception():
    # Construct a mock event representing /clear command
    event = AsyncMock(spec=GroupMessageEvent)
    event.group_id = 12345
    event.user_id = 99999
    event.message = "/clear"
    event.sender = AsyncMock()
    event.sender.nickname = "AdminUser"
    event.self_id = 1106447644
    event.reply = AsyncMock()

    plugin = QJinEraPlugin()
    plugin.event = event

    # Pre-populate active debounce and at-tasks to ensure /clear cancels them
    mock_debounce = MagicMock()
    mock_debounce.done.return_value = False
    mock_at = MagicMock()
    mock_at.done.return_value = False
    plugin._debounce_tasks["12345"] = mock_debounce
    plugin._at_tasks["12345"] = mock_at

    with patch("services.topic.topic_manager.is_group_allowed", return_value=True), \
         patch("services.topic.topic_manager.switch_topic", new_callable=AsyncMock) as mock_switch:
        await plugin.handle()
        mock_switch.assert_called_once_with("12345")
        event.reply.assert_called_once_with("已清空当前群聊话题的短期上下文。")
        mock_debounce.cancel.assert_called()
        mock_at.cancel.assert_called()
        assert "12345" not in plugin._debounce_tasks
        assert "12345" not in plugin._at_tasks


@pytest.mark.asyncio
async def test_core_plugin_at_mention_flow():
    # Construct a mock event where bot is @'d
    bot_id = 1106447644
    event = AsyncMock(spec=GroupMessageEvent)
    event.group_id = 12345
    event.user_id = 88888
    event.message = f"[CQ:at,qq={bot_id}] 早上好呀"
    event.sender = AsyncMock()
    event.sender.nickname = "Bob"
    event.self_id = bot_id
    event.reply = AsyncMock()

    plugin = QJinEraPlugin()
    plugin.event = event

    with patch("services.topic.topic_manager.is_group_allowed", return_value=True), \
         patch.object(plugin, "_respond", new_callable=AsyncMock) as mock_respond, \
         patch.object(plugin, "_extract_user_memories", new_callable=AsyncMock) as mock_extract:

        await plugin.handle()
        # Should have scheduled an at_task
        assert "12345" in plugin._at_tasks
        await plugin._at_tasks["12345"]
        mock_respond.assert_called_once()
        assert mock_extract.called


@pytest.mark.asyncio
async def test_scheduler_adapter_readiness():
    bot = MagicMock()
    mock_adapter = MagicMock()
    # Case 1: adapter has no websocket (NapCat not connected yet)
    mock_adapter.websocket = None
    bot.adapters = [mock_adapter]

    assert _get_ready_adapter(bot) is None
    # Must not raise AssertionError
    success = await _init_groups(bot)
    assert success is False

    # Case 2: adapter has active websocket
    mock_ws = MagicMock()
    mock_ws.closed = False
    mock_adapter.websocket = mock_ws
    mock_adapter.call_api = AsyncMock(return_value=[{"group_id": 99999, "group_name": "TestGroup"}])

    assert _get_ready_adapter(bot) is mock_adapter
    with patch("services.topic.topic_manager.is_group_allowed", return_value=True):
        success = await _init_groups(bot)
        assert success is True
        mock_adapter.call_api.assert_called_once_with("get_group_list")
