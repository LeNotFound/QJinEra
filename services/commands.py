"""
指令路由与处理服务。

将群聊命令（如 /clear 等）从核心事件流中解耦出来，支持前缀匹配、注册装饰器及统一拦截。
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from logger import get_logger
from models.message import MessageContent
from services.topic import topic_manager

logger = get_logger("Commands")

CommandHandler = Callable[[Any, str], Awaitable[None]]

_COMMAND_REGISTRY: dict[str, CommandHandler] = {}


def register_command(name: str):
    """注册命令处理函数的装饰器。"""
    def decorator(func: CommandHandler) -> CommandHandler:
        cmd_key = name.lower().strip()
        if not cmd_key.startswith("/"):
            cmd_key = "/" + cmd_key
        _COMMAND_REGISTRY[cmd_key] = func
        return func
    return decorator


@register_command("/clear")
async def _cmd_clear(event: Any, args: str) -> None:
    """清空当前群聊话题的短期上下文。"""
    group_id = str(event.group_id)
    topic_manager.switch_topic(group_id)
    await event.reply("已清空当前群聊话题的短期上下文。")
    logger.info("群 %s 执行 /clear 命令，已切换并重置话题短期上下文", group_id)


async def handle_command(event: Any, content: MessageContent | str | None) -> bool:
    """
    检查消息是否为群指令并进行路由执行。

    Args:
        event: GroupMessageEvent 或包含 group_id 及 reply 方法的事件对象
        content: MessageContent 实例、文本字符串或 None

    Returns:
        bool: 若命中命令并成功执行返回 True，否则返回 False。
    """
    if content is None:
        return False

    if isinstance(content, MessageContent):
        raw_text = content.text.strip()
    else:
        raw_text = str(content).strip()

    # 规范化：去除可能的前置 @ 提及（如在群里 @机器人 /clear）
    raw_text = re.sub(r"^(\[@(?:\d+|all)\]\s*)+", "", raw_text).strip()
    # 兼容中文全角斜杠
    if raw_text.startswith("／"):
        raw_text = "/" + raw_text[1:]

    if not raw_text.startswith("/"):
        return False

    parts = raw_text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    handler = _COMMAND_REGISTRY.get(cmd)
    if handler:
        try:
            await handler(event, args)
        except Exception as e:
            logger.error("执行命令 %s 失败: %s", cmd, e, exc_info=True)
            try:
                await event.reply(f"执行命令 {cmd} 失败: {e}")
            except Exception:
                pass
        return True

    return False
