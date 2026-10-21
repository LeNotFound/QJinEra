"""
Unit tests for services/commands.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from models.message import MessageContent
from services.commands import handle_command, register_command


class MockEvent:
    def __init__(self, group_id: str = "12345"):
        self.group_id = group_id
        self.reply = AsyncMock()


@pytest.mark.asyncio
async def test_non_command():
    event = MockEvent()
    content = MessageContent(text="Hello world")
    result = await handle_command(event, content)
    assert result is False
    event.reply.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_command():
    event = MockEvent()
    content = MessageContent(text="/nonexistent_command_12345")
    result = await handle_command(event, content)
    assert result is False
    event.reply.assert_not_called()


@pytest.mark.asyncio
async def test_clear_command():
    event = MockEvent(group_id="999888")
    content = MessageContent(text="/clear")

    with patch("services.topic.topic_manager.switch_topic", new_callable=AsyncMock) as mock_switch:
        result = await handle_command(event, content)
        assert result is True
        mock_switch.assert_called_once_with("999888")
        event.reply.assert_called_once_with("已清空当前群聊话题的短期上下文。")


@pytest.mark.asyncio
async def test_custom_command_registration():
    event = MockEvent()
    custom_called = False

    @register_command("/testping")
    async def _cmd_ping(ev, args):
        nonlocal custom_called
        custom_called = True
        await ev.reply(f"pong {args}".strip())

    content = MessageContent(text="/testping now")
    result = await handle_command(event, content)
    assert result is True
    assert custom_called is True
    event.reply.assert_called_once_with("pong now")


@pytest.mark.asyncio
async def test_command_without_slash_in_decorator():
    event = MockEvent()

    @register_command("testnoprefix")
    async def _cmd_noprefix(ev, args):
        await ev.reply("no prefix registered")

    content = MessageContent(text="/testnoprefix")
    assert await handle_command(event, content) is True
    event.reply.assert_called_once_with("no prefix registered")


@pytest.mark.asyncio
async def test_command_with_at_prefix_and_fullwidth():
    event = MockEvent(group_id="111222")

    with patch("services.topic.topic_manager.switch_topic", new_callable=AsyncMock) as mock_switch:
        # Preceded by @ mention
        assert await handle_command(event, "[@123456] /clear") is True
        mock_switch.assert_called_with("111222")

        # Full-width slash
        assert await handle_command(event, "／clear") is True


@pytest.mark.asyncio
async def test_command_exception_handled():
    event = MockEvent()

    @register_command("/failcmd")
    async def _cmd_fail(ev, args):
        raise RuntimeError("Something blew up")

    # Command should not crash handle_command, should log and reply failure
    assert await handle_command(event, "/failcmd") is True
    event.reply.assert_called_once_with("执行命令 /failcmd 失败: Something blew up")


@pytest.mark.asyncio
async def test_lore_list_empty():
    event = MockEvent(group_id="111")
    with patch("services.storage.world_lore.get_all", new_callable=AsyncMock, return_value=[]):
        assert await handle_command(event, "/lore list") is True
        event.reply.assert_called_once_with("当前群组暂无记录的世界观设定。")


@pytest.mark.asyncio
async def test_lore_list_with_items():
    event = MockEvent(group_id="111")
    items = [
        {"entity_name": "奶黄包", "description": "一只可爱的橘猫", "scope": "group"},
        {"entity_name": "心岛", "description": "交友软件", "scope": "global"},
    ]
    with patch("services.storage.world_lore.get_all", new_callable=AsyncMock, return_value=items):
        assert await handle_command(event, "/lore") is True
        reply_text = event.reply.call_args[0][0]
        assert "奶黄包" in reply_text
        assert "心岛" in reply_text
        assert "[全局]" in reply_text


@pytest.mark.asyncio
async def test_lore_del_success_and_not_found():
    event = MockEvent(group_id="111")

    # Success case
    with patch("services.storage.world_lore.delete", new_callable=AsyncMock, return_value=True) as mock_del:
        assert await handle_command(event, "/lore del 奶黄包") is True
        mock_del.assert_called_once_with("111", "奶黄包")
        event.reply.assert_called_with("已成功删除世界观设定「奶黄包」。")

    # Not found case
    event.reply.reset_mock()
    with patch("services.storage.world_lore.delete", new_callable=AsyncMock, return_value=False):
        assert await handle_command(event, "/lore del 未知设定") is True
        event.reply.assert_called_with("未找到名为「未知设定」的世界观设定。")


@pytest.mark.asyncio
async def test_lore_add_normal_and_bot_self():
    event = MockEvent(group_id="111")
    event.user_id = "67890"

    # Reject bot self-reference
    assert await handle_command(event, "/lore add 年年 这是一个机器人") is True
    event.reply.assert_called_with("「年年」属于机器人的自指别名，禁止添加为外部世界观设定。")

    event.reply.reset_mock()
    # Normal lore addition
    with patch("services.storage.world_lore.add_or_update", new_callable=AsyncMock) as mock_add:
        assert await handle_command(event, "/lore add 深渊副本 只能三个人打") is True
        mock_add.assert_called_once_with("111", "67890", "深渊副本", "只能三个人打")
        event.reply.assert_called_with("已成功保存世界观设定「深渊副本」。")


@pytest.mark.asyncio
async def test_forget_command():
    event = MockEvent(group_id="111")

    # Empty keyword
    assert await handle_command(event, "/forget") is True
    event.reply.assert_called_with("用法: /forget <关键词> (将遗忘并归档包含该关键词的活跃记忆)")

    # Hit 2 memories
    event.reply.reset_mock()
    with patch("services.storage.memories.forget_by_keyword", new_callable=AsyncMock, return_value=2) as mock_forget:
        assert await handle_command(event, "/forget 讨厌吃香菜") is True
        mock_forget.assert_called_once_with("111", "讨厌吃香菜")
        event.reply.assert_called_with("已成功遗忘并归档 2 条包含「讨厌吃香菜」的记忆。")


@pytest.mark.asyncio
async def test_lore_add_global():
    event = MockEvent(group_id="111")
    event.user_id = "67890"
    with patch("services.storage.world_lore.add_or_update", new_callable=AsyncMock) as mock_add:
        assert await handle_command(event, "/lore add --global 跨群常识 这是公共世界观") is True
        mock_add.assert_called_once_with("111", "67890", "跨群常识", "这是公共世界观", scope="global")
        event.reply.assert_called_with("已成功保存全局世界观设定「跨群常识」。")


@pytest.mark.asyncio
async def test_forget_del_and_list():
    event = MockEvent(group_id="111")

    # /forget del
    with patch("services.storage.memories.delete_by_keyword", new_callable=AsyncMock, return_value=3) as mock_del:
        assert await handle_command(event, "/forget del 错误记忆") is True
        mock_del.assert_called_once_with("111", "错误记忆")
        event.reply.assert_called_with("已彻底删除 3 条包含「错误记忆」的记忆。")

    # /forget list
    event.reply.reset_mock()
    items = [
        {"status": "active", "subject_id": "67890", "content": "喜欢吃蛋糕"},
        {"status": "archived", "subject_id": "67890", "content": "买了一个蛋糕"},
    ]
    with patch("services.storage.memories.get_by_keyword", new_callable=AsyncMock, return_value=items) as mock_list:
        assert await handle_command(event, "/forget list 蛋糕") is True
        mock_list.assert_called_once_with("111", "蛋糕")
        reply_text = event.reply.call_args[0][0]
        assert "【包含「蛋糕」的记忆" in reply_text
        assert "喜欢吃蛋糕" in reply_text


@pytest.mark.asyncio
async def test_profile_command():
    event = MockEvent(group_id="111")
    event.user_id = "10001"

    # 1. 查询画像
    with patch("services.storage.users.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"nickname": "Alice", "description": "一名优秀的开发者"}
        assert await handle_command(event, "/profile") is True
        event.reply.assert_called_with("【用户画像 (Alice - 10001)】\n一名优秀的开发者")

    # 2. 重置画像
    event.reply.reset_mock()
    with patch("services.storage.users.update_description", new_callable=AsyncMock) as mock_update:
        assert await handle_command(event, "/profile reset") is True
        mock_update.assert_called_once_with("111", "10001", "")
        event.reply.assert_called_with("已成功清空用户 10001 的长期画像。")

    # 3. 设置画像
    event.reply.reset_mock()
    with patch("services.storage.users.update_description", new_callable=AsyncMock) as mock_update:
        assert await handle_command(event, "/profile set 喜欢写优雅代码的技术宅") is True
        mock_update.assert_called_once_with("111", "10001", "喜欢写优雅代码的技术宅")
        event.reply.assert_called_with("已成功更新用户 10001 的长期画像。")
