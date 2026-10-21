"""
LLM 服务 — 封装所有与大模型的交互。

职责：Judge 判定 / Writer 生成 / 记忆提取 / 记忆巩固 (Cyber Echo)。
"""

from __future__ import annotations

import ast
import datetime
import json
import re
import time
from typing import Any

import openai
from jinja2 import Environment, FileSystemLoader
from tenacity import AsyncRetrying, stop_after_attempt, retry_if_exception, wait_fixed

from config import config
from logger import get_logger
from services.identity import get_all_bot_aliases

logger = get_logger("LLM")

# ---------------------------------------------------------------------------
#  从配置中一次性读取（运行时不再访问 config）
# ---------------------------------------------------------------------------

_api_key: str = config.llm.api_key
_api_base: str = config.llm.api_base
_proxy: str | None = config.llm.proxy
_timeout: float = config.llm.timeout
_maxtries: int = config.llm.maxtries
_judge_model: str = config.llm.judge_model
_chat_model: str = config.llm.chat_model

_prompts_config = config.prompts
_bot_id: str = str(config.bot.admin_qq)  # Bot 自身的 QQ 号，用于 Prompt 中过滤自身发言

# ---------------------------------------------------------------------------
#  Jinja2 模板与 Persona 加载
# ---------------------------------------------------------------------------

# 初始化 Jinja2 环境
jinja_env = Environment(loader=FileSystemLoader("."))

try:
    with open(_prompts_config.persona_file, "r", encoding="utf-8") as f:
        _raw_persona = json.load(f)
        # 支持 UPEX 协议格式，如果不是则退回兼容模式
        _persona_data = _raw_persona.get("character", _raw_persona)
        if "custom" not in _persona_data:
            _persona_data["custom"] = {}
except Exception as e:
    logger.error("加载 Persona 文件失败: %s", e)
    _persona_data = {}

# 预加载模板
judge_template = jinja_env.get_template(_prompts_config.judge_system_file)
chat_template = jinja_env.get_template(_prompts_config.chat_system_file)
proactive_template = jinja_env.get_template(_prompts_config.proactive_system_file)
memory_consolidator_template = jinja_env.get_template(_prompts_config.memory_consolidator_system_file)
memory_extractor_template = jinja_env.get_template(_prompts_config.memory_extractor_system_file)
group_consolidator_template = jinja_env.get_template(_prompts_config.group_consolidator_system_file)


_client = openai.AsyncOpenAI(
    api_key=_api_key,
    base_url=_api_base,
    timeout=_timeout,
    http_client=openai.DefaultAsyncHttpxClient(proxy=_proxy) if _proxy else None,
)


# ---------------------------------------------------------------------------
#  内部工具
# ---------------------------------------------------------------------------

def _is_503_error(e: BaseException) -> bool:
    """检查是否为 503 错误以决定是否重试"""
    if isinstance(e, openai.APIStatusError) and e.status_code == 503:
        logger.warning(f"检测到 503 错误，准备重试: {e}")
        return True
    return False

