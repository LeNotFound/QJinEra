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

    with patch("services.topic.topic_manager.switch_topic") as mock_switch:
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

    with patch("services.topic.topic_manager.switch_topic") as mock_switch:
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
