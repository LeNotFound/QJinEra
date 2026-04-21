"""
LLM 服务 — 封装所有与大模型的交互。

职责：Judge 判定 / Writer 生成 / 记忆提取 / 记忆巩固 (Cyber Echo)。
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any

import openai
from jinja2 import Environment, FileSystemLoader

from config import config
from logger import get_logger

logger = get_logger("LLM")

# ---------------------------------------------------------------------------
#  从配置中一次性读取（运行时不再访问 config）
# ---------------------------------------------------------------------------

_api_key: str = config.llm.api_key
_api_base: str = config.llm.api_base
_proxy: str | None = config.llm.proxy
_timeout: float = config.llm.timeout
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

async def _call(
    model: str,
    system_prompt: str,
    user_content: str,
    images: list[str] = None,
    *,
    json_mode: bool = True,
) -> dict[str, Any]:
    """统一的 LLM 调用入口。"""
    logger.debug("请求 %s ... system_prompt 长度: %d, user_content 长度: %d\n完整 user_content:\n%s", model, len(system_prompt), len(user_content), user_content)
    
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

    try:
        resp = await _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_content},
            ],
            response_format={"type": "json_object"} if json_mode else None,
        )
        content = resp.choices[0].message.content
        logger.debug("响应 (%s): %s", model, content if content else "")
        return json.loads(content) if json_mode else content
    except Exception:
        logger.error("LLM 调用失败 (%s)", model, exc_info=True)
        return {}


def _format_ts(ts: float) -> str:
    """将 Unix 时间戳转为可读字符串。"""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
#  公开 API
# ---------------------------------------------------------------------------

async def judge_interruption(context: dict[str, Any]) -> dict[str, Any]:
    """调用 Judge 模型判断是否插话。"""
    bot_id = context.get("bot_id", "")
    group_context = context.pop("group_context", None) or {}
    recent_images = context.pop("recent_images", [])

    system_prompt = judge_template.render(
        persona=_persona_data, bot_id=bot_id, group_context=group_context,
    )
    return await _call(
        _judge_model,
        system_prompt,
        json.dumps(context, ensure_ascii=False),
        images=recent_images,
    )


async def generate_chat(context: dict[str, Any]) -> dict[str, Any]:
    """调用 Writer 模型生成聊天回复。"""
    # 提取给 Jinja 的变量，避免未定义错误
    user_profile = context.pop("user_profile_raw", {}) or {}
    world_lore = context.pop("world_lore", []) or []
    group_context = context.pop("group_context", None) or {}
    recent_images = context.pop("recent_images", [])

    # 目前 Life Engine 进度还在 Phase 2 的 DDL 阶段，所以暂时写死一个默认的兜底字典
    bot_status = {"energy": 100.0, "mood": "平静"}
    
    system_prompt = chat_template.render(
        persona=_persona_data,
        bot_status=bot_status,
        user_profile=user_profile,
        world_lore=world_lore,
        group_context=group_context,
    )
    
    return await _call(
        _chat_model,
        system_prompt,
        json.dumps(context, ensure_ascii=False),
        images=recent_images,
    )


async def generate_proactive_topic() -> dict[str, Any]:
    """生成主动话题（冷场时使用）。"""
    system_prompt = proactive_template.render(persona=_persona_data)
    return await _call(
        _chat_model,
        system_prompt,
        "请开始你的表演",
    )


async def extract_memories(recent_messages: list[str], active_memories: list[str] = None) -> dict:
    """从用户消息中提取差异或新增的事实/记忆以及世界设定。"""
    user_content = "Recent User Messages:\n" + "\n".join(recent_messages)
    if active_memories:
        user_content += "\n\nKnown Active Memories:\n" + "\n".join(f"- {m}" for m in active_memories)

    system_prompt = memory_extractor_template.render(persona=_persona_data, bot_id=_bot_id)
    result = await _call(
        _judge_model,
        system_prompt,
        user_content,
    )
    return result


async def consolidate_memory(
    current_profile: str,
    active_facts: list[dict],
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
    system_prompt = memory_consolidator_template.render(persona=_persona_data, bot_id=_bot_id)
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