def _extract_json_container(text: str) -> str:
    """从可能混有 Markdown 代码块、前后说明文字的内容中，精确提取最外层的 JSON 结构（对象 {...} 或数组 [...]）。"""
    stripped = text.strip()

    # 1. 若最外层被 Markdown 代码块包裹，去除首尾代码块标记
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        last_fence = stripped.rfind("```")
        if last_fence > 0 and first_newline != -1 and first_newline < last_fence:
            stripped = stripped[first_newline + 1 : last_fence].strip()

    # 2. 寻找第一个有效 JSON 容器的起始符（{ 或 [）
    start_brace = stripped.find("{")
    start_bracket = stripped.find("[")

    if start_brace == -1 and start_bracket == -1:
        return stripped

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        open_char, close_char = "{", "}"
        start_idx = start_brace
    else:
        open_char, close_char = "[", "]"
        start_idx = start_bracket

    # 3. 具有字符串字面量感知的括号计数器，精确定位最外层匹配的闭合符号
    depth = 0
    in_string = False
    escape = False
    end_idx = -1

    for idx in range(start_idx, len(stripped)):
        ch = stripped[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    end_idx = idx
                    break

    if end_idx != -1:
        return stripped[start_idx : end_idx + 1]
    return stripped[start_idx:]


def _clean_json_syntax(text: str) -> str:
    """在保持所有字符串字面量（包含转义引号与内部 URL/符号）完好无损的前提下，
    修复 JSON 结构外部的非法语法：
    - 剥离 // 行注释与 /* */ 块注释（不误伤字符串内的 http://）
    - 修复正数前带加号的非法数字（如 : +1.0, [ +2, , +5 -> : 1.0, [ 2, , 5）
    - 修复缺少前导 0 的小数（如 : +.5, : .5 -> : 0.5）
    - 修复尾随逗号（如 , } -> }, , ] -> ]）
    - 修复 Python 命名常量（如 True -> true, False -> false, None -> null）
    """
    segments: list[tuple[bool, str]] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    curr_chunk: list[str] = []

    while i < n:
        c = text[i]
        if in_string:
            curr_chunk.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
                segments.append((True, "".join(curr_chunk)))
                curr_chunk = []
            i += 1
        else:
            if c == '"':
                if curr_chunk:
                    segments.append((False, "".join(curr_chunk)))
                    curr_chunk = []
                in_string = True
                curr_chunk.append(c)
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                # 单行注释，跳到行尾
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                # 块注释，跳到 */
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                curr_chunk.append(c)
                i += 1

    if curr_chunk:
        segments.append((in_string, "".join(curr_chunk)))

    # 阶段 2：仅对非字符串片段进行语法修复
    repaired_parts: list[str] = []
    for is_str, chunk in segments:
        if is_str:
            repaired_parts.append(chunk)
        else:
            # 修复 +数字 与前导 0 缺失
            chunk = re.sub(r"\+\s*(\.\d+(?:[eE][+-]?\d+)?)", r"0\1", chunk)
            chunk = re.sub(r"\+\s*(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", r"\1", chunk)
            chunk = re.sub(r"([:\[,]\s*)\.(\d+)", r"\g<1>0.\2", chunk)

            # 修复 Python 风格字面量 True/False/None
            chunk = re.sub(r"\bTrue\b", "true", chunk)
            chunk = re.sub(r"\bFalse\b", "false", chunk)
            chunk = re.sub(r"\bNone\b", "null", chunk)

            # 修复尾随逗号 (如 , } 或 , ])
            chunk = re.sub(r",+\s*([}\]])", r"\1", chunk)

            repaired_parts.append(chunk)

    return "".join(repaired_parts).strip()


def _repair_json(content: str) -> str:
    """对 LLM 返回的潜在非标准 JSON 字符串进行容错修复。"""
    container = _extract_json_container(content)
    return _clean_json_syntax(container)


def _parse_json(content: str) -> Any:
    """尝试解析 JSON，若失败则经由 _repair_json 修复后再次解析。"""
    try:
        return json.loads(content)
    except Exception:
        pass

    repaired = _repair_json(content)
    try:
        return json.loads(repaired, strict=False)
    except Exception:
        pass

    # 尝试处理单引号 Python 字典格式（某些轻量模型可能输出 Python 字典表示）
    try:
        eval_candidate = re.sub(r"\btrue\b", "True", repaired)
        eval_candidate = re.sub(r"\bfalse\b", "False", eval_candidate)
        eval_candidate = re.sub(r"\bnull\b", "None", eval_candidate)
        evaluated = ast.literal_eval(eval_candidate)
        if isinstance(evaluated, (dict, list)):
            return evaluated
    except Exception:
        pass

    return json.loads(repaired, strict=False)


async def _call(
    model: str,
    system_prompt: str,
    user_content: str,
    images: list[str] = None,
    *,
    json_mode: bool = True,
) -> dict[str, Any] | str | None:
    """统一的 LLM 调用入口。"""
    logger.debug(
        "请求 %s ... system_prompt 长度: %d, user_content 长度: %d\n完整 user_content:\n%s",
        model,
        len(system_prompt),
        len(user_content),
        user_content,
    )

    images = images or []
    if images:
        message_content = [{"type": "text", "text": user_content}]
        for b64 in images:
            message_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}"
                }
            })
    else:
        message_content = user_content

    # 1. 模型 API 请求
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_maxtries),
            retry=retry_if_exception(_is_503_error),
            wait=wait_fixed(1),
            reraise=True,
        ):
            with attempt:
                resp = await _client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message_content},
                    ],
                    response_format={"type": "json_object"} if json_mode else None,
                )
                if not resp.choices:
                    content = ""
                else:
                    content = resp.choices[0].message.content or ""
                logger.debug("响应 (%s): %s", model, content)
    except Exception as e:
        logger.error("LLM API 请求失败 (%s): %s", model, e, exc_info=True)
        return None

    if not json_mode:
        return content

    # 2. JSON 内容解析与容错修复
    if not content:
        logger.error("LLM 返回内容为空 (%s)", model)
        return None

    try:
        return _parse_json(content)
    except Exception:
        logger.error(
            "LLM 返回内容 JSON 解析失败 (%s)。原始内容:\n%s",
            model,
            content,
            exc_info=True,
        )
        return None


def _format_ts(ts: float) -> str:
    """将 Unix 时间戳转为可读字符串。"""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
#  公开 API
# ---------------------------------------------------------------------------

def _sanitize_bot_status(status: Any) -> dict[str, Any] | None:
    """对传入模板的 bot_status 字典进行容错与类型安全规范化。"""
    if not isinstance(status, dict):
        return None
    st = status.copy()
    if "energy" in st and (st["energy"] is None or not isinstance(st["energy"], (int, float))):
        try:
            st["energy"] = float(st["energy"])
        except (ValueError, TypeError):
            st["energy"] = 100.0
    return st


