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

from config import config
from logger import get_logger

logger = get_logger("LLM")

# ---------------------------------------------------------------------------
#  从配置中一次性读取（运行时不再访问 config）
# ---------------------------------------------------------------------------

_api_key: str = config.llm.api_key
_api_base: str = config.llm.api_base
_proxy: str | None = config.llm.proxy
_judge_model: str = config.llm.judge_model
_chat_model: str = config.llm.chat_model

_prompts = config.prompts          # PromptsConfig (frozen)

_client = openai.AsyncOpenAI(
    api_key=_api_key,
    base_url=_api_base,
    http_client=openai.DefaultAsyncHttpxClient(proxy=_proxy) if _proxy else None,
)


# ---------------------------------------------------------------------------
#  内部工具
# ---------------------------------------------------------------------------

async def _call(
    model: str,
    system_prompt: str,
    user_content: str,
    *,
    json_mode: bool = True,
) -> dict[str, Any]:
    """统一的 LLM 调用入口。"""
    logger.debug("请求 %s ...", model)
    try:
        resp = await _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"} if json_mode else None,
        )
        content = resp.choices[0].message.content
        logger.debug("响应 (%s): %s", model, content[:200] if content else "")
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
    return await _call(
        _judge_model,
        _prompts.judge_system,
        json.dumps(context, ensure_ascii=False),
    )


async def generate_chat(context: dict[str, Any]) -> dict[str, Any]:
    """调用 Writer 模型生成聊天回复。"""
    return await _call(
        _chat_model,
        _prompts.chat_system,
        json.dumps(context, ensure_ascii=False),
    )


async def generate_proactive_topic() -> dict[str, Any]:
    """生成主动话题（冷场时使用）。"""
    return await _call(
        _chat_model,
        _prompts.proactive_system,
        "请开始你的表演",
    )


async def extract_memories(recent_messages: list[str]) -> list[str]:
    """从用户消息中提取事实/记忆。"""
    result = await _call(
        _judge_model,
        _prompts.memory_extractor_system,
        "Recent User Messages:\n" + "\n".join(recent_messages),
    )
    return result.get("facts", [])


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
    return await _call(_chat_model, _prompts.memory_consolidator_system, user_content)
