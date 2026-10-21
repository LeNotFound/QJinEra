"""
指令路由与处理服务。

将群聊命令（如 /clear, /lore, /forget 等）从核心事件流中解耦出来，支持前缀匹配、注册装饰器及统一拦截。
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from logger import get_logger
from models.message import MessageContent
from services.identity import is_bot_self
from services.storage import memories, users as user_store, world_lore
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
    group_id = str(getattr(event, "group_id", ""))
    await topic_manager.switch_topic(group_id)
    await event.reply("已清空当前群聊话题的短期上下文。")
    logger.info("群 %s 执行 /clear 命令，已切换并重置话题短期上下文", group_id)


@register_command("/lore")
@register_command("/worldlore")
async def _cmd_lore(event: Any, args: str) -> None:
    """群世界观设定管理指令。
    用法:
        /lore list - 查看当前群组世界观列表
        /lore del <实体名> - 删除指定世界观设定
        /lore add <实体名> <描述> - 添加/更新世界观设定
    """
    group_id = str(getattr(event, "group_id", ""))
    user_id = str(getattr(event, "user_id", "admin"))
    sub_parts = args.strip().split(maxsplit=2)
    subcmd = sub_parts[0].lower() if sub_parts else "list"

    if subcmd in ("list", "ls", "show_all", ""):
        lores = await world_lore.get_all(group_id)
        if not lores:
            await event.reply("当前群组暂无记录的世界观设定。")
            return

        lines = [f"【当前群组世界观设定 (共 {len(lores)} 条)】"]
        for idx, item in enumerate(lores, 1):
            scope_tag = " [全局]" if item.get("scope") == "global" else ""
            desc = item["description"]
            if len(desc) > 60:
                desc = desc[:57] + "..."
            lines.append(f"{idx}. [{item['entity_name']}]{scope_tag}: {desc}")
        await event.reply("\n".join(lines))
        logger.info("群 %s 查看世界观列表，共 %d 条", group_id, len(lores))

    elif subcmd in ("del", "delete", "rm", "remove"):
        if len(sub_parts) < 2:
            await event.reply("用法: /lore del <实体名>")
            return
        entity_name = sub_parts[1].strip()
        success = await world_lore.delete(group_id, entity_name)
        if success:
            await event.reply(f"已成功删除世界观设定「{entity_name}」。")
            logger.info("群 %s 删除了世界观设定「%s」", group_id, entity_name)
        else:
            await event.reply(f"未找到名为「{entity_name}」的世界观设定。")

    elif subcmd in ("add", "set"):
        # 支持 /lore add [--global] <实体名> <描述>
        rest_tokens = sub_parts[1:]
        scope = "group"
        if rest_tokens and rest_tokens[0].lower() in ("--global", "-g"):
            scope = "global"
            rest_tokens = rest_tokens[1].split(maxsplit=1) if len(rest_tokens) > 1 else []

        if len(rest_tokens) < 2:
            await event.reply("用法: /lore add [--global] <实体名> <描述>")
            return
        entity_name = rest_tokens[0].strip()
        description = rest_tokens[1].strip()

        if is_bot_self(entity_name):
            await event.reply(f"「{entity_name}」属于机器人的自指别名，禁止添加为外部世界观设定。")
            return

        if scope == "global":
            await world_lore.add_or_update(group_id, user_id, entity_name, description, scope="global")
            await event.reply(f"已成功保存全局世界观设定「{entity_name}」。")
        else:
            await world_lore.add_or_update(group_id, user_id, entity_name, description)
            await event.reply(f"已成功保存世界观设定「{entity_name}」。")
        logger.info("群 %s 添加/更新[%s]世界观设定「%s」", group_id, scope, entity_name)

    else:
        await event.reply(
            "【世界观设定管理指令帮助】\n"
            "/lore list - 查看当前群组世界观列表\n"
            "/lore del <实体名> - 删除指定世界观设定\n"
            "/lore add [--global] <实体名> <描述> - 添加/更新世界观设定"
        )


@register_command("/forget")
async def _cmd_forget(event: Any, args: str) -> None:
    """遗忘/归档记忆指令。
    用法:
        /forget <关键词> - 遗忘并归档包含该关键词的活跃记忆
        /forget del <关键词> - 彻底删除包含该关键词的记忆
        /forget list <关键词> - 预览包含该关键词的记忆列表
    """
    cleaned = args.strip()
    if not cleaned:
        await event.reply("用法: /forget <关键词> (将遗忘并归档包含该关键词的活跃记忆)")
        return

    group_id = str(getattr(event, "group_id", ""))
    sub_parts = cleaned.split(maxsplit=1)
    subcmd = sub_parts[0].lower()

    if subcmd in ("del", "delete", "rm", "remove", "--hard"):
        if len(sub_parts) < 2:
            await event.reply("用法: /forget del <关键词>")
            return
        target_kw = sub_parts[1].strip()
        count = await memories.delete_by_keyword(group_id, target_kw)
        if count > 0:
            await event.reply(f"已彻底删除 {count} 条包含「{target_kw}」的记忆。")
            logger.info("群 %s 执行 /forget del「%s」，彻底删除了 %d 条记忆", group_id, target_kw, count)
        else:
            await event.reply(f"未找到包含「{target_kw}」的记忆。")

    elif subcmd in ("list", "ls", "search"):
        if len(sub_parts) < 2:
            await event.reply("用法: /forget list <关键词>")
            return
        target_kw = sub_parts[1].strip()
        items = await memories.get_by_keyword(group_id, target_kw)
        if not items:
            await event.reply(f"未找到包含「{target_kw}」的记忆。")
            return
        lines = [f"【包含「{target_kw}」的记忆 (共 {len(items)} 条)】"]
        for idx, item in enumerate(items, 1):
            st = item.get("status", "active")
            content = item.get("content", "")
            if len(content) > 50:
                content = content[:47] + "..."
            lines.append(f"{idx}. [{st}] (对象:{item.get('subject_id')}): {content}")
        await event.reply("\n".join(lines))

    else:
        # 默认模式：按关键词归档
        keyword = cleaned
        count = await memories.forget_by_keyword(group_id, keyword)
        if count > 0:
            await event.reply(f"已成功遗忘并归档 {count} 条包含「{keyword}」的记忆。")
            logger.info("群 %s 执行 /forget「%s」，归档了 %d 条记忆", group_id, keyword, count)
        else:
            await event.reply(f"未找到包含「{keyword}」的活跃记忆。")


@register_command("/profile")
@register_command("/userprofile")
async def _cmd_profile(event: Any, args: str) -> None:
    """用户画像管理指令。
    用法:
        /profile - 查看自己在当前群的长期画像
        /profile <QQ号> - 查看指定用户的长期画像
        /profile reset [QQ号] - 重置/清空指定用户或自己的长期画像
        /profile set <新画像描述> - 手动更新自己的长期画像
    """
    group_id = str(getattr(event, "group_id", ""))
    caller_uid = str(getattr(event, "user_id", ""))
    cleaned = args.strip()
    sub_parts = cleaned.split(maxsplit=1)
    subcmd = sub_parts[0].lower() if sub_parts else ""

    if subcmd in ("reset", "clear"):
        target_uid = sub_parts[1].strip() if len(sub_parts) > 1 else caller_uid
        if not target_uid:
            await event.reply("用法: /profile reset [QQ号]")
            return
        await user_store.update_description(group_id, target_uid, "")
        await event.reply(f"已成功清空用户 {target_uid} 的长期画像。")
        logger.info("群 %s 用户 %s 清空了 %s 的长期画像", group_id, caller_uid, target_uid)

    elif subcmd in ("set", "update"):
        if len(sub_parts) < 2:
            await event.reply("用法: /profile set <新画像描述>")
            return
        new_desc = sub_parts[1].strip()
        await user_store.update_description(group_id, caller_uid, new_desc)
        await event.reply(f"已成功更新用户 {caller_uid} 的长期画像。")
        logger.info("群 %s 更新了用户 %s 的长期画像", group_id, caller_uid)

    else:
        # 查询画像
        target_uid = cleaned if cleaned.isdigit() else caller_uid
        if not target_uid:
            await event.reply("无法获取当前用户 ID。")
            return
        user_info = await user_store.get(group_id, target_uid)
        desc = (user_info.get("description") if user_info else "") or ""
        nick = (user_info.get("nickname") if user_info else "") or target_uid
        if desc.strip():
            await event.reply(f"【用户画像 ({nick} - {target_uid})】\n{desc.strip()}")
        else:
            await event.reply(f"用户 {nick} ({target_uid}) 暂无长期画像。")


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