async def judge_interruption(context: dict[str, Any]) -> dict[str, Any]:
    """调用 Judge 模型判断是否插话。"""
    ctx = context.copy()
    bot_id = ctx.get("bot_id", "")
    bot_status = _sanitize_bot_status(ctx.pop("bot_status", None))
    group_context = ctx.pop("group_context", None) or {}
    recent_images = ctx.pop("recent_images", [])

    system_prompt = judge_template.render(
        persona=_persona_data,
        bot_id=bot_id,
        group_context=group_context,
        bot_status=bot_status,
    )
    return await _call(
        _judge_model,
        system_prompt,
        json.dumps(ctx, ensure_ascii=False),
        images=recent_images,
    )


async def generate_chat(context: dict[str, Any]) -> dict[str, Any]:
    """调用 Writer 模型生成聊天回复。"""
    # 提取给 Jinja 的变量，避免未定义错误
    ctx = context.copy()
    user_profile = ctx.pop("user_profile_raw", {}) or {}
    world_lore = ctx.pop("world_lore", None) or {}
    group_context = ctx.pop("group_context", None) or {}
    recent_images = ctx.pop("recent_images", [])

    raw_bot_status = ctx.pop("bot_status", None) or {"energy": 100.0, "mood": "平静"}
    bot_status = _sanitize_bot_status(raw_bot_status) or {"energy": 100.0, "mood": "平静"}

    intervention_reason = ctx.pop("intervention_reason", "")
    circuit_breaker_directive = ctx.pop("circuit_breaker_directive", "")
    focus_user = ctx.pop("focus_user", bot_status.get("focus_user", ""))
    empathy_mood = ctx.pop("empathy_mood", bot_status.get("empathy_mood", ""))
    cur_objective = ctx.pop("cur_objective", bot_status.get("cur_objective", ""))

    if focus_user and not bot_status.get("focus_user"):
        bot_status["focus_user"] = focus_user
    if empathy_mood and not bot_status.get("empathy_mood"):
        bot_status["empathy_mood"] = empathy_mood
    if cur_objective and not bot_status.get("cur_objective"):
        bot_status["cur_objective"] = cur_objective

    system_prompt = chat_template.render(
        persona=_persona_data,
        bot_aliases=sorted(list(get_all_bot_aliases(_persona_data))),
        bot_status=bot_status,
        user_profile=user_profile,
        world_lore=world_lore,
        group_context=group_context,
        intervention_reason=intervention_reason,
        circuit_breaker_directive=circuit_breaker_directive,
        focus_user=focus_user,
        empathy_mood=empathy_mood,
        cur_objective=cur_objective,
    )

    return await _call(
        _chat_model,
        system_prompt,
        json.dumps(ctx, ensure_ascii=False),
        images=recent_images,
    )


async def generate_proactive_topic(bot_status: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成主动话题（冷场时使用）。"""
    sanitized_status = _sanitize_bot_status(bot_status)
    system_prompt = proactive_template.render(
        persona=_persona_data,
        bot_status=sanitized_status,
    )
    return await _call(
        _chat_model,
        system_prompt,
        "请开始你的表演",
    )


async def extract_memories(
    recent_messages: list[str],
    active_memories: list[str] = None,
    identity_map: dict[str, str] | None = None,
    bot_id: str | None = None,
) -> dict:
    """从用户消息中提取差异或新增的事实/记忆以及世界设定。"""
    user_content = "Recent User Messages:\n" + "\n".join(recent_messages)
    if active_memories:
        user_content += "\n\nKnown Active Memories:\n" + "\n".join(f"- {m}" for m in active_memories)

    system_prompt = memory_extractor_template.render(
        persona=_persona_data,
        bot_id=bot_id or _bot_id,
        bot_aliases=sorted(list(get_all_bot_aliases(_persona_data))),
        identity_map=identity_map or {},
    )
    result = await _call(
        _judge_model,
        system_prompt,
        user_content,
    )
    return result


async def consolidate_memory(
    current_profile: str,
    active_facts: list[dict],
    user_name: str | None = None,
    identity_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Cyber Echo — 将碎片化事实融合进长期用户画像。"""
    facts_text = "\n".join(
        f"ID: {f['id']} | Time: {_format_ts(f['timestamp'])} | Content: {f['content']}"
        for f in active_facts
    )
    user_content = (
        f"Current Description:\n{current_profile}\n\n"
        f"New Active Facts (Current Time: {_format_ts(time.time())}):\n{facts_text}"
    )
    logger.info("巩固记忆：%d 条事实", len(active_facts))
    system_prompt = memory_consolidator_template.render(
        persona=_persona_data,
        bot_id=_bot_id,
        user_name=user_name,
        identity_map=identity_map or {},
    )
    return await _call(_chat_model, system_prompt, user_content)


async def consolidate_group_vibe(
    current_vibe: str,
    behavior_overlay: str,
    recent_summaries: list[str],
) -> dict[str, Any]:
    """Cyber Echo — 从话题摘要沉淀群氛围印象。"""
    system_prompt = group_consolidator_template.render(
        behavior_overlay=behavior_overlay,
        current_group_vibe=current_vibe,
        recent_topics=recent_summaries,
    )
    logger.info("群氛围更新：%d 条话题摘要", len(recent_summaries))
    return await _call(_judge_model, system_prompt, "请更新群聊印象。")
