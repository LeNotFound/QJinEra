"""
身份认知与实体解析通用引擎模块。

设计原则：
- 零硬编码：Bot 的名称与别名完全由当前加载的 Persona (.ujson) 以及 config.toml 动态提供，
  更换任何角色卡（.ujson）均即时生效，绝不锁死任何特定人设。
- 动态人物解析：核心人物映射从 Persona 的 custom.identities 或数据库动态生成，
  避免代码中硬编码任何特定用户的 QQ 号或姓名。
- 通用防护：拦截将 Bot 自身作为第三人称客体沉淀的解离记忆，并自动消除公文腔。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from config import config
from logger import get_logger

logger = get_logger("Identity")

# 跨角色通用的通用机器人/系统代称（任何 AI 都适用）
GENERIC_BOT_TERMS: set[str] = {
    "机器人",
    "bot",
    "Bot",
    "BOT",
    "AI",
    "ai",
    "系统",
}


def load_active_persona() -> dict[str, Any]:
    """从配置指定的 persona_file 动态加载当前角色定义。"""
    persona_path = getattr(config.prompts, "persona_file", "")
    if not persona_path or not os.path.exists(persona_path):
        return {}
    try:
        with open(persona_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            char = raw.get("character", raw)
            if not isinstance(char, dict):
                return {}
            if "custom" not in char or not isinstance(char["custom"], dict):
                char["custom"] = {}
            return char
    except Exception as e:
        logger.error("加载 Persona 失败: %s", e)
        return {}


def get_all_bot_aliases(persona: dict[str, Any] | None = None) -> set[str]:
    """
    动态获取当前 Bot 的全部有效别名。
    来源完全由当前加载的 Persona (.ujson) 与 config.toml 驱动，零硬编码。
    """
    p = persona if persona is not None else load_active_persona()
    aliases: set[str] = set(GENERIC_BOT_TERMS)

    # 1. 来自 config.toml [bot]
    if config.bot.name:
        aliases.add(config.bot.name)
    if config.bot.english_name:
        aliases.add(config.bot.english_name)
    for a in getattr(config.bot, "aliases", []):
        if a and isinstance(a, str):
            aliases.add(a.strip())

    # 2. 来自当前 .ujson 角色定义
    if p:
        if p.get("name"):
            aliases.add(str(p["name"]).strip())
        if p.get("english_name"):
            aliases.add(str(p["english_name"]).strip())

        # 支持 character.aliases 或 character.custom.aliases
        char_aliases = p.get("aliases") or p.get("custom", {}).get("aliases") or []
        if isinstance(char_aliases, list):
            for a in char_aliases:
                if a and isinstance(a, str):
                    aliases.add(a.strip())

    return aliases


def get_configured_identities(persona: dict[str, Any] | None = None) -> dict[str, str]:
    """
    从当前 Persona 或配置中读取显式声明的核心人物映射。
    例如可以在 .ujson 的 custom.identities 中声明特定伴侣或造物主，
    换其他 ujson 则自动跟随新 ujson 的定义。
    """
    p = persona if persona is not None else load_active_persona()
    identities: dict[str, str] = {}
    if p:
        custom = p.get("custom", {})
        ids = custom.get("identities") or p.get("identities") or {}
        if isinstance(ids, dict):
            for k, v in ids.items():
                identities[str(k).strip()] = str(v).strip()
    return identities


# 模块级别名与核心身份（动态按当前配置初始化，提供向下兼容导入）
BOT_ALIASES: set[str] = get_all_bot_aliases()
CORE_IDENTITIES: dict[str, str] = get_configured_identities()
KNOWN_BOT_IDS: set[str] = {str(config.bot.admin_qq)} if config.bot.admin_qq else set()


def is_bot_self(
    name_or_id: str,
    bot_id: str = "",
    persona: dict[str, Any] | None = None,
) -> bool:
    """
    判断给定的名称或 ID 是否代表 Bot 自身。
    用于记忆提取与 World Lore 入库前的守卫过滤。
    """
    if not name_or_id:
        return False

    val = str(name_or_id).strip()
    if not val:
        return False

    # 0. 人类核心用户绝对不是 Bot
    active_identities = get_configured_identities(persona)
    if val in active_identities or val in active_identities.values():
        return False

    # 1. 匹配 Bot QQ 号
    if bot_id and val == str(bot_id).strip():
        return True
    if val in KNOWN_BOT_IDS:
        return True

    # 2. 匹配别名列表（动态获取，忽略大小写）
    all_aliases = {a.lower() for a in get_all_bot_aliases(persona)}
    val_lower = val.lower()
    if val_lower in all_aliases:
        return True

    # 3. 清除括号注释（如 "(Bot)", "（机器人）", "[系统]" 等）及常见连接符
    without_brackets = re.sub(r"[\(\[（【].*?[\)\]）】]", "", val_lower).strip()
    if without_brackets and without_brackets in all_aliases:
        return True

    # 4. 匹配常见前缀/后缀变体（例如 "机器人X"、"小X"、"BotX"、"X系统"、"X_bot"）
    target = without_brackets or val_lower
    cleaned = re.sub(r"^(?:机器人|小|bot|the)[\s_#\-\/]*", "", target).strip()
    cleaned = re.sub(r"[\s_#\-\/]*(?:机器人|bot|系统)+$", "", cleaned).strip()
    if cleaned and cleaned in all_aliases:
        return True

    return False


def is_bot_self_memory(
    content: str,
    bot_id: str = "",
    persona: dict[str, Any] | None = None,
) -> bool:
    """
    判断记忆内容是否是将 Bot 自身作为第三人称主语或客观描述的自指记忆。
    用于记忆提取入库前的守卫过滤，阻断将 Bot 沉淀为外部客体记忆（避免人格解离）。
    """
    if not content:
        return False

    text = str(content).strip()
    if not text:
        return False

    # 若内容本身就是 Bot 别名
    if is_bot_self(text, bot_id, persona):
        return True

    # 规范化前导符号
    text_clean = text.lstrip(" -*#`'\"“”‘’")
    text_lower = text_clean.lower()

    # 动态获取当前 Bot 的所有别名（降序排列，优先长词匹配）
    aliases = sorted(get_all_bot_aliases(persona), key=lambda x: len(x), reverse=True)
    valid_aliases = [a for a in aliases if a]
    if not valid_aliases:
        return False

    alias_pattern = "|".join(re.escape(a.lower()) for a in valid_aliases)

    # 匹配以 Bot 别名开头作为陈述主语的模式
    pattern = rf"^(?:(?:小|机器人|bot)[\s_#\-\/]*)?(?:{alias_pattern})(?:[\s_#\-\/]*(?:系统|机器人|bot))?"

    m = re.match(pattern, text_lower)
    if m:
        matched_end = m.end()
        # 如果整句就是别名
        if matched_end == len(text_lower):
            return True
        # 紧跟谓语、系动词、助动词、副词、标点或空格，判定为以此别名为主语的句子
        rest = text_lower[matched_end:]
        if re.match(
            r"^[\s，,：:、。.\-_/（(\[{=]|(?:[是为有]|是一个|是一套|具有|具备|拥有|支持|包含|计划|打算|准备|能够|可以|会|需要|必须|应该|目前|现在|正在|已经|确实|很|非常|真|也|处于|被|经常|在)",
            rest,
        ):
            return True

    return False


def resolve_subject_id(
    subject_id: str,
    identity_map: dict[str, str] | None = None,
    fallback_id: str = "",
) -> str:
    """
    将 LLM 提取的 subject_id / source_id 反向解析为纯数字 QQ 号。
    如果 LLM 输出的是具名（如 "Alice"、"Bob"），反查对应 QQ 号；
    如果是纯数字 QQ 则直接返回；
    若无法识别且提供了 fallback_id，则返回 fallback_id。
    """
    if not subject_id:
        return str(fallback_id).strip()

    s = str(subject_id).strip()
    if not s:
        return str(fallback_id).strip()

    # 1. 已经是纯数字 QQ
    if s.isdigit():
        return s

    # 2. 检查配置的映射表与传入的动态 identity_map
    search_map: dict[str, str] = {}
    search_map.update(get_configured_identities())
    if identity_map:
        search_map.update(identity_map)

    for qid, name in search_map.items():
        if s == str(qid):
            return str(qid)
        names = [n.strip() for n in str(name).split("/") if n.strip()]
        if s in names or any(n and n in s for n in names):
            return str(qid)

    # 3. 若传入的是非数字且有有效 fallback_id，退回 fallback_id
    if fallback_id and str(fallback_id).strip().isdigit():
        return str(fallback_id).strip()

    return s


def sanitize_memory_content(
    content: str,
    user_name: str = "",
    identity_map: dict[str, str] | None = None,
) -> str:
    """
    规范化记忆文本内容，根除机械公文腔与裸数字 QQ 指代。
    - 动态根据 identity_map / configured_identities 将裸数字 QQ 替换为具名人物称谓
    - 将 '该用户'、'该个体'、'该对象'、'此用户'、'此个体' 替换为具名名称或自然称谓
    - 去除 '(用户)'、'（用户）' 等机械公文腔后缀
    """
    if not content:
        return ""

    text = str(content).strip()
    if not text:
        return ""

    # 1. 动态替换 QQ 号为具名（从 identity_map 和当前 persona 的 identities 中取）
    active_map: dict[str, str] = {}
    active_map.update(get_configured_identities())
    if identity_map:
        active_map.update(identity_map)

    for qid, name in active_map.items():
        if qid and qid.isdigit() and name:
            clean_name = name.split("/")[0].strip()
            text = text.replace(qid, clean_name)

    # 2. 去除（用户）后缀
    text = re.sub(r"（用户）|\(用户\)", "", text)

    # 3. 具名化替换机械指代
    target_name = user_name.strip()
    if target_name:
        for term in ["该用户", "该个体", "该对象", "此用户", "此个体"]:
            text = text.replace(term, target_name)
    else:
        text = text.replace("该个体", "这个人").replace("该对象", "对方")

    return text.strip()


def build_identity_map(
    user_pairs: list[tuple[str, str]] | None = None,
    extra_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    构建合并了当前配置核心用户映射与动态会话昵称的完整身份映射表。
    """
    mapping = get_configured_identities()
    if user_pairs:
        for uid, nick in user_pairs:
            s_uid = str(uid).strip()
            s_nick = str(nick).strip()
            if s_uid and s_nick:
                if s_uid not in mapping or not mapping[s_uid]:
                    mapping[s_uid] = s_nick
    if extra_map:
        for k, v in extra_map.items():
            if k and v:
                mapping[str(k).strip()] = str(v).strip()
    return mapping
