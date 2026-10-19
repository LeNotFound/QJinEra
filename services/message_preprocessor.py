"""
消息预处理服务。

职责：
- CQ 码解析（QQ 表情转义、@ 提取、冗余 CQ 码清理）
- 图片提取、过滤（如跳过 GIF 动画表情避免堵塞上下文）及异步下载落盘
- 统一输出标准 MessageContent 模型及内存 base64 图片列表
- @提及（is_mentioned）判定
"""

from __future__ import annotations

import asyncio
import base64
import html
import os
import re
import uuid
from typing import Any

import httpx

from logger import get_logger
from models.message import MessageContent
from services.cq_faces import get_face_text
from utils import spawn_task

logger = get_logger("MessagePreprocessor")

IMAGE_DIR = "data/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """获取或初始化共享的异步 HTTP 客户端。"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient()
    return _http_client


def _save_image(path: str, data: bytes) -> None:
    """同步文件写入，供 asyncio.to_thread 调用实现真实异步落盘。"""
    try:
        with open(path, "wb") as f:
            f.write(data)
    except Exception as e:
        logger.error("保存图片至 %s 失败: %s", path, e)


async def preprocess_message(raw: str | None) -> tuple[MessageContent, list[str]]:
    """
    预处理 CQ 码原始消息。
    
    处理步骤：
    1. 替换 CQ:face 为可读表情描述（容错解析非标准 face_id）
    2. 提取并下载 CQ:image（支持 url/file=http/base64，跳过 GIF 动画表情避免堵塞上下文）
    3. 规范化 CQ:at 标记并移除其他无用 CQ 码
    4. 封装为标准 MessageContent 并返回 (MessageContent, memory_images)
    """
    raw_str = str(raw or "")

    # 1. 替换 CQ:face
    def replace_face(match: re.Match) -> str:
        cq_content = match.group(1) or ""
        params = dict(p.split("=", 1) for p in cq_content.split(",") if "=" in p)
        raw_id = params.get("id", "").strip()
        try:
            face_id = int(raw_id)
            return f" {get_face_text(face_id)} "
        except (ValueError, TypeError):
            return f" [表情:{raw_id}] " if raw_id else " [表情] "

    raw_str = re.sub(r"\[CQ:face(?:,([^\]]*))?\]", replace_face, raw_str)

    # 2. 提取并下载 CQ:image
    images: list[str] = []
    memory_images: list[str] = []
    image_replacements: dict[str, str] = {}

    image_matches = re.finditer(r"\[CQ:image(?:,([^\]]*))?\]", raw_str)
    for match in image_matches:
        full_match = match.group(0)
        if full_match in image_replacements:
            continue

        cq_content = match.group(1) or ""
        params = dict(p.split("=", 1) for p in cq_content.split(",") if "=" in p)

        # 提取动态表情的 summary (如 &#91;晚安&#93; -> [晚安])
        summary = params.get("summary", "")
        if summary:
            summary_text = html.unescape(summary)
            placeholder = f" [动画表情:{summary_text}] "
        else:
            placeholder = " [图片] "

        image_replacements[full_match] = placeholder

        file_val = params.get("file", "")
        url = params.get("url") or (file_val if file_val.startswith(("http://", "https://")) else None)
        is_gif = file_val.endswith(".gif") or "emoji_id" in params

        if not is_gif:
            if file_val.startswith("base64://"):
                try:
                    b64_data = file_val[len("base64://"):]
                    image_data = base64.b64decode(b64_data)
                    file_uuid = str(uuid.uuid4())
                    file_path = os.path.join(IMAGE_DIR, f"{file_uuid}.jpg").replace("\\", "/")
                    spawn_task(asyncio.to_thread(_save_image, file_path, image_data))
                    images.append(file_path)
                    memory_images.append(b64_data)
                except Exception as e:
                    logger.error("解析 base64 图片失败: %s", e)
            elif url:
                try:
                    # 处理可能被转义的 URL 实体
                    url = url.replace("&amp;", "&")
                    client = get_http_client()
                    resp = await client.get(url, timeout=10.0)
                    resp.raise_for_status()
                    image_data = resp.content
                    b64_data = base64.b64encode(image_data).decode("utf-8")
                    file_uuid = str(uuid.uuid4())
                    file_path = os.path.join(IMAGE_DIR, f"{file_uuid}.jpg").replace("\\", "/")

                    # 真正异步落盘，防止阻塞事件循环
                    spawn_task(asyncio.to_thread(_save_image, file_path, image_data))

                    images.append(file_path)
                    memory_images.append(b64_data)
                except Exception as e:
                    logger.error("下载图片失败 %s: %s", url, e)

    # 替换图片 CQ 码为 placeholder
    text = raw_str
    for img_cq, placeholder in image_replacements.items():
        text = text.replace(img_cq, placeholder)

    # 3. 处理 @ 提及与去除其他不需要的 CQ 码
    text = re.sub(r"\[CQ:at,[^\]]*?qq=(\d+|all)[^\]]*\]", r"[@\1] ", text)
    text = re.sub(r"\[CQ:[^\]]+\]", "", text).strip()

    final_text = text or "[图片/表情]"
    content = MessageContent(text=final_text, images=images)
    return content, memory_images


def is_mentioned(event: Any) -> bool:
    """检查 Bot 是否在消息中被 @。"""
    self_id = getattr(event, "self_id", None)
    if not self_id:
        return False
    msg_str = str(getattr(event, "message", ""))
    pattern = rf"\[CQ:at,[^\]]*?qq={re.escape(str(self_id))}(?:,[^\]]*|\])"
    return bool(re.search(pattern, msg_str))
