"""
消息数据模型。

用于统一消息内容（MessageContent）的表示、验证与序列化，替代松散的字典协议。
"""

from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel, Field


class MessageContent(BaseModel):
    """
    统一消息内容模型。
    
    Attributes:
        text: 消息正文文本（含 CQ:face / CQ:image 解析后的替代标记）
        images: 关联的本地落盘图片路径列表
    """
    text: str = ""
    images: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式，仅当存在图片时包含 images 字段以保持向下兼容。"""
        res: dict[str, Any] = {"text": self.text}
        if self.images:
            res["images"] = list(self.images)
        return res

    def to_json(self) -> str:
        """序列化为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MessageContent:
        """从字典构建 MessageContent。"""
        if not data or not isinstance(data, dict):
            return cls(text="")
        raw_text = data.get("text")
        text_str = "" if raw_text is None else str(raw_text)

        raw_images = data.get("images")
        if raw_images is None:
            images_list = []
        elif isinstance(raw_images, str):
            images_list = [raw_images]
        elif isinstance(raw_images, (list, tuple, set)):
            images_list = [str(x) for x in raw_images]
        else:
            images_list = []

        return cls(text=text_str, images=images_list)

    @classmethod
    def from_json(cls, raw: str | None) -> MessageContent:
        """从 JSON 字符串反序列化，若解析失败或为纯文本则作为普通文本兜底。"""
        if raw is None:
            return cls(text="")
        if not isinstance(raw, str):
            raw = str(raw)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return cls.from_dict(parsed)
            return cls(text=str(parsed))
        except (json.JSONDecodeError, TypeError):
            return cls(text=raw)

    @classmethod
    def from_raw(cls, content: MessageContent | dict[str, Any] | str | Any) -> MessageContent:
        """容错转换器：支持 MessageContent、dict、str 或任意对象。"""
        if content is None:
            return cls(text="")
        if isinstance(content, cls):
            return content
        if isinstance(content, dict):
            return cls.from_dict(content)
        if isinstance(content, str):
            return cls.from_json(content)
        return cls(text=str(content))

    def get(self, key: str, default: Any = None) -> Any:
        """字典兼容 get 方法。"""
        if key == "text":
            return self.text
        if key == "images":
            return self.images
        return default

    def __getitem__(self, key: str) -> Any:
        """字典兼容下标访问。"""
        if key == "text":
            return self.text
        if key == "images":
            return self.images
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        """字典兼容 in 运算符（如 `'images' in content` 或 `'text' in content`）。"""
        if key == "text":
            return True
        if key == "images":
            return bool(self.images)
        return False

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def __str__(self) -> str:
        return self.text
